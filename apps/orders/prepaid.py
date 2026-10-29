"""Thu tiền trước khi pha chế.

Luồng trả sau giữ nguyên: Tạo đơn → Pha chế → Phục vụ → Thanh toán (payments.py).
Luồng thu trước: Tạo đơn kèm thu tiền (cùng một giao dịch) → Pha chế → Xác nhận pha xong → Giao nước và hoàn tất.

Tiền và tiến độ tách riêng: đơn thu trước có `payment` ngay từ lúc tạo nhưng trạng thái vẫn đi theo các dòng
(Đã gửi pha chế, Đã pha chế, Đã phục vụ) cho đến khi thu ngân bấm Giao nước và hoàn tất; lúc đó đơn mới sang
Đã thanh toán (trạng thái đóng chung của cả hai luồng). Tiền vào quỹ ca lúc thu; hoàn tất không ghi tiền,
không trừ kho. Kho đi đúng như đơn trả sau: giữ khi gửi, trừ khi pha xong (services.complete_line).

Điều chỉnh sau khi đã thu trước vẫn qua phê duyệt. Tổng tiền tăng thì sinh khoản thu thêm, giảm thì sinh khoản
hoàn (hai bước như hủy hóa đơn). Thanh toán gốc không bao giờ bị sửa hay xóa.
"""

from datetime import time

from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q, Sum
from django.utils import timezone

from apps.accounts.models import Role
from apps.accounts.permissions import Cap, user_can
from apps.audit.models import Action
from apps.audit.services import record
from apps.core import numbers
from apps.core.idempotency import run_once
from apps.shifts.models import Refund, Shift

from .models import AdjustmentRequest, Order, OrderLine, Payment, PrepaidCharge

MODE_LATER, MODE_NOW = "sau", "truoc"


class PrepayDenied(PermissionDenied):
    """Không được thu tiền trước hoặc xác nhận ở quầy thu ngân lúc này; view ghi nhật ký từ chối (AC-111)."""


# ---------------- Ai được thu trước ----------------

def duty_problem(user, now=None):
    """Chuỗi rỗng nếu `user` được thu tiền trước và xác nhận đơn thu trước lúc này, không thì lý do.

    Cần quyền Thanh toán, có ca đang giữ quỹ và người này đang trong ca với vai trò Thu ngân: đã chấm công vào ca
    Thu ngân, hoặc có lịch phân công Thu ngân đang diễn ra. Chủ quán trực tiếp quản lý ca nên luôn được."""
    from apps.schedule.models import Assignment
    from apps.staff import timekeeping

    now = now or timezone.now()
    if not user_can(user, Cap.PAYMENT):
        return "Bạn không có quyền thu tiền."
    if Shift.objects.operating(now) is None:
        return "Chưa có ca đang mở; Chủ quán khai báo ca rồi mới thu tiền."
    if user.is_owner:
        return ""
    att = timekeeping.open_attendance(user)
    if att is not None and att.role == Role.THU_NGAN and not timekeeping.is_forgotten(att, now):
        return ""
    local = timezone.localtime(now)
    planned = Assignment.objects.filter(
        Q(shift__end__gt=local.time()) | Q(shift__end=time(0)),  # ca kết thúc lúc 0 giờ là hết ngày
        user=user, role=Role.THU_NGAN, removed_at__isnull=True, shift__date=local.date(),
        shift__start__lte=local.time())
    if planned.exists():
        return ""
    return ("Bạn chưa được phân công Thu ngân trong ca này (chưa vào ca với vai trò Thu ngân và không có lịch Thu ngân "
            "lúc này). Vẫn gửi được đơn thanh toán sau.")


def log_denied(request, error):
    """Ghi nhật ký lần bị từ chối (AC-111). View gọi sau khi giao dịch của thao tác đã hủy, nên dòng này còn lại."""
    record(Action.ACCESS_DENIED, request=request, object_type="capability",
           reason=f"{Cap.PAYMENT}: Thu tiền trước, xác nhận đơn thu trước · {error}")


# ---------------- Thu tiền khi tạo đơn ----------------

def clean_spec(raw):
    """Phần thanh toán gửi kèm đơn. None nghĩa là trả sau (mặc định)."""
    if not isinstance(raw, dict) or raw.get("mode") != MODE_NOW:
        return None
    received = raw.get("cash_received")
    if received in (None, ""):
        received = None
    else:
        try:
            received = int(received)
        except (TypeError, ValueError):
            raise ValidationError("Tiền khách đưa không hợp lệ.")
        if received < 0:
            raise ValidationError("Tiền khách đưa không hợp lệ.")
    method = str(raw.get("method") or "")
    return {"mode": MODE_NOW, "method": method, "transfer_confirmed": bool(raw.get("transfer_confirmed")),
            "cash_received": received if method == Payment.Method.CASH else None}


