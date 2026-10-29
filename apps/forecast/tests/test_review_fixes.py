"""Các điểm Chủ quán rà soát ngày 13/10/2026 trên nhánh du-bao-nguyen-lieu (commit 4ca2a4e): mỗi điểm một kiểm thử
tái hiện đúng tình huống đã nêu."""

from datetime import date, timedelta

from django.test import SimpleTestCase
from django.utils import timezone

from apps.forecast import methods, planning, policy
from apps.forecast.policy import Inputs, Lot

from .test_planning import PlanBase, at

THU = date(2026, 10, 15)


def base(**kw):
    daily = {THU + timedelta(days=j): 0.0 for j in range(0, 20)}
    data = dict(today=THU, daily=daily, sigma=[5.0] * 10, csl=95, available=10.0, group="A", review_days=1,
                target_days=2, pack=100.0, unit="g", pack_label="gói")
    data.update(kw)
    return Inputs(**data)


class ArrivalDayShortageTests(SimpleTestCase):
    def test_shortage_before_end_of_day_delivery_is_detected(self):
        """Điểm 1: đầu ngày còn 10, trong ngày cần 50, cuối ngày nhận 100: thiếu 40 trước khi hàng về."""
        fri = THU + timedelta(days=1)
        inp = base()
        inp.daily[fri] = 50.0
        inp.lots = [Lot(100.0, fri, "da_dat", 7)]
        r = policy.compute(inp)
        row = next(x for x in r["timeline"] if x["date"] == fri)
        self.assertEqual((row["before_arrival"], row["level"]), (-40.0, 60.0))
        self.assertEqual(r["stockout_date"], fri)
        self.assertEqual(r["risk_date"], fri)
        self.assertNotEqual(r["action"], policy.NONE)
        self.assertEqual(r["action"], policy.EXPEDITE)  # đề nghị giao trước giờ mở cửa ngày đó
        self.assertIn("trước giờ mở cửa", r["reason"])

    def test_unavoidable_shortage_without_lot_is_urgent_buy(self):
        fri = THU + timedelta(days=1)
        inp = base()
        inp.daily[fri] = 50.0
        r = policy.compute(inp)
        self.assertEqual(r["action"], policy.BUY)
        self.assertTrue(r["urgent"])


class CapacityTests(SimpleTestCase):
    def test_never_suggests_more_than_capacity(self):
        """Điểm 2: sức chứa 50, quy cách 100 một gói: không được đề xuất 200 như đề xuất thường."""
        inp = base(available=0.0, capacity=50.0)
        for j in range(1, 10):
            inp.daily[THU + timedelta(days=j)] = 60.0
        r = policy.compute(inp)
        self.assertLessEqual(r["quantity"], 50.0)
        self.assertTrue(r["infeasible"])
        self.assertEqual(r["binding"], "sức chứa")
        self.assertTrue(any("quy cách nhỏ hơn" in o for o in r["options"]))

    def test_shelf_life_conflict_offers_both_choices(self):
        inp = base(available=0.0, shelf_life=1, target_days=6)
        for j in range(1, 12):
            inp.daily[THU + timedelta(days=j)] = 60.0
        r = policy.compute(inp)
        self.assertFalse(r["infeasible"])
        self.assertEqual(r["conflict"], "hạn dùng")
        self.assertEqual(len(r["options"]), 2)
        # hạn 1 ngày chỉ dùng hết 60 trong khi gói 100: mua tối thiểu 1 gói, cảnh báo phần hết hạn
        self.assertEqual((r["packs"], r["expiry_excess"]), (1, 40))

    def test_safety_stock_is_capped_by_shelf_life(self):
        inp = base(available=0.0, shelf_life=3, target_days=2, sigma=[80.0] * 10)
        for j in range(0, 12):
            inp.daily[THU + timedelta(days=j)] = 60.0
        r = policy.compute(inp)
        # hạn 3 ngày, chu kỳ mua 2 ngày: phần tồn an toàn chỉ còn 1 ngày để dùng, tối đa 60
        self.assertEqual(r["ss_cap"], 60)
        self.assertLessEqual(r["ss_S"], 60)
        self.assertTrue(any("Tồn an toàn giới hạn" in n for n in r["notes"]))


