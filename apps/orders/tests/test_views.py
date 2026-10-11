import json
import uuid

from django.test import TestCase
from django.urls import reverse

from apps.orders.models import Order, OrderLine

from .helpers import D, build_menu, cart, levels


class OrderViewTests(TestCase):
    def setUp(self):
        self.d = build_menu()

    def post(self, url, body):
        return self.client.post(url, json.dumps(body), content_type="application/json")

    def test_waiter_submits_and_resend_returns_same_order(self):
        self.client.force_login(self.d["waiter"])
        self.assertEqual(self.client.get(reverse("orders:create")).status_code, 200)
        body = {"operation_key": uuid.uuid4().hex, "order": cart(self.d, quantity=2)}
        first = self.post(reverse("orders:submit"), body).json()
        second = self.post(reverse("orders:submit"), body).json()
        self.assertTrue(first["ok"])
        self.assertTrue(second["repeated"])
        self.assertEqual(first["code"], second["code"])
        self.assertEqual(Order.objects.count(), 1)

    def test_shortage_returns_409_with_details(self):
        self.client.force_login(self.d["waiter"])
        payload = cart(self.d, quantity=40)  # 40 × 30 ml > 1.000 ml sữa
        response = self.post(reverse("orders:submit"), {"operation_key": uuid.uuid4().hex, "order": payload})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["shortages"][0]["ingredient"], "Sữa đặc")
        self.assertEqual(Order.objects.count(), 0)

    def test_barista_completes_and_repeat_click_is_safe(self):
        self.client.force_login(self.d["waiter"])
        self.post(reverse("orders:submit"), {"operation_key": uuid.uuid4().hex, "order": cart(self.d)})
        line = OrderLine.objects.get()
        self.client.force_login(self.d["barista"])
        page = self.client.get(reverse("orders:bar"))
        self.assertContains(page, line.order.code)
        body = {"operation_key": uuid.uuid4().hex, "line": line.pk, "cups": 1, "expected_done": 0}
        for _ in range(3):
            self.assertTrue(self.post(reverse("orders:bar_complete"), body).json()["ok"])
        self.assertEqual(levels(self.d["coffee"]), (D(1980), D(0), D(1980)))
        self.assertNotContains(self.client.get(reverse("orders:bar_queue")), line.order.code)

    def test_permissions_by_role(self):
        self.client.force_login(self.d["barista"])
        self.assertEqual(self.client.get(reverse("orders:create")).status_code, 403)
        response = self.post(reverse("orders:submit"), {"operation_key": uuid.uuid4().hex, "order": cart(self.d)})
        self.assertEqual(response.status_code, 403)
        self.client.force_login(self.d["waiter"])
        self.assertEqual(self.client.get(reverse("orders:bar")).status_code, 403)
        self.assertEqual(self.client.get(reverse("inventory:stock")).status_code, 403)
        self.client.force_login(self.d["barista"])
        self.assertContains(self.client.get(reverse("inventory:stock")), "Có thể dùng")
