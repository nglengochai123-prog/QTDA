"""Màn hình kế hoạch mua (mục 9.2): danh sách theo ngày phải đặt, chi tiết, bốn thao tác của Chủ quán."""

import uuid
from datetime import timedelta

from django.urls import reverse

from apps.forecast import planning
from apps.inventory.models import PurchaseOrder
from apps.orders.tests.helpers import PASSWORD

from .test_planning import PlanBase, at


def key():
    return uuid.uuid4().hex


class PlanScreenTests(PlanBase):
    def test_list_detail_and_actions(self):
        from apps.accounts.models import Role, User

        planning.run_full(at(self.today, 8))
        cashier = User.objects.create_user("thungan", password=PASSWORD, role=Role.THU_NGAN)
        self.client.login(username=cashier.username, password=PASSWORD)
        self.assertEqual(self.client.get(reverse("forecast:plans")).status_code, 403)
        self.client.login(username=self.owner.username, password=PASSWORD)
        page = self.client.get(reverse("forecast:plans"))
        self.assertContains(page, "Sữa đặc")
        self.assertContains(page, "Đặt ngay")
        detail = self.client.get(reverse("forecast:plan", args=[self.milk.pk]))
        self.assertContains(detail, "Tồn dự kiến 14 ngày tới")
        self.assertContains(detail, "Đặt chậm nhất")
        plan = self.milk.plans.get(is_current=True)
        url = reverse("forecast:plan", args=[self.milk.pk])
        expected = (self.today + timedelta(days=1)).isoformat()
        # Sửa mà không ghi chú: không tạo đơn
        self.client.post(url, {"action": "chap_nhan", "plan": plan.pk, "operation_key": key(),
                               "quantity": str(plan.suggested_quantity + 1000), "expected_date": expected})
        self.assertFalse(PurchaseOrder.objects.exists())
        k = key()
        data = {"action": "chap_nhan", "plan": plan.pk, "operation_key": k, "expected_date": expected,
                "quantity": str(plan.suggested_quantity)}
        self.client.post(url, data)
        self.client.post(url, data)  # gửi lại
        po = PurchaseOrder.objects.get()
        self.assertEqual(po.status, "nhap")
        self.client.post(url, {"action": "da_bao_ncc", "po": po.pk, "expected_date": expected})
        po.refresh_from_db()
        self.assertEqual(po.status, "da_dat")
        r = self.client.post(reverse("forecast:plans"), {"action": "tinh_lai"})
        self.assertEqual(r.status_code, 302)
        self.assertContains(detail, "Tồn trước khi hàng về")
        season = self.client.post(reverse("masterdata:create", args=["dieu-chinh-mua"]), {
            "ingredient": self.milk.pk, "start": self.today.isoformat(),
            "end": (self.today + timedelta(days=30)).isoformat(), "percent": "-15", "basis": "Nghỉ hè",
            "is_active": "on"})
        self.assertEqual(season.status_code, 302)
        from apps.forecast.models import SeasonalAdjustment

        self.assertEqual(SeasonalAdjustment.objects.get().created_by, self.owner)
