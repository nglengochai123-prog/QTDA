"""Hoàn tiền khi hủy hóa đơn đã thanh toán (GD-07).

Duyệt hoàn và xác nhận đã hoàn là hai bước; tiền ra ghi đúng một lần vào ca thực sự hoàn,
giữ liên kết với thanh toán gốc, và chỉ bị trừ một lần khi đối soát.
"""

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
        return Refund.objects.get(request_id_ref=req.pk)

    def pay_back(self, refund):
        op = key()
        shift_services.confirm_refund(self.cashier, op, refund.pk, "Đã trả khách")
        shift_services.confirm_refund(self.cashier, op, refund.pk, "Đã trả khách")  # gửi lại
        result, _ = shift_services.confirm_refund(self.cashier, key(), refund.pk)  # bấm lại
        self.assertFalse(result["applied"])
        refund.refresh_from_db()
        return refund

    def test_approval_is_not_money_out(self):
        shift_services.add_cash_entry(self.manager, key(), self.shift.pk, "dau_ca", 500000)
        order = self.paid_order("tien_mat")
        refund = self.cancel_paid(order)
        self.assertEqual((refund.status, refund.shift, refund.payment), (Refund.Status.APPROVED, None, order.payment))
        self.assertEqual(shift_services.figures(self.shift)["refunds_cash"], 0)
        self.assertEqual(list(shift_services.pending_refunds()), [refund])

    def test_cash_refund_same_shift_deducted_once(self):
        shift_services.add_cash_entry(self.manager, key(), self.shift.pk, "dau_ca", 500000)
        refund = self.pay_back(self.cancel_paid(self.paid_order("tien_mat")))
        self.assertEqual((refund.status, refund.method, refund.amount, refund.shift, refund.paid_by),
                         ("da_hoan", "tien_mat", 25000, self.shift, self.cashier))
        f = shift_services.figures(self.shift)
        self.assertEqual((f["revenue_cash"], f["refunds_cash"], f["expected_cash"], f["net_revenue"]),
                         (25000, 25000, 500000, 0))
        shift_services.close_shift(self.manager, self.shift.pk)
        shift_services.submit_report(self.manager, self.shift.pk, 500000, 0)
        self.assertFalse(Discrepancy.objects.exists())

    def test_transfer_refund_matched_against_statement(self):
        shift_services.add_cash_entry(self.manager, key(), self.shift.pk, "dau_ca", 0)
        refund = self.pay_back(self.cancel_paid(self.paid_order("chuyen_khoan")))
        self.assertEqual(refund.method, "chuyen_khoan")
        shift_services.close_shift(self.manager, self.shift.pk)
        # Sao kê ghi hoàn 50.000 trong khi chỉ duyệt hoàn 25.000: thiếu 25.000 ở mục hoàn chuyển khoản.
        shift_services.submit_report(self.manager, self.shift.pk, 0, 25000, 50000)
        d = Discrepancy.objects.get()
        self.assertEqual((d.method, d.expected, d.actual, d.difference), ("ck_hoan", 25000, 50000, -25000))
        self.assertEqual(shift_services.figures(self.shift)["net_transfer"], 0)

    def test_approved_in_one_shift_paid_in_next_goes_to_paying_shift(self):
        shift_services.add_cash_entry(self.manager, key(), self.shift.pk, "dau_ca", 0)
        refund = self.cancel_paid(self.paid_order("tien_mat"))  # duyệt trong ca chiều, khách chưa nhận tiền
        shift_services.close_shift(self.manager, self.shift.pk)
        before = shift_services.figures(self.shift)
        now = timezone.now()
        Shift.objects.filter(pk=self.shift.pk).update(ends_at=now - timedelta(minutes=1))
        later = Shift.objects.create(store=self.d["store"], name="Ca tối", starts_at=now - timedelta(minutes=1),
                                     ends_at=now + timedelta(hours=3), approver=self.manager,
                                     backup_approver=self.backup)
        refund = self.pay_back(refund)
        self.assertEqual(refund.shift, later)
        self.assertEqual(shift_services.figures(Shift.objects.get(pk=self.shift.pk)), before)
        self.assertEqual(shift_services.figures(later)["refunds_cash"], 25000)

    def test_approval_without_open_shift_but_payout_needs_one(self):
        order = self.paid_order("tien_mat")
        req = self.request(self.cashier, order, "huy_hoa_don")
        Shift.objects.update(status=Shift.Status.CLOSED)
        adjustments.decide(self.d["owner"], key(), req.pk, True)
        refund = Refund.objects.get()
        with self.assertRaises(ValidationError):
            shift_services.confirm_refund(self.cashier, key(), refund.pk)
        refund.refresh_from_db()
        self.assertEqual((refund.status, refund.shift), (Refund.Status.APPROVED, None))

    def test_cashier_screen_and_home_show_refunds_waiting_for_the_customer(self):
        from django.test import Client

        from apps.orders.tests.helpers import PASSWORD

        self.cancel_paid(self.paid_order("tien_mat"))
        c = Client()
        c.login(username=self.cashier.username, password=PASSWORD)
        page = c.get("/thu-ngan/").content.decode()
        self.assertIn("Hoàn tiền đã duyệt, chờ trả khách", page)
        self.assertNotIn("Chưa có ca đang mở", page)
        self.assertIn("Hoàn tiền chờ trả khách", c.get("/").content.decode())
        Shift.objects.update(status=Shift.Status.CLOSED)
        self.assertIn("Chưa có ca đang mở", c.get("/thu-ngan/").content.decode())
