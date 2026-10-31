"""Tạo ngoại lệ theo quy tắc, xem xét, vụ việc tổn thất và giá trị kiểm soát tạm tính (BRU-12, 14, 15, 16)."""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.audit.models import Action
from apps.audit.services import record
from apps.core import params
from apps.core.models import Store

from .models import (ExceptionCase, ExceptionReview, LossCase, LossEvidence, LossRecovery, LossVerification)

Kind = ExceptionCase.Kind


def open_exception(kind, *, rule, employee=None, shift=None, period="", order=None, request=None, amount=0,
                   detail="", severity=ExceptionCase.Severity.IMPORTANT, store=None, one_per_scope=True,
                   ingredient=None):
    """Tạo ngoại lệ, hoặc gắn thêm vào ngoại lệ đang mở cùng loại cho cùng nhân viên và ca (BRU-12)."""
    existing = None
    if one_per_scope:
        existing = ExceptionCase.objects.filter(kind=kind, status=ExceptionCase.Status.OPEN, employee=employee,
                                                shift=shift, period=period, ingredient=ingredient).first()
    if existing is None:
        existing = ExceptionCase.objects.create(
            store=store or Store.get_default(), kind=kind, rule=rule, employee=employee, shift=shift, period=period,
            order=order, amount=amount, detail=detail, severity=severity, ingredient=ingredient)
        record(Action.CREATE, obj=existing, object_type="control.ExceptionCase", actor_label="hệ thống",
               after={"loai": existing.get_kind_display(), "quy_tac": rule, "gia_tri": amount}, reason=detail[:200])
    else:
        existing.amount = max(existing.amount, amount)
        if detail and detail not in existing.detail:
            existing.detail = (existing.detail + "\n" + detail).strip()
        existing.save(update_fields=["amount", "detail", "updated_at"])
    if request is not None:
        existing.requests.add(request)
    if shift is not None:
        existing.shifts.add(shift)
    return existing


# ---------------- Xem xét ngoại lệ (FR-17, BRU-14) ----------------

@transaction.atomic
def review(user, exception_id, result, money_loss=False, measure="", correction_reason=""):
    if not user.is_owner:
        raise ValidationError("Chỉ Chủ quán được ghi kết quả xem xét ngoại lệ.")  # AC-36
    exc = ExceptionCase.objects.select_for_update().get(pk=exception_id)
    if result not in ExceptionReview.Result.values:
        raise ValidationError("Chọn kết quả Hợp lệ, Nhắc nhở hoặc Vi phạm.")
    previous = exc.effective_review()
    if previous is not None and not correction_reason.strip():
        raise ValidationError("Ngoại lệ đã có kết quả; muốn thay đổi phải lập bản đính chính có lý do và bằng chứng.")
    if money_loss and exc.loss_case_id is None:
        raise ValidationError("Ngoại lệ có tổn thất tiền phải được gắn vào một vụ việc tổn thất trước khi đóng.")  # AC-35
    new = ExceptionReview.objects.create(exception=exc, result=result, money_loss=money_loss, measure=measure,
                                         reviewer=user, corrects=previous, correction_reason=correction_reason)
    if previous is not None:
        previous.superseded_by = new
        previous._superseding = True
        previous.save(update_fields=["superseded_by", "updated_at"])
    exc.status = ExceptionCase.Status.CLOSED
    exc.save(update_fields=["status", "updated_at"])
    record(Action.STATUS_CHANGE, actor=user, obj=exc, object_type="control.ExceptionCase",
           before={"ket_qua": previous.get_result_display()} if previous else None,
           after={"ket_qua": new.get_result_display(), "ton_that_tien": money_loss},
           reason=("Đính chính: " + correction_reason) if previous else measure)
    return new


def reminders_due(now=None):
    """Ngoại lệ chờ xem xét quá số ngày quy định (AC-36)."""
    now = now or timezone.now()
    cutoff = now - timezone.timedelta(days=params.get("review_reminder_days"))
    return ExceptionCase.objects.filter(status=ExceptionCase.Status.OPEN, created_at__lte=cutoff)


# ---------------- Vụ việc tổn thất (FR-18, BRU-15) ----------------

