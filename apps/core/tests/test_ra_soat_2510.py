"""Rà soát lõi 25/10/2026: các lỗi tìm thấy khi đọc lại luồng bán hàng, ca và kho."""

from datetime import timedelta
from unittest import mock

from django.test import Client
from django.utils import timezone

from apps.orders import adjustments, payments, services
from apps.orders.models import AdjustmentRequest, Order, Payment
from apps.orders.tests.helpers import PASSWORD, D, levels
from apps.orders.tests.test_adjust_pay import Base, key
from apps.shifts import services as shift_services
from apps.shifts.models import Shift


class LateShiftPaymentTests(Base):
    """Khách trả tiền sau giờ kết thúc dự kiến của ca nhưng ca chưa kết: tiền vẫn thuộc quỹ ca đó."""

    def test_payment_after_scheduled_end_goes_to_open_shift(self):
        order, line = self.order()
        self.finish(line)
        later = self.shift.ends_at + timedelta(minutes=10)
        with mock.patch("django.utils.timezone.now", return_value=later):
            payments.pay_table(self.cashier, key(), order.table_id, "tien_mat")
        payment = Payment.objects.get()
        self.assertEqual(payment.shift, self.shift)
        self.assertEqual(shift_services.figures(self.shift)["revenue_cash"], 25000)

    def test_order_after_scheduled_end_attaches_to_open_shift(self):
        later = self.shift.ends_at + timedelta(minutes=10)
        with mock.patch("django.utils.timezone.now", return_value=later):
            order, _ = self.order()
        self.assertEqual(order.shift, self.shift)

    def test_payment_without_any_open_shift_is_refused(self):
        order, line = self.order()
        self.finish(line)
        Shift.objects.filter(pk=self.shift.pk).update(status=Shift.Status.CLOSED)
        from django.core.exceptions import ValidationError

        with self.assertRaises(ValidationError):
            payments.pay_table(self.cashier, key(), order.table_id, "tien_mat")
        self.assertFalse(Payment.objects.exists())


class ApproveWithoutStockTests(Base):
    """Duyệt đổi món khi nguyên liệu món mới không đủ: báo lỗi rõ ràng, không lỗi máy chủ."""

    def test_decide_view_reports_shortage(self):
        order, line = self.order()
        req = self.request(self.d["waiter"], order, "doi_mon", line=line.pk, cups=1,
                           new_line={"item": self.d["item"].pk, "size": self.d["size_m"].pk, "quantity": 40})
        client = Client()
        client.login(username=self.manager.username, password=PASSWORD)
        response = client.post(f"/duyet/{req.pk}/", {"decision": "approve", "operation_key": key()}, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Sữa đặc")
        req.refresh_from_db()
        self.assertEqual(req.status, AdjustmentRequest.Status.PENDING)


class StockGuardTests(Base):
    def test_waste_cannot_exceed_physical_stock(self):
        from django.core.exceptions import ValidationError

        from apps.inventory import operations as ops

        with self.assertRaises(ValidationError):
            ops.record_waste(self.d["barista"], key(), self.d["milk"].pk, "1500", "do_vo")
        self.assertEqual(levels(self.d["milk"])[0], D(1000))

    def test_count_on_negative_book_stock_needs_owner(self):
        from apps.inventory import operations as ops
        from apps.inventory import stock
        from apps.inventory.models import StockCount, StockMovement

        stock.move(self.d["milk"].pk, -1100, kind=StockMovement.Kind.WASTE, actor=self.manager,
                   store=self.d["store"], source_type="thu")
        result, _ = ops.submit_count(self.d["barista"], key(), self.d["milk"].pk, "500", "Đếm lại sau khi lệch")
        self.assertTrue(result["pending"])
        self.assertEqual(StockCount.objects.get().status, StockCount.Status.PENDING)


class FormErrorTests(Base):
    """Biểu mẫu gửi thiếu ô chọn hoặc trỏ tới bản ghi không còn: quay lại kèm thông báo, không lỗi máy chủ."""

    def test_missing_ingredient_returns_message(self):
        client = Client()
        client.login(username=self.manager.username, password=PASSWORD)
        response = client.post("/kho/hao-hut/", {"operation_key": key(), "ingredient": "", "quantity": "1"},
                               HTTP_REFERER="http://testserver/kho/hao-hut/")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].endswith("/kho/hao-hut/"))

    def test_stale_object_returns_message(self):
        client = Client()
        client.login(username=self.manager.username, password=PASSWORD)
        response = client.post("/ca/chenh-lech/999999/quyet-dinh/", {"accept": "1"}, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Không tìm thấy dữ liệu")


class LastShiftOfDayTests(Base):
    def test_early_morning_shift_is_not_last_when_evening_shift_exists(self):
        from datetime import datetime, time

        tz = timezone.get_current_timezone()
        day = timezone.localdate() - timedelta(days=3)
        morning = Shift.objects.create(store=self.d["store"], name="Ca sáng",
                                       starts_at=datetime.combine(day, time(6), tz), ends_at=datetime.combine(day, time(12), tz),
                                       approver=self.manager)
        Shift.objects.create(store=self.d["store"], name="Ca tối", starts_at=datetime.combine(day, time(17), tz),
                             ends_at=datetime.combine(day, time(22), tz), approver=self.manager)
        self.assertIsNone(shift_services.data_status(morning)["count"])
