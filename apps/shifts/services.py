"""Quỹ tiền ca, kết ca, báo cáo cuối ca, đối soát và chênh lệch tích lũy (FR-07, 08, 09, 12, 13)."""

from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.audit.models import Action
from apps.audit.services import record
from apps.core import numbers, params, uploads
from apps.core.idempotency import run_once

from .models import CashEntry, Discrepancy, ExpenseCategory, Refund, Shift, ShiftReport, ShiftReportCorrection


def _money(value, label):
    """Tiền gõ kiểu Việt Nam ("1.390.000", "1 390 000 đ"); số 0 hợp lệ (ví dụ không có chuyển khoản)."""
    if str(value if value is not None else "").strip().startswith("-"):
        raise ValidationError(f"{label} không được âm.")
    return numbers.vnd(value, label, allow_zero=True)


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
            check_cash_on_hand(shift, value, "chi")
            if category not in ExpenseCategory.values or category == ExpenseCategory.MATERIALS:
                raise ValidationError("Chọn danh mục chi. Chi nguyên vật liệu ghi qua phiếu nhập.")
            if not note.strip():
                raise ValidationError("Ghi nội dung khoản chi.")
            limit = params.get("receipt_photo_threshold")
            if value >= limit and not receipt:
                raise ValidationError(f"Khoản chi từ {limit:,} đồng phải có ảnh chứng từ.".replace(",", "."))  # AC-15
            fields.update(category=category, receipt=uploads.check_photo(receipt) or "")
        elif kind == CashEntry.Kind.HANDOVER:
            if value == 0:
                raise ValidationError("Số tiền nộp phải lớn hơn 0.")
            if not receiver_id or int(receiver_id) == user.pk:
                raise ValidationError("Chọn người nhận tiền khác người nộp.")
            from apps.accounts.models import User
            from apps.accounts.permissions import Cap, user_can

            receiver = User.objects.filter(pk=int(receiver_id), is_active=True).first()
            if not user_can(receiver, Cap.CASH_FUND):
                raise ValidationError("Người nhận phải là Chủ quán hoặc thu ngân: chỉ họ bấm xác nhận đã nhận tiền được.")
            check_cash_on_hand(shift, value, "nộp")
            fields["receiver_id"] = receiver.pk
        entry = CashEntry.objects.create(store=shift.store, shift=shift, kind=kind, amount=value, note=note[:255],
                                         actor=user, operation_key=operation_key, **fields)
        if kind == CashEntry.Kind.HANDOVER:
            from apps.core.push import notify_later

            # Ca không kết được khi khoản nộp chưa được xác nhận, nên báo ngay người nhận.
            notify_later([entry.receiver_id], f"Xác nhận nhận {numbers.fmt(value)} đ tiền nộp",
                         f"{user} nộp giữa {shift}. Bấm xác nhận khi đã nhận đủ tiền.", "/ca/")
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


@transaction.atomic
def correct_opening(user, shift_id, amount, reason=""):
    """Sửa tiền đầu ca gõ nhầm khi ca còn mở (người đã xác nhận hoặc Chủ quán), có lý do và nhật ký.

    Tiền đầu ca sai làm số phải có trong két sai cả ca: chi, nộp giữa ca bị chặn oan hoặc chênh lệch giả lúc kết ca."""
    shift = Shift.objects.select_for_update().get(pk=shift_id)
    _require_open(shift)
    entry = shift.cash_entries.filter(kind=CashEntry.Kind.OPENING).first()
    if entry is None:
        raise ValidationError("Ca chưa xác nhận tiền đầu ca.")
    if user.pk != entry.actor_id and not user.is_owner:
        raise ValidationError("Chỉ người đã xác nhận tiền đầu ca hoặc Chủ quán sửa được.")
    reason = str(reason or "").strip()[:255]
    if not reason:
        raise ValidationError("Ghi lý do sửa tiền đầu ca (ví dụ gõ thiếu một số 0).")
    value = _money(amount, "Tiền đầu ca")
    if value == entry.amount:
        return entry
    left = cash_on_hand(shift) - entry.amount + value
    if left < 0:
        raise ValidationError(f"Với tiền đầu ca {numbers.fmt(value)} đ, két theo sổ sẽ âm {numbers.fmt(-left)} đ vì đã "
                              "chi và nộp nhiều hơn; kiểm tra lại số tiền.")
    before = entry.amount
    CashEntry.objects.filter(pk=entry.pk).update(amount=value)
    entry.amount = value
    record(Action.UPDATE, actor=user, obj=entry, object_type="shifts.CashEntry", reason=reason,
           before={"ca": str(shift), "tien_dau_ca": before}, after={"tien_dau_ca": value})
    return entry


