"""Màn hình kế hoạch mua (mục 9.2): danh sách theo ngày phải đặt, chi tiết, bốn thao tác của Chủ quán."""

import uuid
from datetime import timedelta

from django.urls import reverse
from django.utils import timezone

from apps.core import numbers
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
        # Có đề xuất: biểu đồ so tồn khi không đặt thêm với khi đặt hôm nay đúng số đề xuất.
        self.assertTrue(plan.packs)
        with_order = plan.result["with_order"]
        self.assertEqual(len(with_order), len(plan.result["timeline"]))
        arrival = self.today + timedelta(days=plan.result["exposure"])
        expires = arrival + timedelta(days=self.milk.shelf_life_days - 1)  # lô mới hết hạn cuối ngày này
        for row, level in zip(plan.result["timeline"], with_order):
            gap = level - row["level"]
            if row["date"] < arrival.isoformat():
                self.assertAlmostEqual(gap, 0, delta=0.05)
            elif row["date"] < expires.isoformat():
                self.assertAlmostEqual(gap, float(plan.suggested_quantity), delta=0.05)
        self.assertContains(detail, "Nếu không đặt thêm")
        self.assertContains(detail, "Nếu đặt hôm nay theo đề xuất")
        self.assertContains(page, 'href="#dat-ngay"')
        url = reverse("forecast:plan", args=[self.milk.pk])
        expected = (self.today + timedelta(days=1)).isoformat()
        # Sửa mà không ghi chú: không tạo đơn
        self.client.post(url, {"action": "chap_nhan", "plan": plan.pk, "operation_key": key(),
                               "quantity": str(plan.suggested_quantity + 1000), "expected_date": expected})
        self.assertFalse(PurchaseOrder.objects.exists())
        k = key()
        # Số lượng gõ đúng như ô hiện ("5.900" là năm nghìn chín trăm, không phải 5,9).
        shown = numbers.fmt(plan.suggested_quantity)
        self.assertContains(detail, f'value="{shown}"')
        data = {"action": "chap_nhan", "plan": plan.pk, "operation_key": k, "expected_date": expected,
                "quantity": shown}
        self.client.post(url, data)
        self.client.post(url, data)  # gửi lại
        po = PurchaseOrder.objects.get()
        self.assertEqual((po.status, po.quantity), ("nhap", plan.suggested_quantity))
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

    def test_open_orders_show_even_without_forecast(self):
        """Nguyên liệu chưa đủ dữ liệu dự báo vẫn hiện Đơn đang về để báo nhà cung cấp hoặc hủy."""
        from apps.inventory.models import Ingredient

        ice = Ingredient.objects.create(store=self.d["store"], name="Đá viên", unit="g", pack_size=1000, lead_time_days=1,
                                        main_supplier=self.supplier)
        PurchaseOrder.objects.create(store=self.d["store"], supplier=self.supplier, ingredient=ice, quantity=2000,
                                     expected_date=self.today + timedelta(days=1), created_by=self.owner,
                                     status="nhap", order_by=self.today)
        planning.run_full(at(self.today, 8))
        self.client.login(username=self.owner.username, password=PASSWORD)
        detail = self.client.get(reverse("forecast:plan", args=[ice.pk]))
        self.assertContains(detail, "Chưa đủ dữ liệu")
        self.assertContains(detail, "<h2>Đơn đang về</h2>", html=False)
        self.assertContains(detail, "Đã báo nhà cung cấp")
        self.assertContains(detail, "Hủy đơn")