def _next_code():
    last = LossCase.objects.order_by("-id").values_list("code", flat=True).first()
    number = int(last.split("-")[1]) + 1 if last else 1
    return f"VV-{number:03d}"


def open_case(user, title, *, operation_key):
    from apps.core.idempotency import run_once

    def action():
        case = LossCase.objects.create(store=user.store or Store.get_default(), code=_next_code(), title=title,
                                       created_by=user)
        record(Action.CREATE, actor=user, obj=case, object_type="control.LossCase",
               after={"ma": case.code, "tieu_de": title})
        return {"case": case.pk}

    result, _ = run_once(operation_key, "loss_case", {"title": title}, action, actor=user)
    return LossCase.objects.get(pk=result["case"])


@transaction.atomic
def add_evidence(user, case, *, exception=None, discrepancy=None, amount=None, transaction_ref=""):
    if case.verifications.exists():
        raise ValidationError("Vụ việc đã xác minh; không thêm bằng chứng làm thay đổi kỳ đã ghi nhận.")
    if (exception is None) == (discrepancy is None):
        raise ValidationError("Chọn đúng một bằng chứng: ngoại lệ hoặc khoản chênh lệch.")
    if exception is not None:
        if LossEvidence.objects.filter(exception=exception).exists():
            raise ValidationError("Ngoại lệ này đã thuộc một vụ việc khác.")
        amount = exception.amount if amount is None else amount
        transaction_ref = transaction_ref or (exception.order.code if exception.order_id else "")
        exception.loss_case = case
        exception.save(update_fields=["loss_case", "updated_at"])
    else:
        if LossEvidence.objects.filter(discrepancy=discrepancy).exists():
            raise ValidationError("Khoản chênh lệch này đã thuộc một vụ việc khác.")
        if amount is None:
            amount = -discrepancy.difference if discrepancy.difference < 0 else 0
    evidence = LossEvidence.objects.create(case=case, exception=exception, discrepancy=discrepancy, amount=amount,
                                           transaction_ref=transaction_ref)
    record(Action.UPDATE, actor=user, obj=case, object_type="control.LossCase",
           after={"bang_chung": str(exception or discrepancy), "so_tien": amount, "cung_giao_dich": transaction_ref})
    return evidence


@transaction.atomic
def verify(user, case, amount, reason=""):
    if not user.is_owner:
        raise ValidationError("Chỉ Chủ quán xác nhận tổn thất.")
    previous = case.verified_amount()
    if previous == int(amount):
        return  # gửi lại cùng giá trị: không ghi thêm bản xác minh
    if previous is not None and not reason.strip():
        raise ValidationError("Thay đổi giá trị đã xác minh phải có lý do và bằng chứng (bản đính chính).")
    if int(amount) < 0:
        raise ValidationError("Giá trị tổn thất không được âm.")
    verification = LossVerification.objects.create(case=case, amount=int(amount), reason=reason, actor=user)
    case.status = LossCase.Status.CONCLUDED
    case.save(update_fields=["status", "updated_at"])
    record(Action.UPDATE, actor=user, obj=case, object_type="control.LossCase",
           before={"da_xac_minh": previous}, after={"da_xac_minh": int(amount), "verification_id": verification.pk,
                  "period_amounts": loss_periods(case, int(amount)),
                  "period_basis": "Kỳ bằng chứng; phân bổ tỷ lệ khi vụ việc có nhiều kỳ"}, reason=reason)


def recover(user, case, amount, note="", *, operation_key):
    from apps.core.idempotency import run_once

    def action():
        if not user.is_owner:
            raise ValidationError("Chỉ Chủ quán ghi thu hồi tổn thất.")
        if int(amount) <= 0:
            raise ValidationError("Số tiền thu hồi phải lớn hơn 0.")
        remaining = LossCase.objects.select_for_update().get(pk=case.pk).remaining_amount()
        if remaining is None:
            raise ValidationError("Xác nhận giá trị tổn thất trước khi ghi thu hồi.")
        if int(amount) > remaining:
            raise ValidationError(f"Thu hồi vượt phần còn lại {remaining:,} đ.".replace(",", "."))
        LossRecovery.objects.create(case=case, amount=int(amount), note=note[:255], actor=user)
        record(Action.UPDATE, actor=user, obj=case, object_type="control.LossCase", after={"thu_hoi": int(amount)},
               reason=note)
        return {"case": case.pk}

    run_once(operation_key, "loss_recovery", {"case": case.pk, "amount": int(amount), "note": note}, action, actor=user)


