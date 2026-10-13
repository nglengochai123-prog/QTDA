"""Dự báo nhu cầu theo khung lý thuyết, cảnh báo Cần đặt hàng (AC-66, AC-67) và đề xuất số lượng (AC-70, AC-71)."""

import math
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.control import alerts
from apps.control.models import Alert
from apps.forecast import dglm, evaluate, services
from apps.forecast.models import ExpertJudgement, MethodDecision, OrderSuggestion
from apps.inventory.models import PurchaseOrder, Supplier
from apps.orders.tests.helpers import PASSWORD, build_menu
from apps.shifts.models import Shift, ShiftReport


class MathTests(TestCase):
    def test_framework_example_and_special_functions(self):
        # Mục 4.1: Gamma(60, 2) + hai ngày 22, 24 ly → Gamma(106, 4), kỳ vọng 26,5 ly
        a, b = 60 + 22 + 24, 2 + 2
        self.assertEqual((a, b, a / b), (106, 4, 26.5))
        self.assertAlmostEqual(dglm.digamma(1), -0.5772156649, places=8)
        self.assertAlmostEqual(dglm.trigamma(1), math.pi ** 2 / 6, places=8)
        self.assertAlmostEqual(dglm.trigamma(dglm.alpha_from_q(0.02)), 0.02, places=8)

    def test_judgement_to_prior_respects_width_and_cap(self):
        a, b, days, capped = dglm.gamma_from_judgement(30, 20, 40, max_days=7)
        self.assertAlmostEqual(a / b, 30)
        self.assertFalse(capped)
        mean, (q10, _q50, q90) = dglm.nb_summary(a, b)
        self.assertTrue(18 <= q10 <= 22 and 38 <= q90 <= 42)  # khoảng dự báo khớp nhận định
        a, b, days, capped = dglm.gamma_from_judgement(30, 29, 31, max_days=7)
        self.assertTrue(capped)
        self.assertEqual(days, 7)  # khoảng quá hẹp không tạo độ chắc chắn giả

    def test_model_learns_weekday_and_weekend_levels(self):
        # Nhận định lệch (25 và 35) so với dữ liệu (30 và 45): sau 12 tuần mô hình bám sát số bán gần đây.
        rng = dglm.make_rng("hoc")
        m, C = dglm.prior_state((25 * 2, 2), (35 * 2, 2))
        model = dglm.PoissonDGLM(m, C, 0.95, 0.99)
        ys = []
        for t in range(84):
            dow = t % 7
            ys.append((dow, dglm.poisson(45 if dow >= 5 else 30, rng)))
            model.update(ys[-1][1], dow)
        recent = ys[-28:]
        wd = sum(y for d, y in recent if d < 5) / 20
        we = sum(y for d, y in recent if d >= 5) / 8
        ahead = model.ahead(list(range(7)))
        self.assertLess(abs(sum(a / b for a, b in ahead[:5]) / 5 - wd), 3)
        self.assertLess(abs(sum(a / b for a, b in ahead[5:]) / 2 - we), 6)
        self.assertGreater(sum(a / b for a, b in ahead[5:]) / 2, 35)  # đã rời khỏi nhận định cuối tuần 35
        # Tổng 7 ngày từ mô phỏng khớp tổng các kỳ vọng từng ngày (mục 4.2)
        totals = sorted(sum(p) for p in model.simulate(list(range(7)), 600, rng))
        self.assertLess(abs(sum(totals) / 600 - sum(a / b for a, b in ahead)), 0.03 * sum(a / b for a, b in ahead))
        self.assertLess(dglm.quantile(totals, 0.1), dglm.quantile(totals, 0.9))

    def test_crps_is_lower_for_better_forecast(self):
        good = dglm.crps_discrete(dglm.poisson_pmf_list(30, 120), 31)
        bad = dglm.crps_discrete(dglm.poisson_pmf_list(10, 120), 31)
        self.assertLess(good, bad)


def fake_history(size_id, days, today, weekday=20, weekend=30, closed=(), flagged=()):
    rng = dglm.make_rng("lich-su", size_id)
    dates = [today - timedelta(days=days - i) for i in range(days)]
    status = {d: ("dong_cua" if d in closed else "du_dieu_kien") for d in dates}
    cups = {size_id: {d: dglm.poisson(weekend if d.weekday() >= 5 else weekday, rng) for d in dates}}
    return dates, status, cups, {size_id: set(flagged)}