@transaction.atomic
def cancel_handover(user, entry_id, reason=""):
    """Bỏ khoản nộp giữa ca chưa được xác nhận: ghi nhầm người nhận hay số tiền, hoặc người nhận báo không nhận được.

    Khoản chưa xác nhận chưa làm đổi số tiền phải có trong két, nên bỏ đi không làm sai số liệu ca; nội dung khoản
    được giữ trong nhật ký. Người nhận, người ghi và Chủ quán làm được, khi ca còn mở."""
    entry = (CashEntry.objects.select_for_update().select_related("shift", "receiver", "actor")
             .get(pk=entry_id, kind=CashEntry.Kind.HANDOVER))
    if entry.confirmed_at is not None:
        raise ValidationError("Khoản nộp đã được người nhận xác nhận; không bỏ được.")
    if entry.shift.status != Shift.Status.OPEN:
        raise ValidationError(f"{entry.shift} đã kết; không sửa quỹ ca này.")
    if user.pk not in (entry.receiver_id, entry.actor_id) and not user.is_owner:
        raise ValidationError("Chỉ người nộp, người nhận hoặc Chủ quán bỏ được khoản nộp này.")
    reason = str(reason or "").strip()[:255] or (
        "Người nhận báo không nhận được" if user.pk == entry.receiver_id else "")
    if not reason:
        raise ValidationError("Ghi lý do bỏ khoản nộp (ví dụ ghi nhầm người nhận).")
    record(Action.DELETE, actor=user, obj=entry, object_type="shifts.CashEntry",
           before={"ca": str(entry.shift), "loai": entry.get_kind_display(), "so_tien": entry.amount,
                   "nguoi_nop": str(entry.actor), "nguoi_nhan": str(entry.receiver), "noi_dung": entry.note},
           reason=reason)
    entry.delete()
    return entry


def approve_refund(order, approver, request_id):
    """Bước 1 khi hủy hóa đơn đã thanh toán được duyệt: ghi khoản hoàn chờ thực hiện (GD-07).

    Chưa có tiền ra, chưa gắn ca. Phương thức hoàn theo phương thức khách đã trả; giữ liên kết
    với thanh toán gốc. Mỗi yêu cầu chỉ sinh tối đa một khoản hoàn.
    """
    payment = order.payment
    if payment is None or order.total == 0:
        return None
    existing = Refund.objects.filter(request_id_ref=request_id).first()
    if existing is not None:
        return existing
    method = Refund.Method.CASH if payment.method == "tien_mat" else Refund.Method.TRANSFER
    refund = Refund.objects.create(store=order.store, payment=payment, order_code=order.code, method=method,
                                   amount=order.total, approved_by=approver, request_id_ref=request_id)
    record(Action.CREATE, actor=approver, obj=refund, object_type="shifts.Refund",
           after={"don": order.code, "phuong_thuc": refund.get_method_display(), "so_tien": refund.amount,
                  "thanh_toan_goc": payment.pk, "trang_thai": refund.get_status_display()})
    return refund


def confirm_refund(user, operation_key, refund_id, note=""):
    """Bước 2: người thu tiền xác nhận đã hoàn cho khách. Tiền ra ghi vào ca đang mở lúc này, đúng một lần."""
    payload = {"refund": int(refund_id), "note": str(note or "")[:255]}

    def action():
        refund = Refund.objects.select_for_update().get(pk=payload["refund"])
        if refund.status == Refund.Status.PAID:
            return {"refund": refund.pk, "shift": refund.shift_id, "applied": False,
                    "message": "Khoản này đã được ghi hoàn trước đó; không ghi thêm."}
        shift = Shift.objects.operating()
        if shift is None:
            raise ValidationError("Không có ca đang mở; mở ca rồi mới ghi đã hoàn tiền.")
        warning = _refund_cash_short(shift, refund)
        refund.status, refund.shift = Refund.Status.PAID, shift
        refund.paid_by, refund.paid_at, refund.paid_note = user, timezone.now(), payload["note"]
        refund.save(update_fields=["status", "shift", "paid_by", "paid_at", "paid_note", "updated_at"])
        record(Action.STATUS_CHANGE, actor=user, obj=refund, object_type="shifts.Refund",
               before={"trang_thai": Refund.Status.APPROVED.label},
               after={"trang_thai": refund.get_status_display(), "ca": str(shift), "so_tien": refund.amount,
                      "phuong_thuc": refund.get_method_display()}, reason=payload["note"])
        return {"refund": refund.pk, "shift": shift.pk, "applied": True, "message": "", "warning": warning}

    return run_once(operation_key, "refund_paid", payload, action, actor=user)