class ReviewScheduleTests(SimpleTestCase):
    def test_fortnightly_review_is_not_daily(self):
        """Điểm 6: chu kỳ 14 ngày không được coi hôm nay luôn là ngày kiểm tra."""
        anchor = THU - timedelta(days=3)
        inp = base(group="B", review_days=14, target_days=14, review_anchor=anchor, available=10000.0)
        r = policy.compute(inp)
        self.assertFalse(r["review_today"])
        self.assertEqual(r["next_review"], anchor + timedelta(days=14))
        self.assertEqual(r["r_eff"], 11)
        on_day = policy.compute(base(group="B", review_days=14, target_days=14, review_anchor=THU,
                                     available=10000.0))
        self.assertTrue(on_day["review_today"])
        self.assertEqual(on_day["r_eff"], 14)

    def test_trigger_reason_separates_periodic_and_continuous(self):
        inp = base(group="B", review_days=7, target_days=7, review_weekday=THU.weekday(), available=100.0)
        for j in range(1, 12):
            inp.daily[THU + timedelta(days=j)] = 30.0
        self.assertEqual(policy.compute(inp)["trigger"], "định kỳ")
        inp = base(group="B", review_days=7, target_days=7, review_weekday=(THU.weekday() + 3) % 7, available=40.0)
        for j in range(1, 12):
            inp.daily[THU + timedelta(days=j)] = 30.0
        self.assertEqual(policy.compute(inp)["trigger"], "giám sát liên tục")


class OutOfSampleTests(SimpleTestCase):
    def series(self, tail):
        start = date(2026, 3, 2)
        out = []
        for j in range(120):
            d = start + timedelta(days=j)
            x = 100.0 + (30.0 if d.weekday() >= 5 else 0.0)
            if j >= 40:
                x = tail(d, x)
            out.append((d, x, "ok"))
        return out

    def test_first_origin_does_not_use_later_data(self):
        """Điểm 4: đổi dữ liệu sau gốc đầu tiên không được làm đổi sai số tại gốc đầu tiên."""
        a = self.series(lambda d, x: x)
        for method in ("M0", "LN", "WMA", "HW", "TSB"):
            ra = methods.rolling(a, method, estimate=(700, 760, 820), lookback=200)
            first = ra["origins"][0][0]
            b = [(d, x * (2.0 if d.weekday() == 2 else 0.5) if d > first else x, st) for d, x, st in a]
            rb = methods.rolling(b, method, estimate=(700, 760, 820), lookback=200)
            self.assertEqual(rb["origins"][0][0], first)
            self.assertAlmostEqual(ra["origins"][0][1][1][1], rb["origins"][0][1][1][1], places=6, msg=method)

    def test_holt_winters_starts_after_eight_weeks(self):
        s = self.series(lambda d, x: x)
        r = methods.rolling(s, "HW", lookback=200)
        ok_days = [d for d, _, st in s if st == "ok"]
        self.assertGreaterEqual(r["origins"][0][0], ok_days[55])

    def test_estimate_after_origin_is_not_used(self):
        s = self.series(lambda d, x: x)
        since = s[60][0]
        r = methods.rolling(s, "M0", estimate=(700, 760, 820), estimate_since=since, lookback=200)
        self.assertGreaterEqual(r["origins"][0][0], since)


class LongWindowTests(SimpleTestCase):
    def test_windows_used_for_buying_and_month_are_measured_or_marked(self):
        """Điểm 5: cửa sổ dài được đo trực tiếp; chưa đủ gốc thì ghi là ước lượng tạm."""
        start = date(2026, 1, 5)
        s = [(start + timedelta(days=j), 100.0 + (j * 7919 % 13), "ok") for j in range(200)]
        today = s[-1][0] + timedelta(days=1)
        fc = methods.forecast_series(s, today=today, horizon=35, decision_h=15, candidates=("LN", "WMA"))
        self.assertGreaterEqual(len(fc["sigma"]), 31)
        self.assertTrue(fc["sigma_measured"][14])  # R 14 + ℓ 1
        self.assertTrue(fc["sigma_measured"][30])  # tháng
        short = s[-40:]
        fc = methods.forecast_series(short, today=today, horizon=35, decision_h=15, candidates=("LN", "WMA"))
        self.assertFalse(all(fc["sigma_measured"]))


