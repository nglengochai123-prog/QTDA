"""Truy vết từ số tổng hợp tới giao dịch chi tiết (NFR-19): mỗi dòng báo cáo doanh thu mở đúng các đơn tạo nên nó."""

from django.urls import reverse
from django.utils import timezone

from apps.inventory.models import QuickReport
from apps.orders import payments
from apps.orders.tests.helpers import PASSWORD
from apps.orders.tests.test_adjust_pay import Base, key
from apps.reports import services


class DrillDownTests(Base):
    def setUp(self):
        super().setUp()
        for qty in (1, 2):
            order, line = self.order(quantity=qty)
            self.finish(line)
            payments.pay_table(self.cashier, key(), order.table_id, "tien_mat")
        self.order()  # đơn chưa thu tiền: không thuộc báo cáo doanh thu
        self.client.login(username=self.d["owner"].username, password=PASSWORD)

    def test_each_revenue_row_links_to_matching_orders(self):
        today = timezone.localdate()
        for dim in services.DIMENSIONS:
            data = services.revenue(today, today, dim)
            self.assertTrue(data["rows"], dim)
            for row in data["rows"]:
                self.assertTrue(row["link"], (dim, row["key"]))
                r = self.client.get(reverse("orders:lookup") + "?" + row["link"])
                self.assertEqual(r.context["page"].paginator.count, row["orders"], (dim, row["key"]))
        page = self.client.get(reverse("reports:revenue"), {"tu": today.isoformat(), "den": today.isoformat()})
        self.assertContains(page, reverse("orders:lookup") + "?da_thu=1")

    def test_dashboard_and_reports_link_to_details(self):
        QuickReport.objects.create(store=self.d["store"], ingredient=self.d["milk"], level="sap_het", reporter=self.d["barista"])
        r = self.client.get(reverse("reports:dashboard"))
        self.assertContains(r, "Nguyên liệu báo Sắp hết")
        self.assertContains(r, self.d["milk"].name)
        self.assertContains(r, reverse("orders:lookup") + "?da_thu=1&amp;theo=thanh_toan")
        self.assertContains(r, reverse("control:exceptions") + "?muc=")
        today = timezone.localdate().isoformat()
        r = self.client.get(reverse("reports:materials"), {"tu": today, "den": today})
        self.assertContains(r, reverse("inventory:ledger") + f"?nvl={self.d['milk'].pk}&amp;loai=tieu_hao_va_lam")
        self.assertEqual(self.client.get(reverse("inventory:report"), {"thang": "2026-01"}).status_code, 200)
        self.assertEqual(self.client.get(reverse("reports:revenue_control")).status_code, 200)
