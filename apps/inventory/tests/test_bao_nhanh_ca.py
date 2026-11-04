"""Báo nhanh theo ca: ca sau thấy báo thiếu của ca trước, báo lại không tạo bản trùng, nhập hàng thì đóng báo."""
import tempfile
from datetime import timedelta

from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from apps.inventory import operations as ops
from apps.inventory.models import QuickReport, Supplier
from apps.orders.tests.helpers import PASSWORD
from apps.orders.tests.test_prepaid import Base, key
from apps.reports.tests.test_insights import photo
from apps.shifts.models import Shift


@override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix="lam-test-media-"))
class ShiftQuickReportTests(Base):
    def next_shift(self):
        # Ca trước kết thúc, ca sau đang mở.
        now = timezone.now()
        Shift.objects.filter(pk=self.shift.pk).update(starts_at=now - timedelta(hours=6), ends_at=now - timedelta(minutes=5))
        return Shift.objects.create(store=self.d["store"], name="Ca tối", starts_at=now - timedelta(minutes=5),
                                    ends_at=now + timedelta(hours=4), approver=self.owner)

    def test_next_shift_sees_report_and_repeat_is_a_confirmation(self):
        milk = self.d["milk"]
        first, _ = ops.quick_report(self.d["barista"], key(), milk.pk, "sap_het", "200")
        report = QuickReport.objects.get()
        self.assertEqual(report.shift, self.shift)
        later = self.next_shift()
        other = type(self.d["barista"]).objects.create_user("phache2", password=PASSWORD, role=self.d["barista"].role)
        again, _ = ops.quick_report(other, key(), milk.pk, "sap_het", "120")
        self.assertTrue(again["duplicate"])
        self.assertEqual(QuickReport.objects.count(), 1)
        report.refresh_from_db()
        self.assertEqual((report.confirm_count, report.last_confirmed_by, str(report.last_estimated_left)),
                         (1, other, "120.00"))
        board = ops.open_reports_board()
        self.assertTrue(board[0].earlier_shift)
        self.client.force_login(other)
        # Bảng báo thiếu nằm trong phần quầy tự cập nhật mỗi 2 giây, không cần tải lại trang mới thấy báo mới.
        for name in ("orders:bar", "orders:bar_queue"):
            page = self.client.get(reverse(name))
            self.assertContains(page, "Đang báo thiếu")
            self.assertContains(page, "ca trước")
        page = self.client.get(reverse("inventory:quick_report"))
        self.assertContains(page, "Vẫn sắp hết")
        self.assertTrue(later)

    def test_out_after_low_escalates_and_keeps_one_open_report(self):
        milk = self.d["milk"]
        ops.quick_report(self.d["barista"], key(), milk.pk, "sap_het")
        result, _ = ops.quick_report(self.d["barista"], key(), milk.pk, "da_het")
        self.assertFalse(result["duplicate"])
        self.assertEqual(QuickReport.objects.filter(acknowledged_at__isnull=True).get().level, "da_het")
        # Báo Sắp hết sau khi đã báo Đã hết: chỉ là xác nhận, không hạ mức.
        result, _ = ops.quick_report(self.d["barista"], key(), milk.pk, "sap_het")
        self.assertTrue(result["duplicate"])
        self.assertEqual(QuickReport.objects.filter(acknowledged_at__isnull=True).get().level, "da_het")

    def test_receipt_closes_open_reports(self):
        milk = self.d["milk"]
        ops.quick_report(self.d["barista"], key(), milk.pk, "da_het")
        supplier = Supplier.objects.create(store=self.d["store"], name="NCC")
        ops.create_receipt(self.owner, key(), supplier.pk, [{"ingredient": milk.pk, "quantity": "380",
                                                             "unit_price": 60}], "tra_ngay", invoice_photo=photo())
        report = QuickReport.objects.get()
        self.assertIsNotNone(report.acknowledged_at)
        self.assertIn("Đã nhập hàng", report.note)
        self.assertEqual(ops.open_reports_board(), [])
        # Sau khi nhập, báo mới là báo mới thật sự.
        result, _ = ops.quick_report(self.d["barista"], key(), milk.pk, "sap_het")
        self.assertFalse(result["duplicate"])

    def test_out_reports_come_first_on_the_board(self):
        ops.quick_report(self.d["barista"], key(), self.d["milk"].pk, "sap_het")
        ops.quick_report(self.d["barista"], key(), self.d["coffee"].pk, "da_het")
        self.assertEqual([r.ingredient for r in ops.open_reports_board()], [self.d["coffee"], self.d["milk"]])
