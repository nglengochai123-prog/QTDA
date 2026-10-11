"""Quỹ tiền ca, kết ca, báo cáo cuối ca, đối soát và chênh lệch tích lũy (FR-07, 08, 09, 12, 13)."""

from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.audit.models import Action
from apps.audit.services import record
from apps.core import params
from apps.core.idempotency import run_once

from .models import CashEntry, Discrepancy, ExpenseCategory, Refund, Shift, ShiftReport


def _money(value, label):
    try:
        amount = int(str(value).replace(".", "").replace(",", "").strip())
    except (TypeError, ValueError):
        raise ValidationError(f"{label} không hợp lệ.")
    if amount < 0:
        raise ValidationError(f"{label} không được âm.")
    return amount


def _require_open(shift):
    if shift.status != Shift.Status.OPEN:
        raise ValidationError("Ca đã kết; không ghi thêm vào quỹ của ca này.")


# ---------------- Quỹ tiền mặt ca (FR-07, BRU-05) ----------------

def add_cash_entry(user, operation_key, shift_id, kind, amount, *, category="", note="", receipt=None, receiver_id=None):
    payload = {"shift": int(shift_id), "kind": kind, "amount": str(amount), "category": category, "note": note,
               "receiver": receiver_id, "receipt": getattr(receipt, "name", "")}

    def action():
        shift = Shift.objects.select_for_update().get(pk=payload["shift"])
        _require_open(shift)
        value = _money(amount, "Số tiền")
        if kind not in CashEntry.Kind.values:
            raise ValidationError("Chọn loại bút toán.")
        fields = {}
        if kind == CashEntry.Kind.OPENING:
            if shift.cash_entries.filter(kind=CashEntry.Kind.OPENING).exists():
                raise ValidationError("Ca này đã xác nhận tiền đầu ca.")
        elif kind == CashEntry.Kind.EXPENSE:
            if value == 0:
                raise ValidationError("Số tiền chi phải lớn hơn 0.")
            if category not in ExpenseCategory.values or category == ExpenseCategory.MATERIALS:
                raise ValidationError("Chọn danh mục chi. Chi nguyên vật liệu ghi qua phiếu nhập.")
            if not note.strip():
                raise ValidationError("Ghi nội dung khoản chi.")
            limit = params.get("receipt_photo_threshold")
            if value >= limit and not receipt:
                raise ValidationError(f"Khoản chi từ {limit:,} đồng phải có ảnh chứng từ.".replace(",", "."))  # AC-15
            fields.update(category=category, receipt=receipt or "")
        elif kind == CashEntry.Kind.HANDOVER:
            if value == 0:
                raise ValidationError("Số tiền nộp phải lớn hơn 0.")
            if not receiver_id or int(receiver_id) == user.pk:
                raise ValidationError("Chọn người nhận tiền khác người nộp.")
            fields["receiver_id"] = int(receiver_id)
        entry = CashEntry.objects.create(store=shift.store, shift=shift, kind=kind, amount=value, note=note[:255],
                                         actor=user, operation_key=operation_key, **fields)
        record(Action.CREATE, actor=user, obj=entry, object_type="shifts.CashEntry",
               after={"ca": str(shift), "loai": entry.get_kind_display(), "so_tien": value,
                      "danh_muc": entry.get_category_display() if entry.category else "", "noi_dung": note})
        return {"entry": entry.pk, "text": str(entry)}

    return run_once(operation_key, "cash_entry", payload, action, actor=user)