def _refund_cash_short(shift, refund):
    """Hoàn tiền mặt nhiều hơn tiền két theo sổ: vẫn cho ghi (khách cần nhận lại tiền) nhưng báo để kiểm tra két."""
    if refund.method != Refund.Method.CASH:
        return ""
    left = cash_on_hand(shift)
    if refund.amount <= left:
        return ""
    return (f"Két của {shift} theo sổ chỉ còn {numbers.fmt(max(left, 0))} đ, ít hơn khoản hoàn {numbers.fmt(refund.amount)} đ. "
            f"Nếu két thực có đủ tiền thì kiểm tra tiền đầu ca và các khoản chi đã ghi; cuối ca sẽ thấy chênh lệch nếu sổ sai.")


def pending_refunds():
    return Refund.objects.filter(status=Refund.Status.APPROVED).select_related("approved_by", "payment")


def refund_rows(operating=None):
    """Khoản hoàn chờ trả khách cho màn Thu ngân và Ca của tôi: (khoản, khóa thao tác, cảnh báo két thiếu tiền)."""
    import uuid

    return [(r, uuid.uuid4().hex, _refund_cash_short(operating, r) if operating else "") for r in pending_refunds()]


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
    paid = shift.refunds.filter(status=Refund.Status.PAID)
    refunds_cash = paid.filter(method=Refund.Method.CASH).aggregate(s=Sum("amount"))["s"] or 0
    refunds_transfer = paid.filter(method=Refund.Method.TRANSFER).aggregate(s=Sum("amount"))["s"] or 0
    expected_cash = opening + revenue_cash - refunds_cash - expenses - handovers  # BRU-10
    return {"opening": opening, "revenue_cash": revenue_cash, "revenue_transfer": revenue_transfer,
            "refunds_cash": refunds_cash, "refunds_transfer": refunds_transfer, "expenses": expenses,
            "handovers": handovers, "expected_cash": expected_cash,
            "net_transfer": revenue_transfer - refunds_transfer,
            "revenue_total": revenue_cash + revenue_transfer,
            "net_revenue": revenue_cash + revenue_transfer - refunds_cash - refunds_transfer}


def cash_on_hand(shift):
    """Tiền mặt trong két theo sổ; khoản nộp chưa được xác nhận coi như đã ra khỏi két."""
    pending = sum(e.amount for e in shift.cash_entries.filter(kind=CashEntry.Kind.HANDOVER, confirmed_at__isnull=True))
    return figures(shift)["expected_cash"] - pending


def check_cash_on_hand(shift, amount, verb):
    """Không chi hoặc nộp nhiều hơn tiền đang có trong két: thường là gõ thừa số 0."""
    left = cash_on_hand(shift)
    if amount > left:
        tail = ("" if shift.cash_entries.filter(kind=CashEntry.Kind.OPENING).exists()
                else " Ca chưa xác nhận tiền đầu ca; xác nhận trước nếu két có tiền để sẵn.")
        raise ValidationError(f"Két của {shift} theo sổ chỉ còn {numbers.fmt(max(left, 0))} đ, ít hơn khoản {verb} "
                              f"{numbers.fmt(amount)} đ. Kiểm tra lại số tiền đã gõ.{tail}")


# ---------------- Kết ca (FR-08, BRU-06) ----------------

