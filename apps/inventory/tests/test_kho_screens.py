"""Các màn Kho sau khi làm lại: Kiểm kê, Đặt hàng, Phải trả, Phiếu nhập, Hao hụt; cách đọc số kiểu Việt Nam."""

import tempfile
import uuid
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.inventory import operations as ops
from apps.inventory.models import Payable, PurchaseOrder, Receipt, StockCount, Supplier
from apps.orders.tests.helpers import build_menu
from apps.shifts.models import CashEntry, Shift


def key():
    return uuid.uuid4().hex


class NumberInputTests(TestCase):
    def test_quantity_reads_dot_groups_as_thousands_and_comma_as_decimal(self):
        # Màn hình hiển thị "1.866 gram"; người dùng gõ lại đúng như vậy thì phải là 1866, không phải 1,866.
        cases = {"1.866": "1866", "12.160": "12160", "1,5": "1.5", "1.5": "1.5", "1.000,5": "1000.5", "270": "270"}
        for raw, expected in cases.items():
            self.assertEqual(str(ops._dec(raw, "Số lượng")), expected, raw)
        for bad in ("1e999", "NaN", "Infinity", "abc", "99999999999"):
            with self.assertRaises(ValidationError, msg=bad):
                ops._dec(bad, "Số lượng")

    def test_money_reads_vietnamese_grouping(self):
        for raw, expected in {"2.982.000": 2982000, "2,982,000": 2982000, "2 982 000 đ": 2982000, "311600": 311600,
                              "1.200": 1200, "31,5": 32}.items():
            self.assertEqual(ops._vnd(raw, "Số tiền"), expected, raw)
        for bad in ("", "-5", "1e5", "abc", "0"):
            with self.assertRaises(ValidationError, msg=bad):
                ops._vnd(bad, "Số tiền")