@transaction.atomic
def confirm_handover(user, entry_id):
    """Người nhận xác nhận đã nhận tiền nộp giữa ca; chỉ khi đó khoản nộp mới có hiệu lực."""
    entry = CashEntry.objects.select_for_update().get(pk=entry_id, kind=CashEntry.Kind.HANDOVER)
    if entry.receiver_id != user.pk:
        raise ValidationError("Chỉ người nhận mới xác nhận được khoản nộp này.")
    if entry.confirmed_at is None:
        entry.confirmed_at = timezone.now()
        CashEntry.objects.filter(pk=entry.pk).update(confirmed_at=entry.confirmed_at)
        record(Action.STATUS_CHANGE, actor=user, obj=entry, object_type="shifts.CashEntry",
               after={"xac_nhan_nhan": entry.amount})
    return entry


def record_refund(order, approver, request_id):
    """Hoàn tiền khi hủy hóa đơn đã thanh toán được duyệt (BRU-05, BRU-08, BRU-10).

    - Phương thức hoàn: theo phương thức khách đã trả (giả định GD-07, chờ Chủ quán xác nhận).
    - Ca ghi nhận: ca đang mở lúc duyệt, vì tiền hoàn rời quỹ của ca đó; doanh thu vẫn thuộc ca đã thu.
    - Mỗi yêu cầu chỉ sinh tối đa một khoản hoàn (ràng buộc duy nhất theo mã yêu cầu).
    """
    payment = order.payment
    if payment is None or order.total == 0:
        return None
    existing = Refund.objects.filter(request_id_ref=request_id).first()
    if existing is not None:
        return existing
    shift = Shift.objects.current()
    if shift is None:
        raise ValidationError("Không có ca đang mở để ghi khoản hoàn tiền; mở ca rồi duyệt lại.")
    method = Refund.Method.CASH if payment.method == "tien_mat" else Refund.Method.TRANSFER
    refund = Refund.objects.create(store=order.store, shift=shift, order_code=order.code, method=method,
                                   amount=order.total, approved_by=approver, request_id_ref=request_id)
    record(Action.CREATE, actor=approver, obj=refund, object_type="shifts.Refund",
           after={"don": order.code, "phuong_thuc": refund.get_method_display(), "so_tien": refund.amount,
                  "ca": str(shift)})
    return refund


# ---------------- Số liệu ca ----------------

def figures(shift):
    from apps.orders.models import Payment

    payments = Payment.objects.filter(shift=shift)
    revenue_cash = payments.filter(method="tien_mat").aggregate(s=Sum("amount"))["s"] or 0
    revenue_transfer = payments.filter(method="chuyen_khoan").aggregate(s=Sum("amount"))["s"] or 0
    if shift.closed_cash_revenue is not None:
        revenue_cash, revenue_transfer = shift.closed_cash_revenue, shift.closed_transfer_revenue
    entries = list(shift.cash_entries.all())
    opening = sum(e.amount for e in entries if e.kind == CashEntry.Kind.OPENING)
    expenses = sum(e.amount for e in entries if e.kind == CashEntry.Kind.EXPENSE)
    handovers = sum(e.amount for e in entries if e.kind == CashEntry.Kind.HANDOVER and e.is_effective)
    refunds_cash = shift.refunds.filter(method=Refund.Method.CASH).aggregate(s=Sum("amount"))["s"] or 0
    refunds_transfer = shift.refunds.filter(method=Refund.Method.TRANSFER).aggregate(s=Sum("amount"))["s"] or 0
    expected_cash = opening + revenue_cash - refunds_cash - expenses - handovers  # BRU-10
    return {"opening": opening, "revenue_cash": revenue_cash, "revenue_transfer": revenue_transfer,
            "refunds_cash": refunds_cash, "refunds_transfer": refunds_transfer, "expenses": expenses,
            "handovers": handovers, "expected_cash": expected_cash,
            "net_transfer": revenue_transfer - refunds_transfer,
            "revenue_total": revenue_cash + revenue_transfer,
            "net_revenue": revenue_cash + revenue_transfer - refunds_cash - refunds_transfer}


# ---------------- Kết ca (FR-08, BRU-06) ----------------