class ForecastBase(TestCase):
    def setUp(self):
        self.d = build_menu(coffee_opening=2000, milk_opening=1000)
        self.owner = self.d["owner"]
        self.size = self.d["size_m"]
        self.today = timezone.localdate()
        self.supplier = Supplier.objects.create(store=self.d["store"], name="NCC sữa")
        milk = self.d["milk"]
        milk.main_supplier, milk.lead_time_days, milk.order_cycle_days = self.supplier, 2, 10
        milk.safety_stock, milk.pack_size, milk.shelf_life_days = Decimal(300), Decimal(380), 7
        milk.save()
        for day_type, typical, low, high in (("ngay_thuong", 20, 12, 28), ("cuoi_tuan", 30, 20, 40)):
            ExpertJudgement.objects.create(store=self.d["store"], size=self.size, day_type=day_type, typical=typical,
                                           low=low, high=high, basis="Nhập sữa 4 tuần gần đây", provided_by=self.owner)

    def release(self, days=28, **kw):
        with mock.patch("apps.forecast.services.history",
                        return_value=fake_history(self.size.pk, days, self.today, **kw)):
            return services.release(user=self.owner)


class ServiceTests(ForecastBase):
    def test_day_status_closed_unfinished_and_eligible(self):
        y = self.today - timedelta(days=1)
        start = timezone.make_aware(timezone.datetime.combine(y, timezone.datetime.min.time())) + timedelta(hours=6)
        shift = Shift.objects.create(store=self.d["store"], name="Ca", starts_at=start, ends_at=start + timedelta(hours=14),
                                     approver=self.owner)
        status = services.day_status(y - timedelta(days=1), y, self.today)
        self.assertEqual(status[y - timedelta(days=1)], "dong_cua")  # không có ca: không coi là bán 0 ly
        self.assertEqual(status[y], "chua_chot")
        Shift.objects.filter(pk=shift.pk).update(status=Shift.Status.CLOSED)
        ShiftReport.objects.create(store=self.d["store"], shift=shift, counted_cash=0, transfer_received=0,
                                   submitted_by=self.owner)
        self.assertEqual(services.day_status(y, y, self.today)[y], "du_dieu_kien")

    def test_release_uses_owner_estimate_until_owner_chooses_model(self):
        rel = self.release(closed={self.today - timedelta(days=3)}, flagged={self.today - timedelta(days=5)})
        s = rel.series.get(size=self.size)
        self.assertEqual(s.method, MethodDecision.Method.OWNER)
        self.assertEqual((s.eligible_days, s.flagged_days), (26, 1))  # ngày đóng cửa và ngày thiếu hàng không học
        self.assertTrue(any("ngày dữ liệu" in x for x in s.limitations))
        self.assertIn("owner", s.daily[0])
        self.assertLessEqual(s.totals["7"]["q10"], s.totals["7"]["mean"])
        milk_fc = rel.ingredients.get(ingredient=self.d["milk"])
        self.assertAlmostEqual(milk_fc.daily[0]["mean"] / 30, s.totals["1"]["mean"], delta=s.totals["1"]["mean"] * 0.2 + 1)
        MethodDecision.objects.create(store=self.d["store"], size=self.size, method="bayes", decided_by=self.owner)
        self.assertEqual(self.release().series.get(size=self.size).method, "bayes")

    def test_ac66_ac67_order_needed_alert_counts_only_timely_lots_and_closes(self):
        """Cảnh báo Cần đặt hàng theo kế hoạch mua: lô về sau cửa sổ không che rủi ro; đặt đủ thì tự đóng."""
        from apps.forecast import planning

        milk = self.d["milk"]
        milk.weekly_low, milk.weekly_typical, milk.weekly_high = 3500, 4200, 5000  # khoảng 600 ml mỗi ngày
        milk.save()
        morning = timezone.make_aware(timezone.datetime.combine(self.today, timezone.datetime.min.time())) + timedelta(hours=8)
        # Lô giao sau 5 ngày nằm ngoài cửa sổ kích hoạt nên không được tính
        PurchaseOrder.objects.create(store=self.d["store"], supplier=self.supplier, ingredient=milk, quantity=5000,
                                     expected_date=self.today + timedelta(days=5), created_by=self.owner)
        planning.run_full(morning)
        plan = milk.plans.get(is_current=True)
        self.assertEqual(plan.result["ip_s"], 1000)
        self.assertEqual(plan.action, "thuc_giao")  # đưa lô 5.000 ml về sớm là hết rủi ro
        self.assertGreater(plan.packs, 0)  # phương án mua bổ sung nếu không giao sớm được
        self.assertTrue(plan.alert_on)
        self.assertLessEqual(plan.order_by, self.today)
        alerts.sync(morning)
        alert = Alert.objects.get(kind="can_dat_hang")
        self.assertEqual((alert.assignee_role, alert.severity), ("chu_quan", "quan_trong"))
        alerts.sync(morning)
        self.assertEqual(Alert.objects.filter(kind="can_dat_hang").count(), 1)  # không trùng
        # Lô về cuối ngày mai không che được thiếu hụt trong ngày mai (giả định giao cuối ngày); lô về hôm nay thì có.
        PurchaseOrder.objects.create(store=self.d["store"], supplier=self.supplier, ingredient=milk, quantity=5000,
                                     expected_date=self.today, created_by=self.owner)
        planning.recompute(milk.pk, morning)
        alerts.sync(morning)
        alert.refresh_from_db()
        self.assertEqual((alert.status, alert.auto_closed), ("da_dong", True))

    def test_ac70_suggestion_limited_by_shelf_life_and_rounded_to_pack(self):
        milk = self.d["milk"]
        daily = [600.0] * 30
        projected = 100.0
        sug = services.suggestion(milk, daily, projected, 300.0, 2)
        comp = sug["components"]
        self.assertEqual(comp["limited_by"], "thời hạn sử dụng")  # chu kỳ 10 ngày > hạn dùng 7 ngày
        self.assertEqual(comp["cycle_demand"], 6000.0)
        self.assertEqual(comp["shelf_demand"], 4200.0)
        self.assertEqual(sug["quantity"] % 380, 0)  # làm tròn lên theo quy cách
        self.assertGreaterEqual(sug["quantity"], 4200 + 300 - 100)
        milk.order_cycle_days = None
        self.assertIn("missing", services.suggestion(milk, daily, projected, 300.0, 2)["components"])

    def test_evaluation_compares_three_methods_on_held_out_days(self):
        with mock.patch("apps.forecast.evaluate.history",
                        return_value=fake_history(self.size.pk, 84, self.today, weekday=24, weekend=36)):
            result = evaluate.evaluate(self.today)
        r = result["rows"][0]
        self.assertIn(r["delta"], evaluate.DELTAS)
        for h in evaluate.HORIZONS:
            for method in ("model", "owner", "naive"):
                self.assertIsNotNone(r["horizons"][h][method], (h, method))
        self.assertIn(r["verdict"], ("mo_hinh_tot_hon", "chua_tot_hon"))
        # Nhận định lệch (20 và 30) so với thực tế (24 và 36): mô hình học từ dữ liệu phải có CRPS 1 ngày thấp hơn
        self.assertLess(r["horizons"][1]["model"]["crps"], r["horizons"][1]["owner"]["crps"])