@override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix="lam-test-media-"))
class KhoScreenTests(TestCase):
    def setUp(self):
        self.d = build_menu(coffee_opening=1000, milk_opening=4000)
        self.supplier = Supplier.objects.create(store=self.d["store"], name="NCC X")
        self.owner = self.d["owner"]

    def photo(self):
        return SimpleUploadedFile("hd.jpg", b"\xff\xd8\xffjpeg", content_type="image/jpeg")

    def payable(self, amount_per_ml=30, qty="1000"):
        lines = [{"ingredient": self.d["milk"].pk, "quantity": qty, "unit_price": amount_per_ml}]
        ops.create_receipt(self.d["barista"], key(), self.supplier.pk, lines, "tra_sau", invoice_photo=self.photo())
        return Payable.objects.latest("id")

    def test_supplier_payment_from_shift_cash_is_an_expense_of_the_open_shift(self):
        payable = self.payable()
        with self.assertRaises(ValidationError):  # chưa có ca đang mở thì không lấy tiền két được
            ops.pay_supplier(self.owner, payable.pk, "10.000", "quy_ca", operation_key=key())
        now = timezone.now()
        shift = Shift.objects.create(store=self.d["store"], name="Ca chiều", starts_at=now - timedelta(hours=1),
                                     ends_at=now + timedelta(hours=3), approver=self.owner)
        with self.assertRaisesMessage(ValidationError, "theo sổ chỉ còn 0 đ"):  # két chưa có tiền
            ops.pay_supplier(self.owner, payable.pk, "10.000", "quy_ca", operation_key=key())
        CashEntry.objects.create(store=shift.store, shift=shift, kind=CashEntry.Kind.OPENING, amount=200000,
                                 actor=self.owner, operation_key=key())
        ops.pay_supplier(self.owner, payable.pk, "10.000", "quy_ca", operation_key=key())
        entry = CashEntry.objects.get(shift=shift, kind=CashEntry.Kind.EXPENSE)
        self.assertEqual((entry.kind, entry.amount), (CashEntry.Kind.EXPENSE, 10000))
        self.assertEqual(payable.remaining(), 20000)
        ops.pay_supplier(self.owner, payable.pk, "20.000", "chuyen_khoan", operation_key=key())
        self.assertEqual(CashEntry.objects.filter(shift=shift, kind=CashEntry.Kind.EXPENSE).count(), 1)  # chuyển khoản không đụng quỹ ca
        self.assertTrue(Payable.objects.get(pk=payable.pk).is_paid)

    def test_payables_page_totals_and_formatted_amount(self):
        payable = self.payable()
        self.client.force_login(self.owner)
        page = self.client.get(reverse("inventory:payables"))
        self.assertContains(page, "30.000 đ")
        self.client.post(reverse("inventory:payables"), {"payable": payable.pk, "amount": "30.000",
                                                         "source": "chuyen_khoan", "operation_key": key()})
        self.assertTrue(Payable.objects.get(pk=payable.pk).is_paid)

    def test_receipt_price_with_thousand_dots_and_incomplete_line(self):
        self.client.force_login(self.owner)
        url = reverse("inventory:receipt")
        base = {"operation_key": key(), "rows": 8, "supplier": self.supplier.pk, "payment_type": "tra_sau",
                "due_days": 7, "invoice_photo": self.photo()}
        self.client.post(url, {**base, "ingredient_0": self.d["milk"].pk, "quantity_0": "1.000", "price_0": "35",
                               "price_1": "20.000"})
        self.assertFalse(Receipt.objects.exists())  # dòng 2 có đơn giá mà thiếu nguyên liệu: không lưu dở
        self.client.post(url, {**base, "operation_key": key(), "invoice_photo": self.photo(),
                               "ingredient_0": self.d["milk"].pk, "quantity_0": "1.000", "price_0": "1.200"})
        receipt = Receipt.objects.get()
        line = receipt.lines.get()
        self.assertEqual((line.quantity, line.unit_price), (1000, 1200))  # 1.000 ml × 1.200 đ, không phải 1 ml × 1 đ

    def test_purchase_orders_split_waiting_and_reschedule_rules(self):
        today = timezone.localdate()
        late = ops.create_purchase_order(self.owner, self.supplier.pk, self.d["milk"].pk, 5000, today,
                                         operation_key=key())
        PurchaseOrder.objects.filter(pk=late.pk).update(expected_date=today - timedelta(days=2))
        done = ops.create_purchase_order(self.owner, self.supplier.pk, self.d["coffee"].pk, 1000, today,
                                         operation_key=key())
        PurchaseOrder.objects.filter(pk=done.pk).update(status=PurchaseOrder.Status.DELIVERED, received_quantity=1000)
        self.client.force_login(self.owner)
        page = self.client.get(reverse("inventory:purchase_orders"))
        self.assertEqual([po.pk for po in page.context["waiting"]], [late.pk])
        self.assertEqual(page.context["late"], 1)
        self.assertContains(page, "Giao chậm")
        with self.assertRaises(ValidationError):
            ops.reschedule(self.owner, done.pk, today + timedelta(days=1))  # đã giao đủ
        with self.assertRaises(ValidationError):
            ops.reschedule(self.owner, late.pk, today - timedelta(days=1))  # ngày đã qua
        ops.reschedule(self.owner, late.pk, today + timedelta(days=1))
        self.assertEqual(PurchaseOrder.objects.get(pk=late.pk).effective_status(), PurchaseOrder.Status.ORDERED)

    def test_count_page_drafts_per_ingredient_and_pending_state(self):
        self.client.force_login(self.d["barista"])
        url = reverse("inventory:count")
        page = self.client.get(url)
        self.assertContains(page, f'data-draft="kiem-ke-{self.d["milk"].pk}"')
        self.assertContains(page, f'data-draft="kiem-ke-{self.d["coffee"].pk}"')
        self.client.post(url, {"operation_key": key(), "ingredient": self.d["milk"].pk, "counted": "3.000",
                               "reason": "Đổ một hộp"})
        count = StockCount.objects.get()
        self.assertEqual(count.counted, 3000)  # "3.000" là ba nghìn ml
        self.assertEqual(count.status, StockCount.Status.PENDING)
        page = self.client.get(url)
        self.assertContains(page, "Chờ xác nhận")
        self.assertEqual(page.context["done"], 1)