class IntradayRecomputeTests(PlanBase):
    def test_same_data_later_in_day_gives_new_calculation(self):
        """Điểm 3: 8 giờ và 16 giờ cùng dữ liệu nhưng phần nhu cầu còn lại của hôm nay khác nhau."""
        planning.run_full(at(self.today, 8))
        morning = self.milk.plans.get(is_current=True)
        afternoon = planning.recompute(self.milk.pk, at(self.today, 16))
        self.assertNotEqual(morning.pk, afternoon.pk)
        self.assertLess(afternoon.result["f0"], morning.result["f0"])
        self.assertEqual(planning.recompute(self.milk.pk, at(self.today, 16)).pk, afternoon.pk)


class SeasonalAdjustmentTests(PlanBase):
    def test_owner_seasonal_adjustment_applies_only_in_its_period(self):
        """Điểm 7: điều chỉnh mùa của Chủ quán có căn cứ, thời gian áp dụng và nguồn."""
        from apps.forecast.models import SeasonalAdjustment

        start = self.today + timedelta(days=7)
        SeasonalAdjustment.objects.create(store=self.d["store"], ingredient=self.milk, start=start,
                                          end=start + timedelta(days=20), percent=-15,
                                          basis="Sinh viên nghỉ hè năm trước", created_by=self.owner)
        fc = planning.build_forecasts(timezone.now())[self.milk.pk]
        before = planning.demand(fc, start - timedelta(days=7))
        inside = planning.demand(fc, start)
        self.assertAlmostEqual(inside / before, 0.85, places=2)  # cùng thứ, giảm 15%
        self.assertEqual(fc["seasonal"][0]["basis"], "Sinh viên nghỉ hè năm trước")


class SeasonNotDoubleCountedTests(SimpleTestCase):
    def test_season_is_relative_to_off_season_baseline(self):
        """Rà soát lần 2, điểm 1: nền 100, Chủ quán đặt −15%, mô hình đã học còn 85 thì không giảm thêm (72,25)."""
        f = methods.residual_season_factor
        self.assertAlmostEqual(f(-15, 100, 100), 0.85)  # chưa học: áp đủ
        self.assertAlmostEqual(f(-15, 100, 85) * 85, 85)  # đã học xong: ngừng điều chỉnh
        self.assertAlmostEqual(f(-15, 100, 92) * 92, 85)  # học một phần: chỉ áp phần còn thiếu
        self.assertAlmostEqual(f(-15, 100, 80), 1.0)  # mô hình giảm nhiều hơn: không đẩy ngược lên
        self.assertAlmostEqual(f(20, 100, 110) * 110, 120)


class FutureEstimateTests(SimpleTestCase):
    def test_estimate_effective_later_is_not_blended_yet(self):
        """Rà soát lần 2, điểm 2: ước tính có hiệu lực sau hôm nay chưa được trộn vào dự báo bước đầu."""
        start = date(2026, 3, 2)
        s = [(start + timedelta(days=j), 100.0 + (j * 37 % 11), "ok") for j in range(30)]
        today = s[-1][0] + timedelta(days=1)
        later = methods.forecast_series(s, today=today, horizon=7, estimate=(700, 760, 820),
                                        estimate_since=today + timedelta(days=3), candidates=("LN", "WMA"))
        none = methods.forecast_series(s, today=today, horizon=7, candidates=("LN", "WMA"))
        self.assertIsNone(later["prior_weight"])
        self.assertEqual(later["daily"], none["daily"])
        now = methods.forecast_series(s, today=today, horizon=7, estimate=(700, 760, 820), estimate_since=start,
                                      candidates=("LN", "WMA"))
        self.assertIsNotNone(now["prior_weight"])


