import json
import uuid

from django.core.exceptions import ValidationError
from django.db import transaction
from django.test import TestCase
from django.urls import reverse

from apps.inventory import stock
from apps.orders import services
from apps.orders.models import Order, OrderLine

from .helpers import D, build_menu, cart, levels


def key():
    return uuid.uuid4().hex


class LifecycleTests(TestCase):
    """FR-03, BRU-02: Đã gửi pha chế → Đã pha chế → Đã phục vụ; AC-06, AC-07."""

    def setUp(self):
        self.d = build_menu()
        result, _ = services.submit_order(self.d["waiter"], key(), cart(self.d, quantity=2))
        self.order = Order.objects.get(pk=result["order_id"])
        self.line = self.order.lines.get()

    def test_states_follow_brd_order(self):
        self.assertEqual(self.order.status, Order.Status.SENT)
        with self.assertRaises(ValidationError):
            services.serve_line(self.d["waiter"], key(), self.line.pk)  # chưa pha xong
        services.complete_line(self.d["barista"], key(), self.line.pk, 1, 0)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.SENT)  # còn 1 ly chờ
        services.complete_line(self.d["barista"], key(), self.line.pk, 1, 1)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.PREPARED)
        self.assertIn(self.line, services.ready_lines())
        op = key()
        services.serve_line(self.d["waiter"], op, self.line.pk)
        again, repeated = services.serve_line(self.d["waiter"], op, self.line.pk)
        self.assertTrue(repeated)
        self.order.refresh_from_db()
        self.line.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.SERVED)
        self.assertEqual((self.line.status, self.line.served_by), (OrderLine.Status.SERVED, self.d["waiter"]))
        self.assertNotIn(self.line, services.ready_lines())

    def test_payment_refused_until_served(self):
        # AC-07: thanh toán khi chưa phục vụ bị từ chối, trạng thái giữ nguyên.
        with self.assertRaises(ValidationError):
            services.ensure_can_pay(self.order)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.SENT)
        services.complete_line(self.d["barista"], key(), self.line.pk, 2, 0)
        with self.assertRaises(ValidationError):
            services.ensure_can_pay(self.order)
        services.serve_line(self.d["waiter"], key(), self.line.pk)
        services.ensure_can_pay(self.order)


class ShortageDetailTests(TestCase):
    def test_rejected_order_reports_cups_left_per_line(self):
        # AC-04: đơn bị từ chối được báo còn đáp ứng bao nhiêu ly.
        d = build_menu(coffee_opening=50)  # đủ 2 ly 20 g
        with self.assertRaises(stock.InsufficientStock) as ctx:
            services.submit_order(d["waiter"], key(), cart(d, quantity=3))
        self.assertEqual(ctx.exception.lines, [{"name": "Cà phê sữa M", "quantity": 3, "left": 2}])

    def test_release_returns_available_without_touching_physical(self):
        # AC-49 (phần kho): món chờ pha bị hủy trả lại tồn có thể dùng, tồn vật lý không đổi.
        d = build_menu()
        result, _ = services.submit_order(d["waiter"], key(), cart(d, quantity=3))
        line = OrderLine.objects.get(order_id=result["order_id"])
        services.complete_line(d["barista"], key(), line.pk, 2, 0)
        with transaction.atomic():
            stock.release(line.usage_for(1))
        self.assertEqual(levels(d["coffee"]), (D(1960), D(0), D(1960)))


class FlowViewTests(TestCase):
    def setUp(self):
        self.d = build_menu()
        self.client.force_login(self.d["waiter"])
        body = {"operation_key": key(), "order": cart(self.d, quantity=1, options=[self.d["cream"]], note="ít ngọt")}
        self.code = self.client.post(reverse("orders:submit"), json.dumps(body), content_type="application/json").json()["code"]
        self.line = OrderLine.objects.get()

    def test_print_ticket_has_brd_fields(self):
        # AC-05: mã đơn, tên món, tùy chọn, số lượng, số bàn, ghi chú, thời điểm.
        self.client.force_login(self.d["barista"])
        page = self.client.get(reverse("orders:print_ticket", args=[self.line.order_id])).content.decode()
        for text in (self.code, "Cà phê sữa M", "Kem muối", "Bàn 5", "ít ngọt", "Gửi lúc"):
            self.assertIn(text, page)
        self.client.force_login(self.d["waiter"])
        self.assertEqual(self.client.get(reverse("orders:print_ticket", args=[self.line.order_id])).status_code, 403)

    def test_waiter_sees_ready_with_table_and_serves(self):
        # AC-06: pha xong thì phục vụ thấy món kèm số bàn.
        services.complete_line(self.d["barista"], key(), self.line.pk, 1, 0)
        count = self.client.get(reverse("orders:ready_count")).json()
        self.assertEqual(count, {"count": 1, "tables": ["5"]})
        self.assertContains(self.client.get(reverse("orders:ready")), "Bàn 5")
        body = {"operation_key": key(), "line": self.line.pk}
        for _ in range(2):
            response = self.client.post(reverse("orders:serve"), json.dumps(body), content_type="application/json")
            self.assertTrue(response.json()["ok"])
        self.assertEqual(self.client.get(reverse("orders:ready_count")).json()["count"], 0)

    def test_availability_exposes_ingredient_stock(self):
        data = self.client.get(reverse("orders:availability")).json()
        self.assertEqual(data["available"][str(self.d["milk"].pk)], 955.0)  # 1000 - 30 - 15
        page = self.client.get(reverse("orders:create"))
        self.assertContains(page, 'id="stock-data"')