def close_blockers(shift):
    from apps.orders.models import AdjustmentRequest, Order

    blockers = []
    open_orders = Order.objects.filter(shift=shift).exclude(status__in=[Order.Status.PAID, Order.Status.CANCELLED])
    for order in open_orders.select_related("table", "payment"):
        if order.is_prepaid:
            continue  # đơn đã thu trước nhưng chưa giao: báo riêng ở dưới, không gọi là chưa thanh toán
        blockers.append(f"Bàn {order.table.code}: đơn {order.code} chưa thanh toán ({order.get_status_display()}).")
    from apps.orders import prepaid

    blockers += prepaid.close_blockers(shift)
    orphans = (Order.objects.filter(shift__isnull=True, created_at__lt=shift.ends_at)
               .exclude(status__in=[Order.Status.PAID, Order.Status.CANCELLED]).select_related("table"))
    for order in orphans:
        # Đơn gửi lúc chưa có ca: thu tiền thì vào ca này, khách bỏ về thì hủy; không để trôi sang ngày khác.
        blockers.append(f"Bàn {order.table.code}: đơn {order.code} gửi lúc chưa có ca, chưa thanh toán "
                        f"({order.get_status_display()}).")
    pending = AdjustmentRequest.objects.filter(status=AdjustmentRequest.Status.PENDING, order__shift=shift)
    for req in pending:
        blockers.append(f"Yêu cầu \"{req.summary()}\" của đơn {req.order.code} đang chờ duyệt.")
    from apps.orders import backup

    blockers += backup.close_blockers(shift)  # AC-13
    if not shift.cash_entries.filter(kind=CashEntry.Kind.OPENING).exists():
        blockers.append("Chưa xác nhận tiền đầu ca: ghi số tiền nhận bàn giao ở mục Ghi quỹ tiền mặt (két trống thì ghi 0).")
    unconfirmed = shift.cash_entries.filter(kind=CashEntry.Kind.HANDOVER, confirmed_at__isnull=True)
    for e in unconfirmed:
        blockers.append(f"Khoản nộp {numbers.fmt(e.amount, 0)} đ cho {e.receiver} chưa được xác nhận: người nhận cần "
                        f"bấm xác nhận đã nhận tiền; ghi nhầm thì bỏ khoản này ở mục Bút toán của ca.")
    return blockers


@transaction.atomic
def carry_over(user, order_id, to_shift_id, reason):
    """Chuyển đơn chưa thanh toán sang ca kế tiếp kèm lý do (BRU-06)."""
    from apps.orders.models import Order

    if not reason.strip():
        raise ValidationError("Ghi lý do chuyển đơn sang ca sau.")
    order = Order.objects.select_for_update().select_related("shift").get(pk=order_id)
    target = Shift.objects.get(pk=to_shift_id, status=Shift.Status.OPEN)
    if order.shift_id == target.pk:
        raise ValidationError("Chọn ca kế tiếp khác ca hiện tại.")
    # Chỉ chuyển đơn khách chưa trả của một ca chưa kết; đơn đã thu hay đã hủy giữ nguyên ca để số liệu ca cũ không đổi.
    if order.status in (Order.Status.PAID, Order.Status.CANCELLED):
        raise ValidationError(f"Đơn {order.code} đã {order.get_status_display().lower()}; không chuyển sang ca khác.")
    if order.shift_id and order.shift.status != Shift.Status.OPEN:
        raise ValidationError(f"{order.shift} đã kết; không chuyển đơn của ca này.")
    if order.shift_id and target.starts_at <= order.shift.starts_at:
        raise ValidationError("Chỉ chuyển đơn sang ca bắt đầu sau ca hiện tại.")
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
    from apps.accounts.models import User
    from apps.core.push import notify_later

    gaps = shift.discrepancies.current()
    notify_later([u.pk for u in User.objects.filter(is_active=True) if u.is_owner],  # AC-17
                 f"Báo cáo cuối ca {shift}", (f"{gaps.count()} khoản chênh lệch" if gaps.exists() else "Đối soát khớp")
                 + f" · gửi bởi {user}", f"/ca/{shift.pk}/")
    return report


