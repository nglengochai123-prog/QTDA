"""Thanh toán theo bàn (FR-04, BRU-04, AC-07 đến AC-10)."""

from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.audit.models import Action
from apps.audit.services import record
from apps.catalog.models import Table
from apps.core.idempotency import run_once
from apps.shifts.models import Shift

from . import adjustments
from .models import AdjustmentRequest, Order, Payment


def open_orders(table):
    return (Order.objects.filter(table=table, payment__isnull=True)
            .exclude(status__in=[Order.Status.PAID, Order.Status.CANCELLED])
            .prefetch_related("lines__options").order_by("created_at"))


def bill(table):
    """Tình trạng thanh toán của một bàn: số tiền, lý do chưa thanh toán được, yêu cầu quá hạn mọi cấp."""
    orders = list(open_orders(table))
    blockers, exhausted = [], []
    for order in orders:
        order.refresh_status()
        req = order.pending_request()
        if req is not None:
            if req.current_level == AdjustmentRequest.Level.EXHAUSTED:
                exhausted.append(req)
            else:
                blockers.append(f"Đơn {order.code} có yêu cầu \"{req.summary()}\" đang chờ duyệt ở cấp "
                                 f"{req.get_current_level_display()}.")  # AC-09
        elif order.status != Order.Status.SERVED:
            blockers.append(f"Đơn {order.code} đang ở trạng thái {order.get_status_display()}, chưa phục vụ xong.")
    if exhausted:
        blockers.append("Có yêu cầu điều chỉnh đã quá hạn mọi cấp: chỉ người được ủy quyền mới thanh toán "
                        "theo món thực nhận.")
    return {"table": table, "orders": orders, "amount": sum(o.total for o in orders),
            "blockers": blockers, "exhausted": exhausted}


def tables_with_bills():
    table_ids = (Order.objects.filter(payment__isnull=True)
                 .exclude(status__in=[Order.Status.PAID, Order.Status.CANCELLED]).values("table_id"))
    return [bill(t) for t in Table.objects.filter(pk__in=table_ids).order_by("sort_order", "code")]


def _check_method(method, transfer_confirmed):
    if method not in Payment.Method.values:
        raise ValidationError("Chọn phương thức thanh toán.")
    if method == Payment.Method.TRANSFER and not transfer_confirmed:
        raise ValidationError("Chỉ xác nhận chuyển khoản khi đã thấy tiền về tài khoản của quán.")


def _record_payment(user, operation_key, table, method, kind):
    orders = list(open_orders(table).select_for_update())
    if not orders:
        raise ValidationError("Bàn này không còn đơn chờ thanh toán.")
    shift = Shift.objects.operating()
    if shift is None:
        # Tiền thu phải vào quỹ một ca để đối soát (BRU-01, BRU-10); không có ca mở thì không ghi được.
        raise ValidationError("Chưa có ca đang mở; Chủ quán khai báo ca rồi mới thu tiền.")
    payment = Payment.objects.create(
        store=table.store, table=table, method=method, kind=kind, amount=sum(o.total for o in orders),
        cashier=user, shift=shift, operation_key=operation_key)
    for order in orders:
        order.payment = payment
        order.status = Order.Status.PAID
        order.save(update_fields=["payment", "status", "updated_at"])
    record(Action.CREATE, actor=user, obj=payment, object_type="orders.Payment",
           after={"ban": table.code, "so_tien": payment.amount, "phuong_thuc": payment.get_method_display(),
                  "loai": payment.get_kind_display(), "don": [o.code for o in orders]})
    return {"payment": payment.pk, "amount": payment.amount, "method": payment.get_method_display(),
            "orders": [o.code for o in orders]}


def pay_table(user, operation_key, table_id, method, transfer_confirmed=False):
    """Thu tiền cả bàn. Chỉ khi mọi đơn đã phục vụ và không có yêu cầu chờ duyệt (AC-07, AC-08, AC-09)."""
    payload = {"table": int(table_id), "method": method, "confirmed": bool(transfer_confirmed)}

    def action():
        _check_method(method, transfer_confirmed)
        table = Table.objects.get(pk=payload["table"])
        state = bill(table)
        if state["blockers"]:
            raise ValidationError(state["blockers"])
        return _record_payment(user, operation_key, table, method, Payment.Kind.NORMAL)

    return run_once(operation_key, "payment", payload, action, actor=user)


def can_pay_received_items(user, req):
    shift = req.order.shift or Shift.objects.operating()
    if user.pk == req.requested_by_id:
        return False
    if shift is not None and shift.payment_authorizer_id:
        return user.pk == shift.payment_authorizer_id
    return user.is_owner


def pay_received_items(user, operation_key, table_id, method, transfer_confirmed=False):
    """AC-10: yêu cầu quá hạn mọi cấp, khách đã nhận món thay thế. Số tiền tính theo giá bán, không nhập tay;
    yêu cầu chuyển sang Chờ hậu kiểm và tạo ngoại lệ cho Chủ quán."""
    payload = {"table": int(table_id), "method": method, "confirmed": bool(transfer_confirmed), "kind": "received"}

    def action():
        _check_method(method, transfer_confirmed)
        table = Table.objects.get(pk=payload["table"])
        state = bill(table)
        if not state["exhausted"]:
            raise ValidationError("Bàn này không có yêu cầu quá hạn mọi cấp.")
        for req in state["exhausted"]:
            if not can_pay_received_items(user, req):
                raise ValidationError("Chỉ người được Chủ quán ủy quyền của ca, không phải người tạo yêu cầu, "
                                      "mới thanh toán theo món thực nhận.")
        for req in state["exhausted"]:
            before, after = adjustments.apply_effects(req, user, delivered=True)
            req.status = AdjustmentRequest.Status.POST_AUDIT
            req.decided_by, req.decided_at = user, timezone.now()
            req.decision_note = "Thanh toán theo món thực nhận khi quá hạn mọi cấp"
            req.save(update_fields=["status", "decided_by", "decided_at", "decision_note", "updated_at"])
            from apps.control.models import ExceptionCase
            from apps.control.services import open_exception

            open_exception(ExceptionCase.Kind.RECEIVED_ITEMS_PAYMENT, rule="Thanh toán theo món thực nhận (BRU-04)",
                           employee=req.requested_by, shift=req.shift, order=req.order, request=req,
                           amount=before["total"] - after["total"], store=req.order.store, one_per_scope=False,
                           detail=f"{req.summary()}. Người xác nhận: {user}. Trước: {before}. Sau: {after}.")
        state = bill(table)
        remaining = [b for b in state["blockers"] if "quá hạn mọi cấp" not in b]
        if remaining:
            raise ValidationError(remaining)
        return _record_payment(user, operation_key, table, method, Payment.Kind.RECEIVED_ITEMS)

    return run_once(operation_key, "payment_received", payload, action, actor=user)