# ---------------- Giá trị kiểm soát tạm tính của tháng (BRU-16) ----------------

# Mục tiêu dự án BO-01 (BRU-16): giá trị kiểm soát tạm tính dưới 200.000 đ mỗi tháng.
# Đây là chỉ tiêu để đo kết quả, KHÔNG phải ngưỡng cảnh báo; ngưỡng cảnh báo tích lũy toàn quán
# là tham số accumulated_store_threshold (BRU-11), cấu hình riêng.
BO01_MONTHLY_TARGET = 200000


def _evidence_month(ev):
    """Business date, independent of when the case was entered."""
    if ev.discrepancy_id:
        at = ev.discrepancy.shift.starts_at
    elif ev.exception.shift_id:
        at = ev.exception.shift.starts_at
    elif ev.exception.order_id:
        at = ev.exception.order.created_at
    elif ev.exception.period:
        try:
            from datetime import date
            return date.fromisoformat(ev.exception.period + "-01").strftime("%Y-%m")
        except ValueError:
            at = ev.exception.created_at
    else:
        at = ev.exception.created_at
    return timezone.localtime(at).strftime("%Y-%m")


def _split_amount(amount, weights):
    """Deterministic proportional attribution; integer rounding preserves the exact case amount."""
    total = sum(weights.values())
    if total <= 0:
        return {min(weights): amount} if weights else {}
    parts = {key: amount * value // total for key, value in weights.items()}
    remainder = amount - sum(parts.values())
    for key in sorted(weights, key=lambda key: (-(amount * weights[key] % total), key))[:remainder]:
        parts[key] += 1
    return parts


def loss_periods(case, amount):
    groups = {}
    for ev in case.evidence.select_related("discrepancy__shift", "exception__shift", "exception__order"):
        key = ev.transaction_ref or f"evidence:{ev.pk}"
        month = _evidence_month(ev)
        old_month, old_amount = groups.get(key, (month, 0))
        groups[key] = (min(month, old_month), max(old_amount, ev.amount, 0))
    weights = {}
    for month, value in groups.values():
        weights[month] = weights.get(month, 0) + value
    if not weights or not sum(weights.values()):
        weights = {timezone.localtime(case.created_at).strftime("%Y-%m"): 1}
    return _split_amount(amount, weights)


def _verified_periods(case):
    from apps.audit.models import AuditLog

    latest = case.verifications.order_by("-created_at", "-id").first()
    if latest is None:
        return {}
    log = AuditLog.objects.filter(object_type="control.LossCase", object_id=str(case.pk),
                                  after__verification_id=latest.pk).order_by("-id").first()
    saved = (log.after or {}).get("period_amounts") if log else None
    return saved if saved is not None else loss_periods(case, latest.amount)


def monthly_control(year, month):
    from apps.shifts.models import Discrepancy

    period = f"{year:04d}-{month:02d}"
    verified = recovered = open_cases = 0
    for case in LossCase.objects.prefetch_related("verifications", "recoveries"):
        parts = _verified_periods(case)
        verified += parts.get(period, 0)
        if parts:
            recovered += _split_amount(case.recovered_amount(), parts).get(period, 0)
        if case.status == LossCase.Status.OPEN and period in loss_periods(case, 0):
            open_cases += 1
    in_process = 0
    for d in Discrepancy.objects.current().filter(shift__starts_at__year=year, shift__starts_at__month=month,
                                                difference__lt=0):
        if not d.is_unexplained_shortage:
            continue
        try:
            evidence = d.evidence
        except LossEvidence.DoesNotExist:
            evidence = None
        if evidence is not None and evidence.case.verified_amount() is not None:
            continue
        in_process += -d.difference
    return {"verified": verified, "in_process": in_process, "recovered": recovered,
            "verified_remaining": verified - recovered, "control_value": verified + in_process,
            "target": BO01_MONTHLY_TARGET, "open_cases": open_cases, "updated_at": timezone.now()}