def reconcile(shift, correction=None):
    """So số phải có với số thực tế đang có hiệu lực; lưu mọi chênh lệch khác 0 (FR-12, BRU-10).

    Chạy lại được (sau đính chính báo cáo): khoản không đổi được giữ nguyên kèm giải trình và quyết định;
    khoản thay đổi thì bản cũ hết hiệu lực (giữ lịch sử) và bản mới thay thế, nên mỗi ca và phương thức
    chỉ có một khoản đang tính vào tích lũy và giá trị kiểm soát.
    """
    from apps.control.models import LossEvidence

    actual = shift.report.effective()
    f = figures(shift)
    at = shift.closed_at or shift.ends_at  # ngưỡng của ca là ngưỡng có hiệu lực lúc kết ca
    cash_limit, transfer_limit = params.get("cash_threshold", at=at), params.get("transfer_threshold", at=at)
    rows = [
        (Discrepancy.Method.CASH, f["expected_cash"], actual["counted_cash"], cash_limit),
        (Discrepancy.Method.TRANSFER_IN, f["revenue_transfer"], actual["transfer_received"], transfer_limit),
        (Discrepancy.Method.TRANSFER_REFUND, f["refunds_transfer"], actual["transfer_refunded"], transfer_limit),
    ]
    created = []
    now = timezone.now()
    for method, expected, real, threshold in rows:
        # Với tiền hoàn, chi ra nhiều hơn mức đã duyệt là thiếu tiền: đổi dấu để "âm" luôn nghĩa là thiếu.
        diff = (expected - real) if method == Discrepancy.Method.TRANSFER_REFUND else (real - expected)
        old = Discrepancy.objects.current().filter(shift=shift, method=method).first()
        if old is not None and (old.expected, old.actual, old.difference) == (expected, real, diff):
            continue
        if old is not None:
            if LossEvidence.objects.filter(discrepancy=old).exists():
                raise ValidationError(f"Khoản chênh lệch {old.get_method_display().lower()} của ca đã là bằng chứng "
                                      f"trong vụ việc tổn thất; đính chính vụ việc trước khi đối soát lại.")
            old.superseded_at, old.superseded_by = now, correction
            old.save(update_fields=["superseded_at", "superseded_by", "updated_at"])
            record(Action.STATUS_CHANGE, obj=old, object_type="shifts.Discrepancy", actor_label="hệ thống",
                   before={"chenh_lech": old.difference}, after={"hieu_luc": "Hết hiệu lực do đối soát lại"},
                   reason=correction.reason if correction else "Đối soát lại theo số liệu mới")
        if diff == 0:
            continue
        d = Discrepancy.objects.create(store=shift.store, shift=shift, method=method, expected=expected,
                                       actual=real, difference=diff, manager=_responsible(shift),
                                       over_threshold=abs(diff) > threshold, threshold=threshold)
        record(Action.CREATE, obj=d, object_type="shifts.Discrepancy", actor_label="hệ thống",
               after={"phuong_thuc": d.get_method_display(), "phai_co": expected, "thuc_te": real,
                      "chenh_lech": diff, "nguong": threshold, "vuot_nguong": d.over_threshold,
                      "dinh_chinh": correction.pk if correction else None})
        created.append(d)
    check_accumulated(shift)
    return created


# ---------------- Đính chính báo cáo cuối ca (GD-11) ----------------

def request_correction(user, operation_key, shift_id, counted_cash, transfer_received, transfer_refunded=0, reason=""):
    payload = {"shift": int(shift_id), "cash": str(counted_cash), "in": str(transfer_received),
               "out": str(transfer_refunded or 0), "reason": str(reason or "").strip()}

    def action():
        report = ShiftReport.objects.select_for_update().select_related("shift").get(shift_id=payload["shift"])
        if not payload["reason"]:
            raise ValidationError("Ghi lý do đính chính báo cáo cuối ca.")
        if report.corrections.filter(status=ShiftReportCorrection.Status.PENDING).exists():
            raise ValidationError("Báo cáo này đang có một đề nghị đính chính chờ duyệt.")
        values = (_money(counted_cash, "Tiền mặt đếm"), _money(transfer_received, "Tiền chuyển khoản nhận"),
                  _money(transfer_refunded or 0, "Tiền hoàn chuyển khoản"))
        current = report.effective()
        if values == (current["counted_cash"], current["transfer_received"], current["transfer_refunded"]):
            raise ValidationError("Số liệu đính chính trùng số đang có hiệu lực.")
        c = ShiftReportCorrection.objects.create(
            store=report.store, report=report, counted_cash=values[0], transfer_received=values[1],
            transfer_refunded=values[2], reason=payload["reason"], requested_by=user, operation_key=operation_key)
        record(Action.CREATE, actor=user, obj=c, object_type="shifts.ShiftReportCorrection",
               before={"tien_mat_dem": current["counted_cash"], "ck_nhan": current["transfer_received"],
                       "ck_hoan": current["transfer_refunded"]},
               after={"tien_mat_dem": values[0], "ck_nhan": values[1], "ck_hoan": values[2]}, reason=payload["reason"])
        if user.is_owner:
            # Chủ quán tự đề nghị thì đồng thời là người duyệt (giả định GD-14).
            _approve_correction(c, user, "Chủ quán tự đính chính")
        return {"correction": c.pk}

    return run_once(operation_key, "report_correction", payload, action, actor=user)


