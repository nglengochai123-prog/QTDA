"""Kiểm tra toàn vẹn chéo giữa đơn, sổ kho, giao dịch tiền và ca (NFR-04).

Dùng trong kiểm thử xuyên suốt và bằng lệnh `manage.py kiem_tra_toan_ven` trên dữ liệu thật.
Trả về danh sách vấn đề bằng lời; danh sách rỗng nghĩa là các số liệu khớp nhau.
"""

from django.db.models import Sum


def problems():
    from apps.inventory import stock
    from apps.orders.models import AdjustmentRequest, Order, Payment
    from apps.shifts.models import Refund, Shift

    out = list(stock.ledger_problems())

    for order in Order.objects.prefetch_related("lines"):
        expected = sum(line.unit_price * line.billable_quantity for line in order.lines.all())
        if order.status != Order.Status.CANCELLED and order.total != expected:
            out.append(f"Đơn {order.code}: tổng tiền {order.total} khác tổng các dòng {expected}")
        if order.status == Order.Status.PAID and order.payment_id is None:
            out.append(f"Đơn {order.code}: đã thanh toán nhưng không có giao dịch thu")

    for payment in Payment.objects.filter(kind=Payment.Kind.NORMAL).prefetch_related("orders"):
        covered = sum(o.total for o in payment.orders.all())
        if covered != payment.amount:
            out.append(f"Giao dịch thu #{payment.pk}: số tiền {payment.amount} khác tổng các đơn {covered}")

    for req in AdjustmentRequest.objects.filter(kind=AdjustmentRequest.Kind.CANCEL_PAID,
                                               status=AdjustmentRequest.Status.APPROVED).select_related("order"):
        want = 1 if req.order.payment_id and req.order.total else 0
        have = Refund.objects.filter(request_id_ref=req.pk).count()
        if have != want:
            out.append(f"Yêu cầu hủy hóa đơn #{req.pk}: có {have} khoản hoàn, cần {want}")
    approved = set(AdjustmentRequest.objects.filter(status=AdjustmentRequest.Status.APPROVED).values_list("pk", flat=True))
    for refund in Refund.objects.all():
        if refund.request_id_ref not in approved:
            out.append(f"{refund}: không gắn với yêu cầu hủy hóa đơn đã duyệt")
        if refund.status == Refund.Status.PAID and refund.shift_id is None:
            out.append(f"{refund}: đã hoàn nhưng không gắn ca thực hoàn")
        if refund.status == Refund.Status.APPROVED and refund.shift_id is not None:
            out.append(f"{refund}: chưa hoàn nhưng đã gắn ca")
        if refund.payment_id is None:
            out.append(f"{refund}: không gắn thanh toán gốc")

    for shift in Shift.objects.filter(status=Shift.Status.CLOSED):
        for method, snapshot in (("tien_mat", shift.closed_cash_revenue), ("chuyen_khoan", shift.closed_transfer_revenue)):
            live = Payment.objects.filter(shift=shift, method=method).aggregate(s=Sum("amount"))["s"] or 0
            if snapshot is not None and snapshot != live:
                out.append(f"{shift}: doanh thu {method} đã chốt {snapshot} khác giao dịch hiện có {live}")
    return out
