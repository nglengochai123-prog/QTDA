"""Một luồng xuyên suốt Phần 1–3, kiểm tra cùng lúc đơn, sổ kho, tiền, báo cáo và nhật ký.

Nhập hàng → tạo đơn → pha một phần → điều chỉnh món → phục vụ → thanh toán → hủy hóa đơn có hoàn tiền
→ kết ca → báo cáo cuối ca và đối soát → giải trình, xác minh chênh lệch → xem báo cáo.
Mỗi bước quan trọng được gửi lại một lần với cùng mã nghiệp vụ để chắc chắn không ghi hai lần.
"""

import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.control import reports
from apps.control import services as control
from apps.control.models import ExceptionCase
from apps.core import integrity
from apps.inventory import operations as ops
from apps.inventory import stock
from apps.inventory.models import Receipt, StockMovement, Supplier, SupplierPayment
from apps.orders import adjustments, payments, services
from apps.orders.models import AdjustmentRequest, Order, Payment, PostPrepCancellation
from apps.orders.tests.helpers import D, cart, levels
from apps.orders.tests.test_adjust_pay import Base, key
from apps.shifts import services as shift_services
from apps.shifts.models import CashEntry, Discrepancy, Refund


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class EndToEndTests(Base):
    def once(self, fn, *args, **kwargs):
        """Gọi một thao tác hai lần với cùng mã nghiệp vụ, như khi mạng mất phản hồi rồi gửi lại."""
        op = key()
        first = fn(*args[:1], op, *args[1:], **kwargs)
        again = fn(*args[:1], op, *args[1:], **kwargs)
        self.assertEqual(first[0], again[0])
        return first[0]

    def test_full_day(self):
        d, owner, barista, waiter = self.d, self.d["owner"], self.d["barista"], self.d["waiter"]
        supplier = Supplier.objects.create(store=d["store"], name="NCC sữa")
        self.once(shift_services.add_cash_entry, self.manager, self.shift.pk, "dau_ca", 500000)

        # 1. Nhập 1.000 ml sữa đặc, 30 đ/ml, trả ngay bằng quỹ ca (có ảnh hóa đơn theo AC-55).
        photo = SimpleUploadedFile("hd.jpg", b"jpeg", content_type="image/jpeg")
        receipt = self.once(ops.create_receipt, barista, supplier.pk,
                            [{"ingredient": d["milk"].pk, "quantity": "1000", "unit_price": 30}], "tra_ngay",
                            invoice_photo=photo, paid_source=SupplierPayment.Source.SHIFT_CASH)
        self.assertEqual(receipt["total"], 30000)
        self.assertEqual(levels(d["milk"]), (D(2000), D(0), D(2000)))

        # 2. Bàn 5 gọi 3 ly cà phê sữa: giữ chỗ 60 g cà phê và 90 ml sữa.
        result = self.once(services.submit_order, waiter, cart(d, quantity=3))
        order_a = Order.objects.get(pk=result["order_id"])
        line = order_a.lines.get()
        self.assertEqual(levels(d["coffee"]), (D(2000), D(60), D(1940)))

        # 3. Quầy pha xong 2 ly: trừ tồn vật lý đúng 2 ly, phần giữ chỗ còn 1 ly.
        self.once(services.complete_line, barista, line.pk, 2, 0)
        self.assertEqual(levels(d["coffee"]), (D(1960), D(20), D(1940)))

        # 4. Khách bỏ 2 ly (1 ly chưa pha, 1 ly đã pha); Quản lý ca duyệt.
        req = self.request(waiter, order_a, "huy_mon", line=line.pk, cups=2)
        self.once(adjustments.decide, self.manager, req.pk, True)
        order_a.refresh_from_db()
        self.assertEqual(order_a.total, 25000)
        self.assertEqual(levels(d["coffee"]), (D(1960), D(0), D(1960)))  # ly chưa pha trả lại, ly đã pha không trừ lại
        self.assertEqual(PostPrepCancellation.objects.get().cups, 1)

        # 5. Phục vụ ly còn lại, 6. thu tiền mặt.
        self.once(services.serve_line, waiter, line.pk)
        self.once(payments.pay_table, self.cashier, order_a.table_id, "tien_mat")

        # 7. Bàn 7 gọi 1 ly, pha, phục vụ, trả chuyển khoản; sau đó hủy hóa đơn, Chủ quán duyệt hoàn tiền.
        payload = cart(d)
        payload["table"] = self.other_table.pk
        result = self.once(services.submit_order, waiter, payload)
        order_b = Order.objects.get(pk=result["order_id"])
        line_b = order_b.lines.get()
        self.once(services.complete_line, barista, line_b.pk, 1, 0)
        self.once(services.serve_line, waiter, line_b.pk)
        self.once(payments.pay_table, self.cashier, self.other_table.pk, "chuyen_khoan", transfer_confirmed=True)
        cancel = self.request(self.cashier, Order.objects.get(pk=order_b.pk), "huy_hoa_don")
        self.once(adjustments.decide, owner, cancel.pk, True)
        adjustments.decide(owner, key(), cancel.pk, True)  # bấm lại bằng mã khác

        # 8. Kết ca, 9. báo cáo cuối ca: thiếu 100.000 đ tiền mặt, chuyển khoản khớp.
        shift_services.close_shift(self.manager, self.shift.pk)
        f = shift_services.figures(self.shift)
        self.assertEqual((f["opening"], f["revenue_cash"], f["expenses"], f["expected_cash"]),
                         (500000, 25000, 30000, 495000))
        self.assertEqual((f["revenue_transfer"], f["refunds_transfer"], f["net_transfer"], f["net_revenue"]),
                         (25000, 25000, 0, 25000))
        report = shift_services.submit_report(self.manager, self.shift.pk, 395000, 25000, 25000)
        self.assertEqual(shift_services.submit_report(self.manager, self.shift.pk, 395000, 25000, 25000), report)
        gap = Discrepancy.objects.get()
        self.assertEqual((gap.method, gap.difference, gap.threshold, gap.over_threshold),
                         ("tien_mat", -100000, 50000, True))

        # 10. Giải trình, Chủ quán không chấp nhận, lập vụ việc và xác minh tổn thất.
        shift_services.explain(self.manager, gap.pk, "Chưa rõ nguyên nhân")
        shift_services.decide(owner, gap.pk, False)
        shift_services.decide(owner, gap.pk, False)  # bấm lại
        now = timezone.localtime()
        self.assertEqual(control.monthly_control(now.year, now.month)["in_process"], 100000)
        case = control.open_case(owner, "Thiếu tiền ca chiều", operation_key=key())
        control.add_evidence(owner, case, discrepancy=gap)
        control.verify(owner, case, 100000)
        control.verify(owner, case, 100000)
        month = control.monthly_control(now.year, now.month)
        self.assertEqual((month["verified"], month["in_process"], month["control_value"]), (100000, 0, 100000))

        # 11. Báo cáo điều chỉnh của ca.
        adj = reports.adjustment_report(self.shift)
        self.assertEqual((adj["total"], len(adj["paid_cancel"]), adj["post_prep_value"]), (2, 1, 25000))

        # ---- Đối chiếu chéo toàn bộ ----
        # Đơn
        order_a.refresh_from_db()
        order_b.refresh_from_db()
        self.assertEqual((order_a.status, order_a.total), (Order.Status.PAID, 25000))
        self.assertEqual(order_b.status, Order.Status.CANCELLED)
        self.assertEqual(Order.objects.count(), 2)
        self.assertEqual(AdjustmentRequest.objects.filter(status="da_duyet").count(), 2)
        # Sổ kho: cà phê 2.000 − 2 ly − 1 ly; sữa 1.000 + 1.000 − 2 ly − 1 ly; không còn giữ chỗ.
        self.assertEqual(levels(d["coffee"]), (D(1940), D(0), D(1940)))
        self.assertEqual(levels(d["milk"]), (D(1910), D(0), D(1910)))
        self.assertEqual(StockMovement.objects.filter(kind=StockMovement.Kind.RECEIPT).count(), 1)
        self.assertEqual(StockMovement.objects.filter(kind=StockMovement.Kind.CONSUME).count(), 4)  # 2 lần pha × 2 nguyên liệu
        self.assertEqual(stock.ledger_problems(), [])
        # Tiền
        self.assertEqual(Receipt.objects.count(), 1)
        self.assertEqual(CashEntry.objects.filter(kind=CashEntry.Kind.EXPENSE).count(), 1)
        self.assertEqual(sorted(Payment.objects.values_list("amount", flat=True)), [25000, 25000])
        self.assertEqual(list(Refund.objects.values_list("method", "amount", "shift")),
                         [("chuyen_khoan", 25000, self.shift.pk)])
        # Ngoại lệ: hủy sau thanh toán (AC-23) được ghi đúng một lần.
        self.assertEqual(ExceptionCase.objects.filter(order=order_b).count(), 1)
        # Nhật ký có đủ các bước.
        types = set(AuditLog.objects.values_list("object_type", flat=True))
        for t in ("inventory.Receipt", "orders.Order", "orders.OrderLine", "orders.AdjustmentRequest",
                  "shifts.Refund", "shifts.Shift", "shifts.ShiftReport", "shifts.Discrepancy", "control.LossCase"):
            self.assertIn(t, types)
        # Kiểm tra toàn vẹn tổng hợp.
        self.assertEqual(integrity.problems(), [])

    def test_integrity_check_reports_tampering(self):
        from apps.inventory.models import IngredientStock

        order, line = self.order()
        self.assertEqual(integrity.problems(), [])
        IngredientStock.objects.filter(ingredient=self.d["coffee"]).update(physical=D(1))
        Order.objects.filter(pk=order.pk).update(total=1)
        found = integrity.problems()
        self.assertTrue(any("Cà phê" in p for p in found))
        self.assertTrue(any(order.code in p for p in found))