class ForecastChoiceTests(PlanBase):
    """BRU-21, BRU-37: tự chọn cách dự báo lần đầu khi đủ dữ liệu, sau đó chỉ đổi khi Chủ quán duyệt."""

    def setUp(self):
        super().setUp()
        for j in range(1, 71):
            day = self.today - timedelta(days=j)
            self.sell_day(day, 30 if day.weekday() >= 5 else 20)

    def test_first_choice_is_remembered_and_switch_needs_owner(self):
        from apps.audit.models import AuditLog
        from apps.forecast.models import ForecastChoice, IngredientPlan

        planning.run_full(timezone.now())
        key = planning.series_key(self.milk.pk)
        first = ForecastChoice.objects.get(series_key=key, superseded_at__isnull=True)
        self.assertEqual(first.source, ForecastChoice.Source.AUTO)
        self.assertTrue(ForecastChoice.objects.filter(series_key=planning.TOTAL_KEY).exists())
        plan = IngredientPlan.objects.get(ingredient=self.milk, is_current=True)
        self.assertEqual(plan.forecast["method"], first.method)
        other = "LN" if first.method != "LN" else "WMA"
        proposal = {"method": other, "from": first.method, "gain": 0.12, "h": 2, "weeks": 4, "mae_from": 10.0,
                    "mae_to": 8.8}
        IngredientPlan.objects.filter(pk=plan.pk).update(forecast={**plan.forecast, "proposal": proposal})
        self.client.login(username=self.owner.username, password=PASSWORD)
        page = self.client.get(reverse("forecast:plans"))
        self.assertContains(page, "Có đề xuất phương pháp dự báo cần xem xét")
        self.assertContains(page, "sai số thấp hơn 12%")
        self.assertNotContains(page, other)  # không hiện tên cách tính
        self.client.post(reverse("forecast:plans"), {"action": "giu_cach", "key": key})
        kept = ForecastChoice.objects.get(series_key=key, superseded_at__isnull=True)
        self.assertEqual((kept.source, kept.method, kept.evidence["tu_choi"]),
                         (ForecastChoice.Source.KEPT, first.method, other))
        fc = {"proposal": proposal}
        planning._hold_proposal(fc, kept, self.today, 28)
        self.assertIsNone(fc["proposal"])  # không nhắc lại trong 4 tuần
        ForecastChoice.objects.filter(pk=kept.pk).update(created_at=timezone.now() - timedelta(days=29))
        kept.refresh_from_db()
        fc = {"proposal": proposal}
        planning._hold_proposal(fc, kept, self.today, 28)
        self.assertEqual(fc["proposal"], proposal)
        plan = IngredientPlan.objects.get(ingredient=self.milk, is_current=True)
        IngredientPlan.objects.filter(pk=plan.pk).update(forecast={**plan.forecast, "proposal": proposal})
        self.client.post(reverse("forecast:plans"), {"action": "doi_cach", "key": key})
        now = ForecastChoice.objects.get(series_key=key, superseded_at__isnull=True)
        self.assertEqual((now.source, now.method, now.decided_by), (ForecastChoice.Source.APPROVED, other, self.owner))
        self.assertTrue(AuditLog.objects.filter(object_type="forecast.ForecastChoice").exists())
        self.assertEqual(IngredientPlan.objects.get(ingredient=self.milk, is_current=True).forecast["method"], other)

    def test_accuracy_page_shows_results_only(self):
        planning.run_full(timezone.now())
        self.client.login(username=self.owner.username, password=PASSWORD)
        page = self.client.get(reverse("forecast:accuracy"))
        self.assertContains(page, "Độ chính xác của dự báo")
        self.assertContains(page, self.milk.name)
        self.assertContains(page, "Sai số tổng số ly cả quán")
        for word in ("Holt", "WMA", "TSB", "bình quân"):
            self.assertNotContains(page, word)

    def test_menu_group_season_applies_to_its_share_only(self):
        from apps.catalog.models import MenuGroup
        from apps.forecast.models import SeasonalAdjustment

        future = dict(start=self.today + timedelta(days=5), end=self.today + timedelta(days=20))
        tea = MenuGroup.objects.create(store=self.d["store"], name="Trà")
        SeasonalAdjustment.objects.create(store=self.d["store"], percent=-10, basis="Chung", **future)
        SeasonalAdjustment.objects.create(store=self.d["store"], menu_group=self.d["item"].group, percent=20,
                                          basis="Cà phê đá bán chạy khi nóng", **future)
        SeasonalAdjustment.objects.create(store=self.d["store"], menu_group=tea, percent=50, basis="Trà", **future)
        fc = planning.build_forecasts(timezone.now())[self.milk.pk]
        self.assertEqual(len(fc["seasonal"]), 2)  # nhóm Trà không dùng sữa: bỏ qua
        iso = (self.today + timedelta(days=6)).isoformat()
        # sữa chỉ dùng cho nhóm món có điều chỉnh riêng: nhận +20%, không nhận điều chỉnh chung −10%
        self.assertAlmostEqual(planning.season_factor(fc, iso), 1.2)
