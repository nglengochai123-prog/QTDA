"""Hoàn tiền khi hủy hóa đơn đã thanh toán: đúng phương thức, đúng ca, chỉ trừ một lần khi đối soát."""

from datetime import timedelta

from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.orders import adjustments, payments
from apps.orders.models import Order
from apps.orders.tests.test_adjust_pay import Base, key
from apps.shifts import services as shift_services
from apps.shifts.models import Discrepancy, Refund, Shift


class RefundTests(Base):
    def paid_order(self, method="tien_mat"):
        order, line = self.order()
        self.finish(line)
        payments.pay_table(self.cashier, key(), order.table_id, method, transfer_confirmed=True)
        return Order.objects.get(pk=order.pk)

    def cancel_paid(self, order):
        req = self.request(self.cashier, order, "huy_hoa_don")
        op = key()
        adjustments.decide(self.d["owner"], op, req.pk, True)
        adjustments.decide(self.d["owner"], op, req.pk, True)  # gửi lại cùng mã
        adjustments.decide(self.d["owner"], key(), req.pk, True)  # bấm lại bằng mã khác
        return req

    def test_cash_refund_same_shift_deducted_once(self):
        shift_services.add_cash_entry(self.manager, key(), self.shift.pk, "dau_ca", 500000)
        order = self.paid_order("tien_mat")
        self.cancel_paid(order)
        refund = Refund.objects.get()
        self.assertEqual((refund.method, refund.amount, refund.shift), ("tien_mat", 25000, self.shift))
        f = shift_services.figures(self.shift)
        self.assertEqual((f["revenue_cash"], f["refunds_cash"], f["expected_cash"], f["net_revenue"]),
                         (25000, 25000, 500000, 0))
        shift_services.close_shift(self.manager, self.shift.pk)
        shift_services.submit_report(self.manager, self.shift.pk, 500000, 0)
        self.assertFalse(Discrepancy.objects.exists())

    def test_transfer_refund_matched_against_statement(self):
        shift_services.add_cash_entry(self.manager, key(), self.shift.pk, "dau_ca", 0)
        order = self.paid_order("chuyen_khoan")
        self.cancel_paid(order)
        self.assertEqual(Refund.objects.get().method, "chuyen_khoan")
        shift_services.close_shift(self.manager, self.shift.pk)
        # Sao kê ghi hoàn 50.000 trong khi chỉ duyệt hoàn 25.000: thiếu 25.000 ở mục hoàn chuyển khoản.
        shift_services.submit_report(self.manager, self.shift.pk, 0, 25000, 50000)
        d = Discrepancy.objects.get()
        self.assertEqual((d.method, d.expected, d.actual, d.difference), ("ck_hoan", 25000, 50000, -25000))
        self.assertEqual(shift_services.figures(self.shift)["net_transfer"], 0)

    def test_refund_in_later_shift_leaves_earlier_shift_unchanged(self):
        shift_services.add_cash_entry(self.manager, key(), self.shift.pk, "dau_ca", 0)
        order = self.paid_order("tien_mat")
        shift_services.close_shift(self.manager, self.shift.pk)
        before = shift_services.figures(self.shift)
        now = timezone.now()
        Shift.objects.filter(pk=self.shift.pk).update(ends_at=now - timedelta(minutes=1))
        later = Shift.objects.create(store=self.d["store"], name="Ca tối", starts_at=now - timedelta(minutes=1),
                                     ends_at=now + timedelta(hours=3), approver=self.manager)
        self.cancel_paid(order)
        self.assertEqual(Refund.objects.get().shift, later)
        self.assertEqual(shift_services.figures(Shift.objects.get(pk=self.shift.pk)), before)
        self.assertEqual(shift_services.figures(later)["refunds_cash"], 25000)

    def test_no_open_shift_blocks_refund_approval(self):
        order = self.paid_order("tien_mat")
        req = self.request(self.cashier, order, "huy_hoa_don")
        Shift.objects.update(status=Shift.Status.CLOSED)
        with self.assertRaises(ValidationError):
            adjustments.decide(self.d["owner"], key(), req.pk, True)
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.PAID)
        self.assertFalse(Refund.objects.exists())
