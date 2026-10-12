"""Sổ kho có bộ lọc, phân trang và liên kết từ dòng tiêu hao tới đơn; lọc ngoại lệ, vụ việc có phân trang."""

from django.urls import reverse

from apps.orders.tests.helpers import PASSWORD
from apps.orders.tests.test_adjust_pay import Base


class LedgerTests(Base):
    def test_ledger_filters_and_order_link(self):
        order, line = self.order()
        self.finish(line)
        self.client.login(username=self.d["owner"].username, password=PASSWORD)
        r = self.client.get(reverse("inventory:ledger"), {"nvl": self.d["milk"].pk, "loai": "pha_che"})
        self.assertEqual(r.status_code, 200)
        rows = r.context["rows"]
        self.assertTrue(rows and all(m.kind == "pha_che" and m.ingredient_id == self.d["milk"].pk for m in rows))
        self.assertContains(r, reverse("orders:detail", args=[order.pk]))
        r = self.client.get(reverse("inventory:ledger"), {"tu": "2000-01-01", "den": "2000-01-01"})
        self.assertContains(r, "Không có biến động nào khớp bộ lọc")
        self.client.login(username=self.d["waiter"].username, password=PASSWORD)
        self.assertEqual(self.client.get(reverse("inventory:ledger")).status_code, 403)

    def test_exception_and_case_lists_filter(self):
        self.client.login(username=self.d["owner"].username, password=PASSWORD)
        r = self.client.get(reverse("control:exceptions"), {"trang-thai": "tat-ca", "loai": "khong_co", "ca": self.shift.pk,
                                                            "tu": "bad"})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Đang xem ngoại lệ của")
        r = self.client.get(reverse("control:cases"), {"trang-thai": "dang_mo"})
        self.assertEqual(r.status_code, 200)