def check_spec(spec):
    """Kiểm tra trước khi giữ kho: phương thức, xác nhận chuyển khoản."""
    from .payments import _check_method

    _check_method(spec["method"], spec["transfer_confirmed"])


def record_prepayment(user, operation_key, order, spec):
    """Ghi tiền thu trước cho đơn vừa tạo, trong cùng giao dịch với việc tạo đơn và giữ kho."""
    shift = Shift.objects.operating()
    if shift is None:
        raise ValidationError("Chưa có ca đang mở; Chủ quán khai báo ca rồi mới thu tiền.")
    if spec["cash_received"] is not None and spec["cash_received"] < order.total:
        raise ValidationError(f"Tiền khách đưa {numbers.fmt(spec['cash_received'], 0)} đ ít hơn số phải thu "
                              f"{numbers.fmt(order.total, 0)} đ.")
    payment = Payment.objects.create(
        store=order.store, table=order.table, method=spec["method"], kind=Payment.Kind.PREPAID, amount=order.total,
        cashier=user, shift=shift, operation_key=f"{operation_key[:50]}-thu-truoc",
        cash_received=spec["cash_received"])
    order.payment = payment
    order.shift = order.shift or shift
    order.save(update_fields=["payment", "shift", "updated_at"])
    after = {"don": order.code, "ban": order.table.code, "so_tien": payment.amount,
             "phuong_thuc": payment.get_method_display(), "loai": payment.get_kind_display(), "ca": str(shift)}
    if payment.cash_received is not None:
        after.update(khach_dua=payment.cash_received, tien_thua=payment.change_due)
    record(Action.CREATE, actor=user, obj=payment, object_type="orders.Payment", after=after,
           reason="Thu tiền trước khi pha chế")
    return {"payment": payment.pk, "amount": payment.amount, "method": payment.get_method_display(),
            "cash_received": payment.cash_received, "change": payment.change_due}


# ---------------- Số dư của đơn thu trước ----------------

def paid_net(order):
    """Tiền khách đã trả hoặc sắp trả cho đơn: thu trước + các khoản thu thêm − các khoản trả lại phần giảm.

    Tính cả khoản đang chờ để mỗi lần điều chỉnh chỉ sinh đúng phần chênh mới."""
    if order.payment_id is None:
        return 0
    extra = order.prepaid_charges.aggregate(s=Sum("amount"))["s"] or 0
    back = (Refund.objects.filter(payment_id=order.payment_id, kind=Refund.Kind.PREPAID_DECREASE)
            .aggregate(s=Sum("amount"))["s"] or 0)
    return order.payment.amount + extra - back


def pending_refunds(order):
    if order.payment_id is None:
        return Refund.objects.none()
    return Refund.objects.filter(payment_id=order.payment_id, kind=Refund.Kind.PREPAID_DECREASE,
                                 status=Refund.Status.APPROVED)


def settle_adjustment(order, req, actor):
    """Sau khi duyệt điều chỉnh một đơn thu trước còn mở: ghi phần chênh giữa tổng mới và tiền đã thu.

    Không đụng thanh toán gốc. Tăng → khoản chờ thu thêm; giảm → khoản hoàn chờ trả khách (shifts.Refund)."""
    due = order.total - paid_net(order)
    if due > 0:
        charge = PrepaidCharge.objects.create(store=order.store, order=order, request=req, amount=due)
        record(Action.CREATE, actor=actor, obj=charge, object_type="orders.PrepaidCharge",
               after={"don": order.code, "so_tien": due, "trang_thai": charge.get_status_display()},
               reason=f"Điều chỉnh đơn thu trước: {req.summary()}")
    elif due < 0:
        payment = order.payment
        method = Refund.Method.CASH if payment.method == Payment.Method.CASH else Refund.Method.TRANSFER
        refund = Refund.objects.create(store=order.store, payment=payment, order_code=order.code, method=method,
                                       amount=-due, approved_by=actor, request_id_ref=req.pk,
                                       kind=Refund.Kind.PREPAID_DECREASE)
        record(Action.CREATE, actor=actor, obj=refund, object_type="shifts.Refund",
               after={"don": order.code, "so_tien": refund.amount, "phuong_thuc": refund.get_method_display(),
                      "loai": refund.get_kind_display(), "thanh_toan_goc": payment.pk,
                      "trang_thai": refund.get_status_display()},
               reason=f"Điều chỉnh đơn thu trước: {req.summary()}")
    return due