def close_blockers(shift):
    from apps.orders.models import AdjustmentRequest, Order

    blockers = []
    open_orders = Order.objects.filter(shift=shift).exclude(status__in=[Order.Status.PAID, Order.Status.CANCELLED])
    for order in open_orders:
        blockers.append(f"Bàn {order.table.code}: đơn {order.code} chưa thanh toán ({order.get_status_display()}).")
    pending = AdjustmentRequest.objects.filter(status=AdjustmentRequest.Status.PENDING, order__shift=shift)
    for req in pending:
        blockers.append(f"Yêu cầu \"{req.summary()}\" của đơn {req.order.code} đang chờ duyệt.")
    if not shift.cash_entries.filter(kind=CashEntry.Kind.OPENING).exists():
        blockers.append("Chưa xác nhận tiền đầu ca.")
    unconfirmed = shift.cash_entries.filter(kind=CashEntry.Kind.HANDOVER, confirmed_at__isnull=True)
    for e in unconfirmed:
        blockers.append(f"Khoản nộp {e.amount:,} đ cho {e.receiver} chưa được xác nhận.".replace(",", "."))
    return blockers


@transaction.atomic
def carry_over(user, order_id, to_shift_id, reason):
    """Chuyển đơn chưa thanh toán sang ca kế tiếp kèm lý do (BRU-06)."""
    from apps.orders.models import Order

    if not reason.strip():
        raise ValidationError("Ghi lý do chuyển đơn sang ca sau.")
    order = Order.objects.select_for_update().get(pk=order_id)
    target = Shift.objects.get(pk=to_shift_id, status=Shift.Status.OPEN)
    if order.shift_id == target.pk:
        raise ValidationError("Chọn ca kế tiếp khác ca hiện tại.")
    before = str(order.shift) if order.shift_id else ""
    order.shift = target
    order.save(update_fields=["shift", "updated_at"])
    record(Action.UPDATE, actor=user, obj=order, object_type="orders.Order", before={"ca": before},
           after={"ca": str(target)}, reason=reason)


@transaction.atomic
def close_shift(user, shift_id):
    shift = Shift.objects.select_for_update().get(pk=shift_id)
    if shift.status == Shift.Status.CLOSED:
        return shift
    blockers = close_blockers(shift)
    if blockers:
        raise ValidationError(blockers)  # AC-16
    f = figures(shift)
    shift.status = Shift.Status.CLOSED
    shift.closed_at, shift.closed_by = timezone.now(), user
    shift.closed_cash_revenue, shift.closed_transfer_revenue = f["revenue_cash"], f["revenue_transfer"]
    shift.save(update_fields=["status", "closed_at", "closed_by", "closed_cash_revenue", "closed_transfer_revenue",
                              "updated_at"])
    record(Action.STATUS_CHANGE, actor=user, obj=shift, object_type="shifts.Shift",
           after={"trang_thai": "Đã kết ca", "doanh_thu_tien_mat": f["revenue_cash"],
                  "doanh_thu_chuyen_khoan": f["revenue_transfer"]})
    return shift


# ---------------- Báo cáo cuối ca và đối soát (FR-08, FR-12, BRU-10) ----------------

