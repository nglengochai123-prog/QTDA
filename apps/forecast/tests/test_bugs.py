"""Bốn lỗi phát hiện khi rà soát (mục 2.4 thiết kế mua nguyên liệu): mỗi lỗi một kiểm thử tái hiện."""

from datetime import timedelta
from unittest import mock

from django.urls import reverse
from django.utils import timezone

from apps.control import alerts
from apps.control.models import Alert
from apps.forecast import services
from apps.forecast.models import IngredientForecast, OrderSuggestion
from apps.inventory.models import Ingredient, PurchaseOrder, RecipeLine, ShortageCase
from apps.orders.tests.helpers import PASSWORD

from .test_forecast import ForecastBase


class ResendConfirmTests(ForecastBase):
    def test_resending_confirm_form_returns_existing_order_without_error(self):
        """Lỗi 1: gửi lại cùng biểu mẫu xác nhận đề xuất từng gây IntegrityError khi lưu đề xuất lần hai."""
        self.release()
        self.client.login(username=self.owner.username, password=PASSWORD)
        sug = services.ordering_status(self.d["milk"])["suggestion"]["quantity"]
        data = {"ingredient": self.d["milk"].pk, "quantity": str(sug), "operation_key": "gui-lai-1", "note": "Theo đề xuất",
                "expected_date": (self.today + timedelta(days=2)).isoformat()}
        self.client.post(reverse("forecast:ordering"), data)
        r = self.client.post(reverse("forecast:ordering"), data)
        self.assertEqual(r.status_code, 302)
        self.assertEqual(PurchaseOrder.objects.count(), 1)
        self.assertEqual(OrderSuggestion.objects.count(), 1)


class LeadDemandWindowTests(ForecastBase):
    def test_q90_uses_same_window_as_mean(self):
        """Lỗi 3: cột 90% của nhu cầu trong thời gian giao từng cộng dư một ngày so với cột kỳ vọng."""
        rel = self.release()
        milk = self.d["milk"]
        fc = IngredientForecast.objects.get(release=rel, ingredient=milk)
        fc.daily = [{"date": (rel.first_day + timedelta(days=k)).isoformat(), "mean": 100.0, "q10": 100.0,
                     "q90": 100.0} for k in range(10)]
        fc.paths_sample = [[100.0 * (k + 1) for k in range(10)] for _ in range(20)]
        fc.save()
        before_open = timezone.make_aware(timezone.datetime.combine(rel.first_day, timezone.datetime.min.time())) \
            + timedelta(hours=1)
        st = services.ordering_status(milk, rel, now=before_open)
        self.assertEqual(st["lead_demand"], 200.0)  # 2 ngày giao × 100
        self.assertEqual(st["lead_demand_q90"], 200.0)


class OptionShortageTests(ForecastBase):
    def test_shortage_of_option_ingredient_flags_the_item_sizes(self):
        """Lỗi 4: cờ ngày thiếu từng chỉ xét nguyên liệu của kích cỡ, bỏ sót nguyên liệu của tùy chọn."""
        cream = Ingredient.objects.create(store=self.d["store"], name="Kem tươi", unit="ml", pack_size=1000,
                                          lead_time_days=1)
        draft = self.d["v1"].copy_as_draft()
        RecipeLine.objects.create(version=draft, option=self.d["cream"], ingredient=cream, quantity=10)
        draft.publish(self.owner)
        day = self.today - timedelta(days=3)
        ShortageCase.objects.create(store=self.d["store"], ingredient=cream, day=day, source="bao_het")
        flags = services.shortage_flags(day, day)
        self.assertIn(day, flags[self.size.pk])


class ClosedAlertEpisodeTests(ForecastBase):
    def test_manually_closed_order_alert_reopens_for_a_new_episode(self):
        """Lỗi 2: cảnh báo Cần đặt hàng đã đóng tay không bao giờ được tạo lại cho nguyên liệu đó."""
        from apps.forecast import planning

        milk = self.d["milk"]
        now = timezone.now()
        with mock.patch.object(planning, "alert_items") as items:
            items.return_value = [{"ingredient": milk, "episode": "20261015-1", "detail": "Đặt ngay",
                                   "order_by": self.today}]
            alerts.sync(now)
            alert = Alert.objects.get(kind=Alert.Kind.ORDER_NEEDED)
            alerts.close(self.owner, alert.pk, "Đã gọi nhà cung cấp")
            alerts.sync(now)  # cùng đợt rủi ro: không mở lại
            self.assertEqual(Alert.objects.filter(kind=Alert.Kind.ORDER_NEEDED).count(), 1)
            items.return_value = []
            alerts.sync(now)  # hàng đã về, hết rủi ro
            items.return_value = [{"ingredient": milk, "episode": "20261020-7", "detail": "Đặt ngay",
                                   "order_by": self.today}]
            alerts.sync(now)  # tồn lại xuống: đợt mới
        self.assertEqual(Alert.objects.filter(kind=Alert.Kind.ORDER_NEEDED).count(), 2)
        self.assertEqual(Alert.objects.filter(kind=Alert.Kind.ORDER_NEEDED, status="moi").count(), 1)