def collect_charge(user, operation_key, charge_id, method, transfer_confirmed=False, cash_received=None):
    """Thu khoản thu thêm: một thanh toán mới loại Thu thêm vào ca đang mở lúc thu. Bấm lại không thu hai lần."""
    payload = {"charge": int(charge_id), "method": method, "confirmed": bool(transfer_confirmed),
               "cash_received": cash_received}

    def action():
        from .payments import _check_method

        problem = duty_problem(user)
        if problem:
            raise PrepayDenied(problem)
        charge = PrepaidCharge.objects.select_for_update().select_related("order", "order__table").get(
            pk=payload["charge"])
        if charge.status == PrepaidCharge.Status.COLLECTED:
            return {"charge": charge.pk, "applied": False, "amount": charge.amount,
                    "message": "Khoản này đã được thu trước đó; không thu thêm."}
        _check_method(method, transfer_confirmed)
        shift = Shift.objects.operating()
        if shift is None:
            raise ValidationError("Chưa có ca đang mở; Chủ quán khai báo ca rồi mới thu tiền.")
        received = cash_received if method == Payment.Method.CASH else None
        if received is not None and received < charge.amount:
            raise ValidationError(f"Tiền khách đưa ít hơn khoản thu thêm {numbers.fmt(charge.amount, 0)} đ.")
        order = charge.order
        payment = Payment.objects.create(
            store=order.store, table=order.table, method=method, kind=Payment.Kind.EXTRA, amount=charge.amount,
            cashier=user, shift=shift, operation_key=f"{operation_key[:50]}-thu-them", cash_received=received)
        charge.status, charge.payment = PrepaidCharge.Status.COLLECTED, payment
        charge.collected_by, charge.collected_at = user, timezone.now()
        charge.save(update_fields=["status", "payment", "collected_by", "collected_at", "updated_at"])
        record(Action.STATUS_CHANGE, actor=user, obj=charge, object_type="orders.PrepaidCharge",
               before={"trang_thai": PrepaidCharge.Status.PENDING.label},
               after={"trang_thai": charge.get_status_display(), "so_tien": charge.amount,
                      "phuong_thuc": payment.get_method_display(), "ca": str(shift), "thanh_toan": payment.pk})
        return {"charge": charge.pk, "applied": True, "amount": charge.amount, "order": order.code,
                "method": payment.get_method_display(), "message": ""}

    return run_once(operation_key, "prepaid_extra", payload, action, actor=user)


# ---------------- Quầy thu ngân: pha xong, giao nước và hoàn tất ----------------

def cashier_complete_line(user, operation_key, line_id, cups, expected_done):
    """Thu ngân xác nhận pha xong cho đơn đã thu trước. Dùng đúng services.complete_line nên trừ kho và bỏ giữ
    chỗ một lần, chống bấm trùng và chống hai nơi cùng xác nhận như ở quầy pha chế."""
    from . import services

    problem = duty_problem(user)
    if problem:
        raise PrepayDenied(problem)
    line = OrderLine.objects.select_related("order__payment").filter(pk=int(line_id)).first()
    if line is None or not line.order.is_prepaid:
        raise ValidationError("Ở quầy thu ngân chỉ xác nhận pha xong cho đơn đã thu tiền trước.")
    return services.complete_line(user, operation_key, line_id, cups, expected_done)


def completion_blockers(order):
    blockers = []
    if not order.is_prepaid:
        return ["Đơn này chưa thu tiền trước; thu tiền ở màn Thu ngân khi khách thanh toán."]
    if order.status == Order.Status.CANCELLED:
        return ["Đơn đã hủy."]
    req = order.pending_request()
    if req is not None:
        blockers.append(f"Đơn có yêu cầu \"{req.summary()}\" đang chờ duyệt.")
    waiting = sum(l.pending_quantity for l in order.lines.all() if l.status != OrderLine.Status.CANCELLED)
    if waiting:
        blockers.append(f"Còn {waiting} ly chưa pha xong.")
    for charge in order.prepaid_charges.filter(status=PrepaidCharge.Status.PENDING):
        blockers.append(f"Còn khoản thu thêm {numbers.fmt(charge.amount, 0)} đ chưa thu.")
    for refund in pending_refunds(order):
        blockers.append(f"Còn khoản trả lại {numbers.fmt(refund.amount, 0)} đ chưa hoàn cho khách.")
    due = order.total - paid_net(order)
    if due and not blockers:
        blockers.append(f"Tiền đã thu lệch tổng đơn {numbers.fmt(due, 0)} đ; báo Chủ quán kiểm tra.")
    return blockers