def _approve_correction(c, user, note):
    c.status, c.decided_by, c.decided_at, c.decision_note = (ShiftReportCorrection.Status.APPROVED, user,
                                                             timezone.now(), note[:255])
    c.save(update_fields=["status", "decided_by", "decided_at", "decision_note", "updated_at"])
    record(Action.STATUS_CHANGE, actor=user, obj=c, object_type="shifts.ShiftReportCorrection",
           after={"trang_thai": c.get_status_display()}, reason=note)
    reconcile(c.report.shift, correction=c)


@transaction.atomic
def decide_correction(user, correction_id, approve, note=""):
    if not user.is_owner:
        raise ValidationError("Chỉ Chủ quán duyệt đính chính báo cáo cuối ca.")
    c = ShiftReportCorrection.objects.select_for_update().select_related("report__shift").get(pk=correction_id)
    wanted = ShiftReportCorrection.Status.APPROVED if approve else ShiftReportCorrection.Status.REJECTED
    if c.status == wanted:
        return c
    if c.status != ShiftReportCorrection.Status.PENDING:
        raise ValidationError("Đề nghị đính chính này đã được xử lý.")
    if approve:
        _approve_correction(c, user, note)
    else:
        c.status, c.decided_by, c.decided_at, c.decision_note = wanted, user, timezone.now(), note[:255]
        c.save(update_fields=["status", "decided_by", "decided_at", "decision_note", "updated_at"])
        record(Action.STATUS_CHANGE, actor=user, obj=c, object_type="shifts.ShiftReportCorrection",
               after={"trang_thai": c.get_status_display()}, reason=note)
    return c


def explain(user, discrepancy_id, text):
    d = Discrepancy.objects.select_for_update().get(pk=discrepancy_id)
    if d.superseded_at:
        raise ValidationError("Khoản chênh lệch này đã hết hiệu lực sau đối soát lại.")
    if user.pk != d.manager_id and not user.is_owner:
        raise ValidationError("Chỉ người lập báo cáo cuối ca hoặc Chủ quán giải trình khoản chênh lệch này.")
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
    if d.superseded_at:
        raise ValidationError("Khoản chênh lệch này đã hết hiệu lực sau đối soát lại.")
    if d.decision:
        raise ValidationError("Khoản chênh lệch này đã có quyết định.")
    if d.over_threshold and not d.explanation:
        raise ValidationError("Chờ giải trình trước khi quyết định.")
    d.decision = Discrepancy.Decision.ACCEPTED if accept else Discrepancy.Decision.REJECTED
    d.decided_by, d.decided_at = user, timezone.now()
    d.save(update_fields=["decision", "decided_by", "decided_at", "updated_at"])
    record(Action.STATUS_CHANGE, actor=user, obj=d, object_type="shifts.Discrepancy",
           after={"quyet_dinh": d.get_decision_display()})
    check_accumulated(d.shift)
    return d


def _responsible(shift):
    """Người chịu trách nhiệm số tiền của ca: người lập báo cáo cuối ca, nếu chưa có thì người kết ca, cuối cùng là Chủ quán phụ trách."""
    report = getattr(shift, "report", None)
    return (report.submitted_by if report else None) or shift.closed_by or shift.approver


