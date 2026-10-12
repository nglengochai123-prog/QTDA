"""Tra cứu đơn có bộ lọc, phân trang và trang chi tiết đơn (truy vết từ báo cáo tới giao dịch, NFR-19)."""

from django.urls import reverse
from django.utils import timezone

from apps.orders import payments

from .helpers import PASSWORD
from .test_adjust_pay import Base, key


class LookupTests(Base):
    def setUp(self):
        super().setUp()
        self.paid, line = self.order()
        self.finish(line)
        payments.pay_table(self.cashier, key(), self.paid.table_id, "tien_mat")
        self.unpaid, _ = self.order(quantity=2)
        self.client.login(username=self.d["owner"].username, password=PASSWORD)

    def codes(self, **params):
        r = self.client.get(reverse("orders:lookup"), params)
        self.assertEqual(r.status_code, 200)
        return [o.code for o in r.context["page"].object_list]

    def test_filters(self):
        self.assertEqual(set(self.codes()), {self.paid.code, self.unpaid.code})
        self.assertEqual(self.codes(da_thu="1"), [self.paid.code])
        self.assertEqual(self.codes(phuong_thuc="tien_mat"), [self.paid.code])
        self.assertEqual(self.codes(q=self.unpaid.code), [self.unpaid.code])
        today = timezone.localdate().isoformat()
        self.assertEqual(self.codes(theo="thanh_toan", tu=today, den=today), [self.paid.code])
        self.assertEqual(self.codes(tu="2000-01-01", den="2000-01-02"), [])
        size = self.unpaid.lines.get().size_id
        self.assertEqual(set(self.codes(ca=str(self.shift.pk), mon=str(size))), {self.paid.code, self.unpaid.code})

    def test_pagination_keeps_filters(self):
        from unittest import mock

        from apps.core.paging import paginate
        self.order()  # 2 đơn chờ pha, 1 đơn mỗi trang
        with mock.patch("apps.orders.views_lookup.paginate", lambda req, qs: paginate(req, qs, per_page=1)):
            r = self.client.get(reverse("orders:lookup"), {"trang_thai": "da_gui"})
        self.assertEqual(r.context["page"].paginator.num_pages, 2)
        self.assertContains(r, "trang_thai=da_gui&amp;trang=2")

    def test_detail_and_permission(self):
        r = self.client.get(reverse("orders:detail", args=[self.paid.pk]))
        self.assertContains(r, self.paid.code)
        self.assertContains(r, "Tiền mặt")
        self.client.login(username=self.d["waiter"].username, password=PASSWORD)
        self.assertEqual(self.client.get(reverse("orders:lookup")).status_code, 403)
        self.assertEqual(self.client.get(reverse("orders:detail", args=[self.paid.pk])).status_code, 403)