def complete_order(user, operation_key, order_id):
    """Giao nước và hoàn tất đơn thu trước: dòng đã pha chuyển Đã phục vụ, đơn chuyển trạng thái đóng.

    Không đánh dấu pha xong, không thu tiền, không trừ kho. Chỉ cập nhật phần còn lại; bấm lại không đổi gì."""
    payload = {"order": int(order_id)}

    def action():
        problem = duty_problem(user)
        if problem:
            raise PrepayDenied(problem)
        order = Order.objects.select_for_update().select_related("table", "payment").get(pk=payload["order"])
        if order.status == Order.Status.PAID and order.is_prepaid:
            return {"order": order.pk, "code": order.code, "applied": False, "delivered": 0,
                    "message": f"Đơn {order.code} đã hoàn tất trước đó."}
        blockers = completion_blockers(order)
        if blockers:
            raise ValidationError(blockers)
        now = timezone.now()
        delivered = 0
        for line in order.lines.select_for_update().filter(status=OrderLine.Status.DONE):
            line.status, line.served_at, line.served_by = OrderLine.Status.SERVED, now, user
            line._progress_update = True
            line.save(update_fields=["status", "served_at", "served_by", "updated_at"])
            delivered += line.quantity - line.cancelled_quantity - line.voided_done_quantity
        before = order.status
        order.status, order.completed_at, order.completed_by = Order.Status.PAID, now, user
        order.save(update_fields=["status", "completed_at", "completed_by", "updated_at"])
        record(Action.STATUS_CHANGE, actor=user, obj=order, object_type="orders.Order",
               before={"trang_thai": Order.Status(before).label},
               after={"trang_thai": "Đã giao, hoàn tất", "giao_them_ly": delivered, "tong_tien": order.total},
               reason=f"Giao nước và hoàn tất đơn thu trước, bàn {order.table.code}")
        return {"order": order.pk, "code": order.code, "applied": True, "delivered": delivered, "message": ""}

    return run_once(operation_key, "prepaid_complete", payload, action, actor=user)


def open_prepaid_orders():
    """Đơn đã thu trước còn mở (chưa giao và hoàn tất), cũ nhất trước."""
    return (Order.objects.filter(payment__kind=Payment.Kind.PREPAID)
            .exclude(status__in=[Order.Status.PAID, Order.Status.CANCELLED])
            .select_related("table", "payment", "payment__cashier")
            .prefetch_related("lines__options", "prepaid_charges", "adjustment_requests")
            .order_by("created_at"))


def cashier_cards():
    """Dữ liệu màn Thu ngân cho từng đơn thu trước: tiền, tiến độ, việc còn lại và mã thao tác."""
    import uuid

    cards = []
    for order in open_prepaid_orders():
        lines = [l for l in order.lines.all() if l.status != OrderLine.Status.CANCELLED]
        for line in lines:
            line.op_done = uuid.uuid4().hex
        charges = [c for c in order.prepaid_charges.all() if c.status == PrepaidCharge.Status.PENDING]
        for charge in charges:
            charge.op = uuid.uuid4().hex
        cards.append({"order": order, "lines": lines, "progress": order.progress(),
                      "waiting": [l for l in lines if l.pending_quantity > 0],
                      "to_deliver": [l for l in lines if l.status == OrderLine.Status.DONE],
                      "charges": charges, "refunds": list(pending_refunds(order)),
                      "blockers": completion_blockers(order), "op_complete": uuid.uuid4().hex})
    return cards


def signature_parts():
    """Phần đơn thu trước trong dấu vết màn Thu ngân (báo "có thay đổi")."""
    return tuple((o.pk, o.status, o.total, tuple((l.pk, l.done_quantity, l.status) for l in o.lines.all()),
                  tuple((c.pk, c.status) for c in o.prepaid_charges.all()))
                 for o in open_prepaid_orders())


def close_blockers(shift):
    """Đơn thu trước chưa giao của ca chặn kết ca; không tự hoàn tất hộ. Hoàn tất hoặc chuyển sang ca sau kèm lý do."""
    out = []
    for order in open_prepaid_orders().filter(shift=shift):
        out.append(f"Bàn {order.table.code}: đơn {order.code} đã thu trước nhưng chưa giao nước và hoàn tất "
                   f"({order.progress_label().lower()}). Hoàn tất đơn ở màn Thu ngân, hoặc chuyển đơn sang ca sau "
                   "kèm lý do.")
    for charge in (PrepaidCharge.objects.filter(status=PrepaidCharge.Status.PENDING, order__shift=shift)
                   .select_related("order")):
        out.append(f"Đơn {charge.order.code} còn khoản thu thêm {numbers.fmt(charge.amount, 0)} đ chưa thu.")
    return out
