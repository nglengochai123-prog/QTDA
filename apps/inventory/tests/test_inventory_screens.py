import json
import uuid

from django.urls import reverse

from apps.inventory import operations as ops
from apps.inventory.models import QuickReport, ShortageCase
from apps.orders.tests.test_adjust_pay import Base


class InventoryScreenTests(Base):
    def test_barista_screens_and_owner_only_pages(self):
        self.client.force_login(self.d["barista"])
        for name in ("inventory:stock", "inventory:quick_report", "inventory:count", "inventory:waste", "inventory:receipt"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)
        for name in ("inventory:purchase_orders", "inventory:payables"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 403, name)
        self.client.post(reverse("inventory:quick_report"), {"operation_key": uuid.uuid4().hex,
                                                             "ingredient": self.d["milk"].pk, "level": "sap_het", "left": "200"})
        self.assertEqual(QuickReport.objects.count(), 1)
        self.client.force_login(self.manager)
        self.assertEqual(self.client.get(reverse("inventory:quick_report_count")).json()["count"], 1)
        self.client.force_login(self.d["owner"])
        for name in ("inventory:purchase_orders", "inventory:payables", "inventory:report"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)

    def test_customer_switch_endpoint(self):
        self.client.force_login(self.d["waiter"])
        body = {"operation_key": uuid.uuid4().hex, "ingredients": [self.d["milk"].pk]}
        for _ in range(2):
            r = self.client.post(reverse("orders:customer_switched"), json.dumps(body), content_type="application/json")
            self.assertTrue(r.json()["ok"])
        self.assertEqual(ShortageCase.objects.filter(source="doi_mon").count(), 1)

    def test_monthly_report_groups_by_ingredient(self):
        # Báo cáo tháng gom theo nguyên liệu; mọi lần kiểm kê đều có trong phần chi tiết (trước đây chỉ 50 lần đầu).
        milk = self.d["milk"]
        ops.record_shortage(milk, "doi_mon")
        for _ in range(3):
            ops.submit_count(self.d["owner"], uuid.uuid4().hex, milk.pk, "0", reason="Đổ vỡ")
        self.client.force_login(self.d["owner"])
        page = self.client.get(reverse("inventory:report"))
        self.assertContains(page, "Hao hụt và kiểm kê tháng")
        self.assertEqual(page.context["count_summary"][0]["n"], 3)
        self.assertEqual(len(page.context["counts"]), 3)
        self.assertEqual(page.context["shortage_total"], 1)
        self.assertContains(page, "Xem từng lần (3)")
