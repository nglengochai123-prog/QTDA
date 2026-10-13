import tempfile
import uuid
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.control.models import ExceptionCase
from apps.orders import payments, services
from apps.orders.models import Order
from apps.orders.tests.helpers import PASSWORD, build_menu, cart
from apps.shifts import services as shift_services
from apps.shifts.models import CashEntry, Discrepancy, Shift


def key():
    return uuid.uuid4().hex


class ShiftBase(TestCase):
    def setUp(self):
        self.d = build_menu()
        self.manager = User.objects.create_user("qlca_a", password=PASSWORD, role=Role.THU_NGAN)
        self.cashier = User.objects.create_user("thungan", password=PASSWORD, role=Role.THU_NGAN)
        now = timezone.now()
        self.shift = Shift.objects.create(store=self.d["store"], name="Ca chiều", starts_at=now - timedelta(hours=2),
                                          ends_at=now + timedelta(hours=2), approver=self.manager)

    def entry(self, kind, amount, **kw):
        return shift_services.add_cash_entry(self.manager, key(), self.shift.pk, kind, amount, **kw)

    def sell(self, method, cups=1):
        result, _ = services.submit_order(self.d["waiter"], key(), cart(self.d, quantity=cups))
        line = Order.objects.get(pk=result["order_id"]).lines.get()
        services.complete_line(self.d["barista"], key(), line.pk, cups, 0)
        services.serve_line(self.d["waiter"], key(), line.pk)
        payments.pay_table(self.cashier, key(), self.d["table"].pk, method, transfer_confirmed=True)


class CashFundTests(ShiftBase):
    def test_entries_and_handover_effective_after_confirmation(self):
        # AC-14
        self.entry("dau_ca", 500000)
        self.entry("chi", 120000, category="sua_chua", note="Thay bóng đèn")
        self.entry("nop", 2000000, receiver_id=self.d["owner"].pk, note="Nộp Chủ quán")
        self.assertEqual(shift_services.figures(self.shift)["handovers"], 0)
        with self.assertRaises(ValidationError):
            shift_services.confirm_handover(self.manager, CashEntry.objects.get(kind="nop").pk)
        shift_services.confirm_handover(self.d["owner"], CashEntry.objects.get(kind="nop").pk)
        f = shift_services.figures(self.shift)
        self.assertEqual((f["opening"], f["expenses"], f["handovers"]), (500000, 120000, 2000000))

    @override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix="lam-test-media-"))
    def test_large_expense_needs_receipt(self):
        # AC-15
        with self.assertRaises(ValidationError):
            self.entry("chi", 600000, category="sua_chua", note="Sửa máy xay")
        photo = SimpleUploadedFile("hoa-don.jpg", b"jpegdata", content_type="image/jpeg")
        self.entry("chi", 600000, category="sua_chua", note="Sửa máy xay", receipt=photo)
        self.assertEqual(CashEntry.objects.filter(kind="chi").count(), 1)

    def test_opening_only_once_and_entry_resend_safe(self):
        op = key()
        shift_services.add_cash_entry(self.manager, op, self.shift.pk, "dau_ca", 500000)
        shift_services.add_cash_entry(self.manager, op, self.shift.pk, "dau_ca", 500000)
        self.assertEqual(CashEntry.objects.count(), 1)
        with self.assertRaises(ValidationError):
            self.entry("dau_ca", 100000)


