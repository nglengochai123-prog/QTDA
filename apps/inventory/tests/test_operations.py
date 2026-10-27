import tempfile
import uuid
from datetime import datetime, timedelta
from unittest import mock

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.control.models import ExceptionCase
from apps.inventory import operations as ops
from apps.inventory.models import (Payable, PurchaseOrder, Receipt, ShortageCase, StockCount, StockMovement, Supplier,
                                   SupplierPayment)
from apps.orders import services
from apps.orders.models import OrderLine
from apps.orders.tests.helpers import D, build_menu, cart, levels


def key():
    return uuid.uuid4().hex


def at_hour(hour):
    return timezone.make_aware(datetime.combine(timezone.localdate(), datetime.min.time()).replace(hour=hour))


@override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix="lam-test-media-"))
class OperationTests(TestCase):
    def setUp(self):
        self.d = build_menu(coffee_opening=1000, milk_opening=4000)
        self.supplier = Supplier.objects.create(store=self.d["store"], name="NCC X")

    def photo(self):
        return SimpleUploadedFile("hd.jpg", b"\xff\xd8\xffjpeg", content_type="image/jpeg")

    def test_quick_report_out_records_one_shortage_per_day(self):
        # AC-51, AC-61
        with mock.patch("apps.inventory.operations.timezone.now", return_value=at_hour(18)):
            r1, _ = ops.quick_report(self.d["barista"], key(), self.d["milk"].pk, "da_het")
            r2, _ = ops.quick_report(self.d["waiter"], key(), self.d["milk"].pk, "da_het")
        self.assertTrue(r1["shortage_recorded"])
        self.assertFalse(r2["shortage_recorded"])
        self.assertEqual(ShortageCase.objects.count(), 1)
        self.assertEqual(ops.open_quick_reports().count(), 2)

    def test_out_report_reaches_owner_phone(self):
        with mock.patch("apps.core.push.notify_later") as notify:
            ops.quick_report(self.d["barista"], key(), self.d["milk"].pk, "sap_het")
            self.assertFalse(notify.called)  # sắp hết thì xem ở trang Kho là đủ
            ops.quick_report(self.d["barista"], key(), self.d["milk"].pk, "da_het")
        self.assertEqual(notify.call_args.args[:2], ([self.d["owner"].pk], "Đã hết Sữa đặc"))

    def test_out_after_closing_no_shortage(self):
        # AC-62
        with mock.patch("apps.inventory.operations.timezone.now", return_value=at_hour(22).replace(minute=30)):
            result, _ = ops.quick_report(self.d["barista"], key(), self.d["milk"].pk, "da_het")
        self.assertFalse(result["shortage_recorded"])
        self.assertFalse(ShortageCase.objects.exists())

    def test_receipt_pay_now_linked_to_order_resend_safe(self):
        # AC-52: lần đặt 10 hộp sữa (10.000 ml), giao đủ, đơn giá 32.000 đ/hộp = 32 đ/ml.
        po = ops.create_purchase_order(self.d["owner"], self.supplier.pk, self.d["milk"].pk, 10000,
                                       timezone.localdate() + timedelta(days=1), operation_key=key())
        lines = [{"ingredient": self.d["milk"].pk, "quantity": "10000", "unit_price": 32, "purchase_order": po.pk}]
        op = key()
        first, _ = ops.create_receipt(self.d["barista"], op, self.supplier.pk, lines, "tra_ngay", invoice_photo=self.photo())
        again, repeated = ops.create_receipt(self.d["barista"], op, self.supplier.pk, lines, "tra_ngay",
                                             invoice_photo=self.photo())
        self.assertTrue(repeated)
        self.assertEqual(first, again)
        self.assertEqual(levels(self.d["milk"])[0], D(14000))
        self.assertEqual(first["total"], 320000)
        po.refresh_from_db()
        self.assertEqual(po.status, PurchaseOrder.Status.DELIVERED)
        self.assertEqual(SupplierPayment.objects.get().amount, 320000)
        self.assertEqual(Receipt.objects.count(), 1)

    def test_receipt_pay_later_and_partial_payments(self):
        # AC-53, AC-54
        lines = [{"ingredient": self.d["coffee"].pk, "quantity": "2000", "unit_price": 320}]
        result, _ = ops.create_receipt(self.d["barista"], key(), self.supplier.pk, lines, "tra_sau",
                                       invoice_photo=self.photo(), due_days=7)
        payable = Payable.objects.get()
        self.assertEqual((payable.amount, payable.remaining(), payable.due_date),
                         (640000, 640000, timezone.localdate() + timedelta(days=7)))
        self.assertFalse(SupplierPayment.objects.exists())
        with self.assertRaises(ValidationError):
            ops.pay_supplier(self.d["barista"], payable.pk, 400000, "chuyen_khoan", operation_key=key())
        op = key()
        ops.pay_supplier(self.d["owner"], payable.pk, 400000, "chuyen_khoan", operation_key=op)
        ops.pay_supplier(self.d["owner"], payable.pk, 400000, "chuyen_khoan", operation_key=op)  # gửi lại
        self.assertEqual(payable.remaining(), 240000)
        self.assertEqual(SupplierPayment.objects.count(), 1)
        ops.pay_supplier(self.d["owner"], payable.pk, 240000, "chuyen_khoan", operation_key=key())
        self.assertTrue(payable.is_paid)
        self.assertEqual(Receipt.objects.get().total, 640000)

    def test_receipt_without_photo_rejected(self):
        # AC-55 và FR-24: mọi phiếu nhập phải có ảnh hóa đơn, kể cả phiếu giá trị nhỏ.
        for qty, price in (("2000", 320), ("10", 100)):
            lines = [{"ingredient": self.d["coffee"].pk, "quantity": qty, "unit_price": price}]
            with self.assertRaises(ValidationError):
                ops.create_receipt(self.d["barista"], key(), self.supplier.pk, lines, "tra_sau")
        self.assertEqual(levels(self.d["coffee"])[0], D(1000))
        self.assertFalse(Receipt.objects.exists())

    def test_partial_and_late_delivery(self):
        # AC-69, AC-68
        op = key()
        po = ops.create_purchase_order(self.d["owner"], self.supplier.pk, self.d["milk"].pk, 10000,
                                       timezone.localdate(), operation_key=op)
        again = ops.create_purchase_order(self.d["owner"], self.supplier.pk, self.d["milk"].pk, 10000,
                                          timezone.localdate(), operation_key=op)
        self.assertEqual((again, PurchaseOrder.objects.count()), (po, 1))
        ops.create_receipt(self.d["barista"], key(), self.supplier.pk,
                           [{"ingredient": self.d["milk"].pk, "quantity": "6000", "unit_price": 0, "purchase_order": po.pk}],
                           "tra_ngay", invoice_photo=self.photo())
        po.refresh_from_db()
        self.assertEqual((po.status, po.remaining), (PurchaseOrder.Status.PARTIAL, D(4000)))
        ops.refresh_late(today=timezone.localdate() + timedelta(days=1))
        po.refresh_from_db()
        self.assertEqual(po.status, PurchaseOrder.Status.LATE)
        self.assertFalse(po.counts_as_incoming)
        ops.reschedule(self.d["owner"], po.pk, timezone.localdate() + timedelta(days=3))
        po.refresh_from_db()
        self.assertEqual(po.status, PurchaseOrder.Status.PARTIAL)

    def test_count_over_threshold_needs_reason_and_owner(self):
        # AC-56: 4.000 ml sữa, đếm 3.600 (10%).
        with self.assertRaises(ValidationError):
            ops.submit_count(self.d["barista"], key(), self.d["milk"].pk, 3600)
        result, _ = ops.submit_count(self.d["barista"], key(), self.d["milk"].pk, 3600, reason="Đổ một hộp")
        self.assertTrue(result["pending"])
        self.assertEqual(levels(self.d["milk"])[0], D(4000))
        with self.assertRaises(ValidationError):
            ops.confirm_count(self.d["barista"], result["count"])
        ops.confirm_count(self.d["owner"], result["count"])
        self.assertEqual(levels(self.d["milk"])[0], D(3600))

    def test_older_pending_count_cannot_be_applied_after_recount(self):
        # Đếm 3.600 (chờ xác nhận), đếm lại 3.500 (chờ xác nhận): xác nhận cả hai sẽ trừ 900 thay vì 500.
        first, _ = ops.submit_count(self.d["barista"], key(), self.d["milk"].pk, 3600, reason="Đổ một hộp")
        StockCount.objects.filter(pk=first["count"]).update(created_at=timezone.now() - timedelta(minutes=5))
        second, _ = ops.submit_count(self.d["barista"], key(), self.d["milk"].pk, 3500, reason="Đếm lại")
        self.client.force_login(self.d["owner"])
        page = self.client.get("/kho/kiem-ke/")
        self.assertContains(page, "lần này đã cũ, chọn Không xác nhận")
        self.assertContains(page, 'value="confirm"', count=1)  # chỉ lần đếm mới có nút Xác nhận
        with self.assertRaisesMessage(ValidationError, "lần đếm này đã cũ"):
            ops.confirm_count(self.d["owner"], first["count"])
        ops.confirm_count(self.d["owner"], second["count"])
        self.assertEqual(levels(self.d["milk"])[0], D(3500))
        ops.confirm_count(self.d["owner"], first["count"], approve=False)
        self.assertEqual(StockCount.objects.get(pk=first["count"]).status, StockCount.Status.REJECTED)
        self.assertNotContains(self.client.get("/kho/kiem-ke/"), "đã cũ")

    def test_count_within_threshold_applies_and_keeps_reservations(self):
        # AC-57: chênh 2,5% điều chỉnh ngay; phần đang giữ cho món chờ pha giữ nguyên.
        services.submit_order(self.d["waiter"], key(), cart(self.d, quantity=2))
        result, _ = ops.submit_count(self.d["barista"], key(), self.d["milk"].pk, 3900)
        self.assertFalse(result["pending"])
        self.assertEqual(levels(self.d["milk"]), (D(3900), D(60), D(3840)))
        self.assertEqual(StockMovement.objects.filter(kind="kiem_ke").count(), 1)

    def test_count_accumulated_exception(self):
        # AC-58: ngưỡng tích lũy 300; thiếu 50, 80, 90 rồi 100 -> 320.
        self.d["milk"].count_accumulated_threshold = 300
        self.d["milk"].save()
        physical = D(4000)
        for short in (50, 80, 90, 100):
            physical -= short
            ops.submit_count(self.d["barista"], key(), self.d["milk"].pk, physical)
            if short != 100:
                self.assertFalse(ExceptionCase.objects.filter(kind="kiem_ke_tich_luy").exists())
        exc = ExceptionCase.objects.get(kind="kiem_ke_tich_luy")
        self.assertEqual(exc.ingredient, self.d["milk"])
        self.assertIn("320", exc.detail)
        self.assertEqual(StockCount.objects.count(), 4)

    def test_waste_requires_reason_and_reduces_physical(self):
        # AC-59, AC-60
        with self.assertRaises(ValidationError):
            ops.record_waste(self.d["barista"], key(), self.d["milk"].pk, 500, "")
        ops.record_waste(self.d["barista"], key(), self.d["milk"].pk, 500, "het_han")
        self.assertEqual(levels(self.d["milk"])[0], D(3500))
        result, _ = services.submit_order(self.d["waiter"], key(), cart(self.d))
        ops.record_waste(self.d["barista"], key(), self.d["coffee"].pk, 20, "pha_hong")
        line = OrderLine.objects.get(order_id=result["order_id"])
        services.complete_line(self.d["barista"], key(), line.pk, 1, 0)
        self.assertEqual(levels(self.d["coffee"])[0], D(960))

    def test_customer_switch_records_shortage_once(self):
        # AC-63
        with mock.patch("apps.inventory.operations.timezone.now", return_value=at_hour(15)):
            first = ops.record_shortage(self.d["milk"], ShortageCase.Source.CUSTOMER_SWITCH, "đơn A")
        with mock.patch("apps.inventory.operations.timezone.now", return_value=at_hour(18)):
            ops.quick_report(self.d["barista"], key(), self.d["milk"].pk, "da_het")
        self.assertIsNotNone(first)
        case = ShortageCase.objects.get()
        self.assertEqual(case.source, ShortageCase.Source.CUSTOMER_SWITCH)