@transaction.atomic
def submit_report(user, shift_id, counted_cash, transfer_received, transfer_refunded=0, incidents=""):
    shift = Shift.objects.select_for_update().get(pk=shift_id)
    if shift.status != Shift.Status.CLOSED:
        raise ValidationError("Kết ca trước rồi mới lập báo cáo cuối ca.")
    existing = ShiftReport.objects.filter(shift=shift).first()
    if existing is not None:
        same = (existing.counted_cash, existing.transfer_received, existing.transfer_refunded) == (
            _money(counted_cash, "Tiền mặt đếm"), _money(transfer_received, "Tiền chuyển khoản nhận"),
            _money(transfer_refunded or 0, "Tiền hoàn chuyển khoản"))
        if same:
            return existing  # gửi lại sau mất phản hồi: không đối soát lần hai
        raise ValidationError("Ca này đã có báo cáo cuối ca; số liệu khác phải ghi bằng giải trình chênh lệch.")
    report = ShiftReport.objects.create(
        store=shift.store, shift=shift, counted_cash=_money(counted_cash, "Tiền mặt đếm"),
        transfer_received=_money(transfer_received, "Tiền chuyển khoản nhận"),
        transfer_refunded=_money(transfer_refunded or 0, "Tiền hoàn chuyển khoản"), incidents=incidents,
        submitted_by=user)
    record(Action.CREATE, actor=user, obj=report, object_type="shifts.ShiftReport",
           after={"tien_mat_dem": report.counted_cash, "ck_nhan": report.transfer_received,
                  "ck_hoan": report.transfer_refunded, "su_co": incidents})
    reconcile(shift)
    return report


def reconcile(shift):
    """So số phải có với thực tế, lưu mọi chênh lệch khác 0 theo phương thức và Quản lý ca (FR-12)."""
    report = shift.report
    f = figures(shift)
    at = shift.closed_at or shift.ends_at  # ngưỡng của ca là ngưỡng có hiệu lực lúc kết ca
    cash_limit, transfer_limit = params.get("cash_threshold", at=at), params.get("transfer_threshold", at=at)
    rows = [
        (Discrepancy.Method.CASH, f["expected_cash"], report.counted_cash, cash_limit),
        (Discrepancy.Method.TRANSFER_IN, f["revenue_transfer"], report.transfer_received, transfer_limit),
        (Discrepancy.Method.TRANSFER_REFUND, f["refunds_transfer"], report.transfer_refunded, transfer_limit),
    ]
    created = []
    for method, expected, actual, threshold in rows:
        # Với tiền hoàn, chi ra nhiều hơn mức đã duyệt là thiếu tiền: đổi dấu để "âm" luôn nghĩa là thiếu.
        diff = (expected - actual) if method == Discrepancy.Method.TRANSFER_REFUND else (actual - expected)
        if diff == 0:
            continue
        d = Discrepancy.objects.create(store=shift.store, shift=shift, method=method, expected=expected,
                                       actual=actual, difference=diff, manager=shift.approver,
                                       over_threshold=abs(diff) > threshold, threshold=threshold)
        record(Action.CREATE, obj=d, object_type="shifts.Discrepancy", actor_label="hệ thống",
               after={"phuong_thuc": d.get_method_display(), "phai_co": expected, "thuc_te": actual,
                      "chenh_lech": diff, "nguong": threshold, "vuot_nguong": d.over_threshold})
        created.append(d)
    check_accumulated(shift)
    return created


@transaction.atomic
def explain(user, discrepancy_id, text):
    d = Discrepancy.objects.select_for_update().get(pk=discrepancy_id)
    if user.pk != d.manager_id and not user.is_owner:
        raise ValidationError("Chỉ Quản lý ca phụ trách giải trình khoản chênh lệch này.")
    if not text.strip():
        raise ValidationError("Ghi nội dung giải trình.")
    d.explanation, d.explained_at = text, timezone.now()
    d.save(update_fields=["explanation", "explained_at", "updated_at"])
    record(Action.UPDATE, actor=user, obj=d, object_type="shifts.Discrepancy", after={"giai_trinh": text})
    return d