def check_accumulated(shift):
    """Cộng dồn thiếu tiền chưa giải thích theo người phụ trách ca và toàn quán trong tháng (FR-13, BRU-11)."""
    from apps.control.models import ExceptionCase
    from apps.control.services import open_exception

    start = timezone.localtime(shift.starts_at)
    period = f"{start:%Y-%m}"
    month = Discrepancy.objects.current().filter(shift__starts_at__year=start.year, shift__starts_at__month=start.month,
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
                rule=f"Thiếu tiền chưa giải thích tích lũy tháng {start:%m/%Y} vượt "
                     f"{params.get('accumulated_manager_threshold'):,} đ".replace(",", "."),
                amount=total, detail=f"Tích lũy {total:,} đ qua {len(items)} ca.".replace(",", "."))
            exc.shifts.add(*{d.shift for d in items})
            results.append(exc)
    store_total = sum(-d.difference for d in shortages)
    if store_total > params.get("accumulated_store_threshold"):
        exc = open_exception(ExceptionCase.Kind.ACCUMULATED_STORE, period=period, store=shift.store,
                             rule=f"Thiếu tiền chưa giải thích của toàn quán tháng {start:%m/%Y} vượt "
                                  f"{params.get('accumulated_store_threshold'):,} đ".replace(",", "."),
                             amount=store_total, detail=f"Tích lũy {store_total:,} đ.".replace(",", "."))
        exc.shifts.add(*{d.shift for d in shortages})
        results.append(exc)
    return results


def accumulated_report(year, month):
    """Tích lũy thiếu chưa giải thích theo người phụ trách ca, loại ca và tháng (AC-28)."""
    rows = {}
    for d in Discrepancy.objects.current().filter(shift__starts_at__year=year, shift__starts_at__month=month,
                                                  difference__lt=0).select_related("manager", "shift"):
        if not d.is_unexplained_shortage:
            continue
        key = (str(d.manager), d.shift.name)
        rows[key] = rows.get(key, 0) + (-d.difference)
    return [{"manager": k[0], "shift_type": k[1], "total": v} for k, v in sorted(rows.items())]


# ---------------- Tình trạng dữ liệu ca (FR-09, BRU-07) ----------------

def critical_count_status(day, now=None):
    """Nhóm trọng yếu của ngày `day` phải được kiểm kê trước giờ mở cửa ngày hôm sau (BRU-07)."""
    from datetime import datetime, time

    from apps.inventory.models import Ingredient, StockCount

    now = now or timezone.now()
    start = timezone.make_aware(datetime.combine(day, time.min))
    deadline = timezone.make_aware(datetime.combine(day + timedelta(days=1), time(params.get("open_hour", at=start))))
    counted = set(StockCount.objects.filter(created_at__gte=start, created_at__lt=deadline)
                  .exclude(status=StockCount.Status.REJECTED).values_list("ingredient_id", flat=True))
    missing = [i.name for i in Ingredient.objects.filter(is_critical=True, is_active=True).exclude(pk__in=counted)]
    return {"deadline": deadline, "missing": missing, "late": bool(missing) and now > deadline}


def data_status(shift, now=None):
    now = now or timezone.now()
    deadline = shift.ends_at + timedelta(hours=params.get("shift_report_hours", at=shift.ends_at))
    has_report = ShiftReport.objects.filter(shift=shift).exists()
    issues = []
    if shift.status == Shift.Status.OPEN and now > shift.ends_at:
        issues.append("Chưa kết ca")
    if not has_report and now > deadline:
        issues.append("Thiếu báo cáo cuối ca")  # AC-18
    from apps.orders import backup

    if any(backup.unprocessed_numbers(r) for r in shift.backup_ranges.all()):
        issues.append("Còn phiếu dự phòng chưa nhập bù")  # FR-09
    day = timezone.localtime(shift.starts_at).date()
    # So theo ngày giờ Việt Nam: ca 6 giờ sáng là 23 giờ UTC hôm trước, nên không dùng starts_at.date().
    last_of_day = not Shift.objects.filter(starts_at__date=day, starts_at__gt=shift.starts_at).exists()
    count = critical_count_status(day, now) if last_of_day else None
    if count and count["late"]:
        issues.append("Thiếu kiểm kê nhóm trọng yếu: " + ", ".join(count["missing"]))  # BRU-07
    return {"count": count, "shift": shift, "closed": shift.status == Shift.Status.CLOSED, "has_report": has_report,
            "deadline": deadline, "past_deadline": now > deadline, "issues": issues, "overdue": bool(issues)}