class CloseAndReconcileTests(ShiftBase):
    def test_close_blocked_then_carry_over(self):
        # AC-16
        self.entry("dau_ca", 500000)
        services.submit_order(self.d["waiter"], key(), cart(self.d))
        with self.assertRaises(ValidationError) as ctx:
            shift_services.close_shift(self.manager, self.shift.pk)
        self.assertIn("Bàn 5", str(ctx.exception))
        next_shift = Shift.objects.create(store=self.d["store"], name="Ca tối", starts_at=self.shift.ends_at,
                                          ends_at=self.shift.ends_at + timedelta(hours=5), approver=self.manager)
        order = Order.objects.get()
        with self.assertRaises(ValidationError):
            shift_services.carry_over(self.manager, order.pk, next_shift.pk, "")
        shift_services.carry_over(self.manager, order.pk, next_shift.pk, "Khách còn ngồi")
        shift_services.close_shift(self.manager, self.shift.pk)
        self.shift.refresh_from_db()
        self.assertEqual(self.shift.status, Shift.Status.CLOSED)

    def test_cash_reconciliation_formula_and_threshold(self):
        # AC-25: 500.000 + 2.500.000 - 120.000 - 2.000.000 = 880.000; đếm 800.000 thiếu 80.000 vượt ngưỡng 50.000.
        self.entry("dau_ca", 500000)
        self.sell("tien_mat", cups=1)  # rồi đặt số tiền thành 2.500.000 cho đúng dữ liệu của AC-25
        Order.objects.filter(pk=Order.objects.get().pk).update(total=2500000)
        from apps.orders.models import Payment
        Payment.objects.update(amount=2500000)
        self.entry("chi", 120000, category="sua_chua", note="Thay bóng đèn")
        entry, _ = self.entry("nop", 2000000, receiver_id=self.d["owner"].pk)
        shift_services.confirm_handover(self.d["owner"], entry["entry"])
        shift_services.close_shift(self.manager, self.shift.pk)
        self.assertEqual(shift_services.figures(self.shift)["expected_cash"], 880000)
        shift_services.submit_report(self.manager, self.shift.pk, 800000, 0)
        d = Discrepancy.objects.get(method="tien_mat")
        self.assertEqual((d.expected, d.actual, d.difference, d.over_threshold), (880000, 800000, -80000, True))
        with self.assertRaises(ValidationError):
            shift_services.decide(self.d["owner"], d.pk, accept=False)  # chưa giải trình
        shift_services.explain(self.manager, d.pk, "Thối nhầm tiền cho khách")
        shift_services.decide(self.d["owner"], d.pk, accept=False)
        d.refresh_from_db()
        self.assertTrue(d.is_unexplained_shortage)

    def test_under_threshold_saved_and_accumulated(self):
        # AC-26, AC-28: 4 ca thiếu 20.000 rồi ca thứ năm thiếu 30.000 -> 110.000 > 100.000.
        shifts = []
        base = self.shift.starts_at
        for i in range(5):
            s = Shift.objects.create(store=self.d["store"], name="Ca chiều", starts_at=base + timedelta(minutes=i),
                                     ends_at=base + timedelta(minutes=i + 1), approver=self.manager)
            shift_services.add_cash_entry(self.manager, key(), s.pk, "dau_ca", 500000)
            shift_services.close_shift(self.manager, s.pk)
            shortage = 30000 if i == 4 else 20000
            shift_services.submit_report(self.manager, s.pk, 500000 - shortage, 0)
            shifts.append(s)
            if i == 0:
                d = Discrepancy.objects.get(shift=s)
                self.assertEqual((d.difference, d.over_threshold), (-20000, False))
                self.assertFalse(ExceptionCase.objects.exists())
        exc = ExceptionCase.objects.get(kind="tich_luy_qlc")
        self.assertEqual((exc.amount, exc.employee, exc.shifts.count()), (110000, self.manager, 5))
        report = shift_services.accumulated_report(base.year, timezone.localtime(base).month)
        self.assertEqual(report[0]["total"], 110000)

    def test_transfer_with_refund(self):
        # AC-27: doanh thu chuyển khoản 1.900.000, hoàn 100.000 đã duyệt; sao kê khớp -> không chênh lệch.
        self.entry("dau_ca", 0)
        from apps.shifts.models import Refund
        from apps.orders.models import Payment
        Payment.objects.create(store=self.d["store"], table=self.d["table"], method="chuyen_khoan", amount=1900000,
                               cashier=self.cashier, shift=self.shift, operation_key=key())
        Refund.objects.create(store=self.d["store"], shift=self.shift, order_code="X", method="chuyen_khoan",
                              amount=100000, approved_by=self.d["owner"], request_id_ref=1, status="da_hoan")
        shift_services.close_shift(self.manager, self.shift.pk)
        shift_services.submit_report(self.manager, self.shift.pk, 0, 1900000, 100000)
        f = shift_services.figures(self.shift)
        self.assertEqual((f["revenue_transfer"], f["refunds_transfer"], f["net_transfer"]), (1900000, 100000, 1800000))
        self.assertFalse(Discrepancy.objects.exists())

    def test_report_deadline_status(self):
        # AC-18
        self.entry("dau_ca", 0)
        shift_services.close_shift(self.manager, self.shift.pk)
        later = self.shift.ends_at + timedelta(hours=2, minutes=1)
        status = shift_services.data_status(self.shift, now=later)
        self.assertIn("Thiếu báo cáo cuối ca", status["issues"])
        self.assertFalse(shift_services.data_status(self.shift, now=self.shift.ends_at)["overdue"])