class ScreenTests(ForecastBase):
    def test_screens_permissions_and_order_from_suggestion(self):
        self.release()
        cashier = User.objects.create_user("thungan", password=PASSWORD, role=Role.THU_NGAN)
        self.client.login(username=cashier.username, password=PASSWORD)
        for name in ("forecast:overview", "forecast:ordering", "forecast:evaluation"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 403)
        self.client.login(username=self.owner.username, password=PASSWORD)
        self.assertContains(self.client.get(reverse("forecast:overview")), "Cà phê sữa M")
        with mock.patch("apps.forecast.evaluate.history",
                        return_value=fake_history(self.size.pk, 30, self.today)):
            self.assertEqual(self.client.get(reverse("forecast:evaluation")).status_code, 200)
        page = self.client.get(reverse("forecast:ordering"))
        self.assertContains(page, "Sữa đặc")
        sug = services.ordering_status(self.d["milk"])["suggestion"]["quantity"]
        url = reverse("forecast:ordering")
        expected = (self.today + timedelta(days=2)).isoformat()
        r = self.client.post(url, {"ingredient": self.d["milk"].pk, "quantity": str(sug + 380), "expected_date": expected,
                                   "operation_key": "khoa-thu-1"})
        self.assertFalse(PurchaseOrder.objects.exists())  # khác đề xuất mà không ghi lý do
        self.client.post(url, {"ingredient": self.d["milk"].pk, "quantity": str(sug + 380), "expected_date": expected,
                               "operation_key": "khoa-thu-2", "note": "Sắp có sự kiện"})
        rec = OrderSuggestion.objects.get()
        self.assertEqual((float(rec.suggested_quantity), float(rec.final_quantity)), (sug, sug + 380))  # AC-71
        self.assertEqual(rec.purchase_order.quantity, Decimal(str(sug + 380)))
        self.assertEqual(r.status_code, 302)

    def test_judgement_page_supersedes_and_keeps_history(self):
        self.client.login(username=self.owner.username, password=PASSWORD)
        r = self.client.post(reverse("masterdata:create", args=["nhan-dinh"]), {
            "size": self.size.pk, "day_type": "ngay_thuong", "typical": "22", "low": "15", "high": "30",
            "basis": "Sổ bán tay tháng 9"})
        self.assertEqual(r.status_code, 302)
        rows = ExpertJudgement.objects.filter(size=self.size, day_type="ngay_thuong")
        self.assertEqual(rows.count(), 2)
        self.assertEqual(rows.filter(superseded_at__isnull=True).get().typical, Decimal("22"))
        r = self.client.post(reverse("masterdata:create", args=["nhan-dinh"]), {
            "size": self.size.pk, "day_type": "ngay_thuong", "typical": "40", "low": "15", "high": "30", "basis": "x"})
        self.assertContains(r, "nằm giữa")
