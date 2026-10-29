"""Thanh toán theo bàn (FR-04, BRU-04, AC-07 đến AC-10)."""

from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.audit.models import Action
from apps.audit.services import record
from apps.catalog.models import Table
from apps.core import numbers
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
    blockers, exhausted, requests = [], [], []
    for order in orders:
        order.refresh_status()
        req = order.pending_request()
        if req is not None:
            requests.append(req)
            if req.current_level == AdjustmentRequest.Level.EXHAUSTED:
                exhausted.append(req)
            else:
                blockers.append(f"Đơn {order.code} có yêu cầu \"{req.summary()}\" đang chờ duyệt ở cấp "
                                f"{req.get_current_level_display()}.")  # AC-09
        elif order.status != Order.Status.SERVED:
            blockers.append(f"Đơn {order.code} đang ở trạng thái {order.get_status_display()}, chưa phục vụ xong.")
    if exhausted:
        shift = exhausted[0].order.shift or Shift.objects.operating()
        who = (f"Người được ủy quyền thu tiền của ca ({shift.authorizer})"
               if shift is not None and shift.authorizer is not None else "Chủ quán")
        summary = "; ".join(f"đơn {r.order.code}: {r.summary()}" for r in exhausted)
        blockers.append(f"Có yêu cầu điều chỉnh đã quá hạn duyệt ({summary}). {who} thu tiền theo món khách "
                        "thực nhận, hoặc Chủ quán duyệt yêu cầu trước ở mục Duyệt.")
    return {"table": table, "orders": orders, "amount": sum(o.total for o in orders),
            "blockers": blockers, "exhausted": exhausted, "requests": requests}


def tables_with_bills():
    table_ids = (Order.objects.filter(payment__isnull=True)
                 .exclude(status__in=[Order.Status.PAID, Order.Status.CANCELLED]).values("table_id"))
    return [bill(t) for t in Table.objects.filter(pk__in=table_ids).order_by("sort_order", "code")]


def cashier_signature(bills=None):
    """Dấu vết ngắn của những gì màn Thu ngân đang hiện: bàn, số tiền, trạng thái đơn, việc còn chặn, khoản hoàn chờ trả.
    Màn Thu ngân so dấu vết này định kỳ để báo "có thay đổi" thay vì tự tải lại dưới tay thu ngân."""
    import hashlib

    from apps.shifts.services import pending_refunds

    bills = tables_with_bills() if bills is None else bills
    parts = [(b["table"].pk, b["amount"], tuple((o.pk, o.status) for o in b["orders"]), tuple(b["blockers"]))
             for b in bills]
    parts.append(tuple(pending_refunds().values_list("pk", flat=True)))
    from .prepaid import signature_parts

    parts.append(signature_parts())  # đơn thu trước: pha xong thêm ly, khoản thu thêm, hoàn tất
    return hashlib.sha1(repr(parts).encode()).hexdigest()[:16]


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
        # Đơn gửi lúc chưa có ca nào mở thì thuộc ca thu tiền của nó, để báo cáo theo ca khớp với quỹ ca.
        order.shift = order.shift or shift
        order.save(update_fields=["payment", "status", "shift", "updated_at"])
    record(Action.CREATE, actor=user, obj=payment, object_type="orders.Payment",
           after={"ban": table.code, "so_tien": payment.amount, "phuong_thuc": payment.get_method_display(),
                  "loai": payment.get_kind_display(), "don": [o.code for o in orders]})
    return {"payment": payment.pk, "amount": payment.amount, "method": payment.get_method_display(),
            "orders": [o.code for o in orders]}


def pay_table(user, operation_key, table_id, method, transfer_confirmed=False, expected=None):
    """Thu tiền cả bàn. Chỉ khi mọi đơn đã phục vụ và không có yêu cầu chờ duyệt (AC-07, AC-08, AC-09).

    `expected` là số tiền thu ngân đang thấy trên màn: bàn vừa có thêm đơn hay đổi món thì không thu theo số mới
    mà báo để thu ngân xem lại, tránh ghi nhiều hơn số tiền khách thực trả."""
    payload = {"table": int(table_id), "method": method, "confirmed": bool(transfer_confirmed)}
    if expected is not None:
        payload["expected"] = int(expected)

    def action():
        _check_method(method, transfer_confirmed)
        table = Table.objects.get(pk=payload["table"])
        state = bill(table)
        if state["blockers"]:
            raise ValidationError(state["blockers"])
        if expected is not None and state["amount"] != payload["expected"]:
            raise ValidationError(f"Bàn {table.code} vừa thay đổi: cần thu {numbers.fmt(state['amount'], 0)} đ, "
                                  f"không phải {numbers.fmt(payload['expected'], 0)} đ như trên màn lúc trước. "
                                  "Xem lại các đơn của bàn rồi thu.")
        return _record_payment(user, operation_key, table, method, Payment.Kind.NORMAL)

    return run_once(operation_key, "payment", payload, action, actor=user)


def can_pay_received_items(user, req):
    shift = req.order.shift or Shift.objects.operating()
    if user.pk == req.requested_by_id:
        return False
    if shift is not None and shift.authorizer is not None:
        return user.pk == shift.authorizer.pk
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
            raise ValidationError("Bàn này không có yêu cầu quá hạn duyệt.")
        for req in state["exhausted"]:
            if not can_pay_received_items(user, req):
                raise ValidationError("Chỉ người được Chủ quán ủy quyền của ca, không phải người tạo yêu cầu, "
                                      "mới thanh toán theo món thực nhận.")
        for req in state["exhausted"]:
            before, after = adjustments.apply_effects(req, user, delivered=True)
            req.status = AdjustmentRequest.Status.POST_AUDIT
            req.decided_by, req.decided_at = user, timezone.now()
            req.decision_note = "Thanh toán theo món thực nhận khi quá hạn duyệt"
            req.save(update_fields=["status", "decided_by", "decided_at", "decision_note", "updated_at"])
            from apps.control.models import ExceptionCase
            from apps.control.services import open_exception

            open_exception(ExceptionCase.Kind.RECEIVED_ITEMS_PAYMENT, rule="Thanh toán theo món thực nhận",
                           employee=req.requested_by, shift=req.shift, order=req.order, request=req,
                           amount=before["total"] - after["total"], store=req.order.store, one_per_scope=False,
                           detail=f"{req.summary()}. Người xác nhận: {user}. Tiền đơn {numbers.fmt(before['total'], 0)} đ, "
                                  f"thu theo món thực nhận {numbers.fmt(after['total'], 0)} đ.")
        state = bill(table)
        remaining = [b for b in state["blockers"] if "quá hạn duyệt" not in b]
        if remaining:
            raise ValidationError(remaining)
        return _record_payment(user, operation_key, table, method, Payment.Kind.RECEIVED_ITEMS)

    return run_once(operation_key, "payment_received", payload, action, actor=user)