class SeasonInPlanTests(PlanBase):
    def test_adapted_model_is_not_reduced_twice(self):
        from apps.forecast.models import SeasonalAdjustment

        for j in range(1, 50):
            day = self.today - timedelta(days=j)
            self.sell_day(day, 20 if j > 21 else 17)  # mùa bắt đầu 21 ngày trước: giảm 15%
        SeasonalAdjustment.objects.create(store=self.d["store"], ingredient=self.milk,
                                          start=self.today - timedelta(days=21), end=self.today + timedelta(days=30),
                                          percent=-15, basis="Nghỉ hè", created_by=self.owner)
        fc = planning.build_forecasts(timezone.now())[self.milk.pk]
        a = fc["seasonal"][0]
        self.assertEqual(a["baseline"], 600.0)
        upcoming = sum(list(fc["daily"].values())[:7]) / 7
        # tổng hiệu lực so với nền không vượt mức Chủ quán đặt
        factor = planning.season_factor(fc, self.today.isoformat())
        self.assertGreaterEqual(upcoming * factor / a["baseline"], 0.85 - 1e-6)


class SeasonEdgeTests(PlanBase):
    """Rà soát lần 3: thiếu nền ngoài mùa, điều chỉnh chung và riêng chồng nhau."""

    def adj(self, **kw):
        from apps.forecast.models import SeasonalAdjustment

        data = dict(store=self.d["store"], ingredient=self.milk, start=self.today - timedelta(days=3),
                    end=self.today + timedelta(days=30), percent=-15, basis="Nghỉ hè", created_by=self.owner)
        data.update(kw)
        a = SeasonalAdjustment(**data)
        a.full_clean()
        a.save()
        return a

    def test_started_season_without_baseline_is_not_applied(self):
        for j in range(1, 6):
            self.sell_day(self.today - timedelta(days=j), 17)
        self.adj()
        fc = planning.build_forecasts(timezone.now())[self.milk.pk]
        self.assertEqual(fc["seasonal"][0]["status"], "chua_xac_dinh_nen")
        self.assertEqual(planning.season_factor(fc, self.today.isoformat()), 1.0)  # không phải 0,85
        self.assertTrue(any("chưa xác định được nền" in w for w in fc["warnings"]))

    def test_owner_baseline_with_basis_is_used(self):
        for j in range(1, 6):
            self.sell_day(self.today - timedelta(days=j), 17)
        self.adj(baseline_daily=600)
        fc = planning.build_forecasts(timezone.now())[self.milk.pk]
        self.assertEqual((fc["seasonal"][0]["baseline_source"], fc["seasonal"][0]["status"]), ("chu_quan", "dang_ap"))
        self.assertAlmostEqual(planning.season_factor(fc, self.today.isoformat()),
                               methods.residual_season_factor(-15, 600.0, fc["season_current"]))

    def test_specific_replaces_general_and_same_scope_needs_independence(self):
        from django.core.exceptions import ValidationError

        future = dict(start=self.today + timedelta(days=5), end=self.today + timedelta(days=20))
        self.adj(ingredient=None, **future)
        self.adj(**future)
        fc = planning.build_forecasts(timezone.now())[self.milk.pk]
        iso = (self.today + timedelta(days=6)).isoformat()
        self.assertAlmostEqual(planning.season_factor(fc, iso), 0.85)  # không phải 0,7225
        self.assertTrue(any("điều chỉnh riêng" in w for w in fc["warnings"]))
        with self.assertRaises(ValidationError):
            self.adj(percent=-10, **future)  # cùng phạm vi, chưa xác nhận độc lập
        from apps.forecast.models import SeasonalAdjustment

        SeasonalAdjustment.objects.filter(ingredient=self.milk).update(independent=True)
        self.adj(percent=-10, independent=True, **future)
        fc = planning.build_forecasts(timezone.now())[self.milk.pk]
        self.assertAlmostEqual(planning.season_factor(fc, iso), 0.85 * 0.9)