@transaction.atomic
def decide(user, discrepancy_id, accept):
    if not user.is_owner:
        raise ValidationError("Chỉ Chủ quán quyết định chấp nhận giải trình.")
    d = Discrepancy.objects.select_for_update().get(pk=discrepancy_id)
    wanted = Discrepancy.Decision.ACCEPTED if accept else Discrepancy.Decision.REJECTED
    if d.decision == wanted:
        return d  # bấm lại cùng quyết định: không ghi thêm
    if d.decision:
        raise ValidationError("Khoản chênh lệch này đã có quyết định.")
    if d.over_threshold and not d.explanation:
        raise ValidationError("Chờ Quản lý ca giải trình trước khi quyết định.")
    d.decision = Discrepancy.Decision.ACCEPTED if accept else Discrepancy.Decision.REJECTED
    d.decided_by, d.decided_at = user, timezone.now()
    d.save(update_fields=["decision", "decided_by", "decided_at", "updated_at"])
    record(Action.STATUS_CHANGE, actor=user, obj=d, object_type="shifts.Discrepancy",
           after={"quyet_dinh": d.get_decision_display()})
    check_accumulated(d.shift)
    return d


def check_accumulated(shift):
    """Cộng dồn thiếu tiền chưa giải thích theo Quản lý ca và toàn quán trong tháng (FR-13, BRU-11)."""
    from apps.control.models import ExceptionCase
    from apps.control.services import open_exception

    start = timezone.localtime(shift.starts_at)
    period = f"{start:%Y-%m}"
    month = Discrepancy.objects.filter(shift__starts_at__year=start.year, shift__starts_at__month=start.month,
                                       difference__lt=0)
    shortages = [d for d in month if d.is_unexplained_shortage]
    by_manager = {}
    for d in shortages:
        by_manager.setdefault(d.manager_id, []).append(d)
    results = []
    for manager_id, items in by_manager.items():
        total = sum(-d.difference for d in items)
        if total > params.get("accumulated_manager_threshold"):
            exc = open_exception(
                ExceptionCase.Kind.ACCUMULATED_MANAGER, employee=items[0].manager, period=period, store=shift.store,
                rule=f"Thiếu tiền chưa giải thích tích lũy tháng {period} vượt "
                     f"{params.get('accumulated_manager_threshold'):,} đ".replace(",", "."),
                amount=total, detail=f"Tích lũy {total:,} đ qua {len(items)} ca.".replace(",", "."))
            exc.shifts.add(*{d.shift for d in items})
            results.append(exc)
    store_total = sum(-d.difference for d in shortages)
    if store_total > params.get("accumulated_store_threshold"):
        exc = open_exception(ExceptionCase.Kind.ACCUMULATED_STORE, period=period, store=shift.store,
                             rule=f"Thiếu tiền chưa giải thích của toàn quán tháng {period} vượt ngưỡng",
                             amount=store_total, detail=f"Tích lũy {store_total:,} đ.".replace(",", "."))
        exc.shifts.add(*{d.shift for d in shortages})
        results.append(exc)
    return results


def accumulated_report(year, month):
    """Tích lũy thiếu chưa giải thích theo Quản lý ca, loại ca và tháng (AC-28)."""
    rows = {}
    for d in Discrepancy.objects.filter(shift__starts_at__year=year, shift__starts_at__month=month,
                                        difference__lt=0).select_related("manager", "shift"):
        if not d.is_unexplained_shortage:
            continue
        key = (str(d.manager), d.shift.name)
        rows[key] = rows.get(key, 0) + (-d.difference)
    return [{"manager": k[0], "shift_type": k[1], "total": v} for k, v in sorted(rows.items())]


# ---------------- Tình trạng dữ liệu ca (FR-09, BRU-07) ----------------

def data_status(shift, now=None):
    now = now or timezone.now()
    deadline = shift.ends_at + timedelta(hours=params.get("shift_report_hours", at=shift.ends_at))
    has_report = ShiftReport.objects.filter(shift=shift).exists()
    issues = []
    if shift.status == Shift.Status.OPEN and now > shift.ends_at:
        issues.append("Chưa kết ca")
    if not has_report and now > deadline:
        issues.append("Thiếu báo cáo cuối ca")  # AC-18
    return {"shift": shift, "closed": shift.status == Shift.Status.CLOSED, "has_report": has_report,
            "deadline": deadline, "issues": issues, "overdue": bool(issues)}
