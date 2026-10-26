"""Bộ tính chính sách mua: hai ví dụ tính tay ở mục 10 và các kịch bản thuần chính sách ở mục 12.4."""

from datetime import date, timedelta

from django.test import SimpleTestCase

from apps.forecast import policy
from apps.forecast.policy import Inputs, Lot

THU = date(2026, 10, 15)
MILK_DAILY = [2600, 3300, 3400, 2300, 2300, 2350, 2400]  # thứ Sáu 16/10 đến thứ Năm 22/10


def milk_inputs(**kw):
    daily = {THU: 2500.0}
    daily.update({THU + timedelta(days=j + 1): float(v) for j, v in enumerate(MILK_DAILY)})
    base = dict(today=THU, daily=daily, sigma=[420, 700, 950], csl=95, available=3900.0, physical=3900.0,
                lots=[Lot(2000.0, date(2026, 10, 19), "da_dat", 1)], f0=0.0, group="A", review_days=1,
                target_days=2, exposure=1, pack=1000.0, pack_label="hộp", unit="ml", moq=1, shelf_life=7,
                capacity=20000.0)
    base.update(kw)
    return Inputs(**base)


class MilkExampleTests(SimpleTestCase):
    """Mục 10.1: sữa tươi nhóm A, tối thứ Năm 15/10/2026 lúc 22 giờ."""

    def setUp(self):
        self.r = policy.compute(milk_inputs())

    def test_levels(self):
        r = self.r
        self.assertEqual((r["k"], r["window_s_days"], r["window_S_days"]), (1.645, 2, 3))
        self.assertEqual((r["mu_s"], r["ss_s"], r["s"]), (5900, 1152, 7052))
        self.assertEqual((r["mu_S"], r["ss_S"], r["S"]), (9300, 1563, 10863))

    def test_inventory_position_excludes_monday_lot(self):
        r = self.r
        self.assertEqual((r["ip_s"], r["ip_S"]), (3900, 3900))
        self.assertEqual([lot.arrival for lot in r["uncounted_lots"]], [date(2026, 10, 19)])
        self.assertTrue(r["need"])

    def test_timeline_risk_and_order_by(self):
        r = self.r
        levels = {row["date"]: row["level"] for row in r["timeline"]}
        self.assertEqual([levels[THU + timedelta(days=j)] for j in range(1, 5)], [1300, -2000, -5400, -5700])
        self.assertEqual(r["timeline"][1]["safety"], 691)
        self.assertEqual(r["risk_date"], date(2026, 10, 17))
        self.assertEqual(r["stockout_date"], date(2026, 10, 17))
        self.assertEqual(r["order_by"], THU)
        self.assertTrue(r["order_now"])

    def test_quantity_and_caps(self):
        r = self.r
        self.assertEqual(r["q0"], 6963)
        self.assertEqual((r["packs"], r["quantity"], r["delta"]), (7, 7000, 37))
        self.assertEqual(r["caps"], {"hạn dùng": 14750, "sức chứa": 16100})
        self.assertIsNone(r["binding"])
        self.assertEqual(r["action"], policy.TOP_UP)  # đã có lô về sau ngày rủi ro
        self.assertIn("Cần đặt trong hôm nay 7 hộp", r["reason"])
        self.assertIn("sau ngày có thể thiếu", r["reason"])
        # Mẫu câu mục 9.1: hết sau khoảng 40% lượng bán của thứ Bảy
        self.assertEqual(r["stockout_part"], 0.39)
        self.assertIn("đủ tới khoảng giữa ngày thứ Bảy 17/10", r["reason"])
        self.assertIn("để hàng về trước thứ Bảy 17/10", r["reason"])

    def test_after_ordering_flow_matches_step_5(self):
        p = policy.Policy(milk_inputs())
        rows = p.timeline(5, p.i.lots + [Lot(7000.0, date(2026, 10, 16))])
        self.assertEqual([row["level"] for row in rows[1:5]], [8300, 5000, 1600, 1300])

    def test_naive_all_incoming_position_buys_five_and_runs_out_sunday(self):
        p = policy.Policy(milk_inputs())
        naive_ip = 3900 + 2000
        packs = policy._ceil((10863 - naive_ip) / 1000)
        self.assertEqual(packs, 5)
        rows = p.timeline(5, p.i.lots + [Lot(5000.0, date(2026, 10, 16))])
        _, stockout = p.scan(rows)
        self.assertEqual(stockout, date(2026, 10, 18))  # Chủ nhật, trước khi lô thứ Hai về

    def test_quantile_mode_does_not_add_ksigma(self):
        r = policy.compute(milk_inputs(quantiles={"s": 7100.0, "S": 10950.0}))
        self.assertEqual((r["S"], r["ss_S"], r["ss_method"]), (10950, 1650, "phân vị"))

    def test_manual_safety_stock_is_a_floor_with_reason(self):
        r = policy.compute(milk_inputs(manual_ss=2000.0))
        self.assertEqual((r["ss_s"], r["ss_S"], r["S"]), (2000, 2000, 11300))
        self.assertTrue(any("Chủ quán nhập" in n for n in r["notes"]))
        r = policy.compute(milk_inputs(manual_ss=100.0))
        self.assertEqual(r["S"], 10863)


class CoffeeExampleTests(SimpleTestCase):
    """Mục 10.2: cà phê bột nhóm B, kiểm tra tối Chủ nhật."""

    def test_weekly_review(self):
        sun = date(2026, 10, 18)
        daily = {sun + timedelta(days=j): 2000.0 for j in range(1, 9)}
        sigma = [600, 850, 1040, 1200, 1340, 1470, 1590, 2100]
        r = policy.compute(Inputs(today=sun, daily=daily, sigma=sigma, csl=95, available=6800.0, group="B",
                                  review_days=7, target_days=7, review_weekday=6, exposure=1, pack=1000.0,
                                  pack_label="túi", unit="g", shelf_life=90))
        self.assertEqual((r["window_s_days"], r["mu_S"], r["ss_S"], r["S"]), (8, 16000, 3455, 19455))
        self.assertEqual((r["ip_S"], r["q0"], r["packs"], r["delta"]), (6800, 12655, 13, 345))
        self.assertEqual(r["action"], policy.BUY)
        self.assertIsNone(r["binding"])
        self.assertGreater(r["caps"]["hạn dùng"], 170000)

    def test_small_shortfall_under_half_pack_is_skipped(self):
        sun = date(2026, 10, 18)
        daily = {sun + timedelta(days=j): 2000.0 for j in range(1, 9)}
        r = policy.compute(Inputs(today=sun, daily=daily, sigma=[100] * 8, csl=90, available=16000.0, group="B",
                                  review_days=7, target_days=7, review_weekday=6, pack=1000.0, unit="g"))
        self.assertLess(r["q0"], 500)
        self.assertEqual((r["action"], r["packs"]), (policy.NONE, 0))

    def test_midweek_monitoring_only_triggers_when_risk_falls_before_next_review(self):
        wed = date(2026, 10, 21)
        daily = {wed + timedelta(days=j): 2000.0 for j in range(0, 12)}
        quiet = policy.compute(Inputs(today=wed, daily=daily, sigma=[300] * 10, csl=90, available=14000.0,
                                      group="B", review_days=7, target_days=7, review_weekday=6, pack=1000.0))
        self.assertFalse(quiet["review_today"])
        self.assertEqual(quiet["action"], policy.NONE)
        urgent = policy.compute(Inputs(today=wed, daily=daily, sigma=[300] * 10, csl=90, available=3000.0,
                                       group="B", review_days=7, target_days=7, review_weekday=6, pack=1000.0))
        self.assertEqual(urgent["action"], policy.BUY)
        self.assertEqual(urgent["window_s_days"], 5)  # tới tối Chủ nhật cộng ℓ


class ScenarioTests(SimpleTestCase):
    """Mục 12.4."""

    def weekday_inputs(self, today, available, **kw):
        daily = {}
        for j in range(0, 14):
            t = today + timedelta(days=j)
            daily[t] = 1400.0 if t.weekday() >= 5 else 1000.0
        base = dict(today=today, daily=daily, sigma=[150, 220, 270, 310], csl=95, available=available, group="A",
                    review_days=1, target_days=2, pack=1000.0, unit="ml", pack_label="hộp")
        base.update(kw)
        return Inputs(**base)

    def test_weekend_surge_triggers_thursday_order_from_daily_sums(self):
        r = policy.compute(self.weekday_inputs(THU, 2200.0))  # đủ cho hơn hai ngày thường
        self.assertTrue(r["need"])
        self.assertEqual(r["mu_s"], 1000 + 1400)  # thứ Sáu + thứ Bảy, không phải 2 × trung bình
        self.assertEqual(r["mu_S"], 1000 + 1400 + 1400)
        mon = date(2026, 10, 19)
        self.assertFalse(policy.compute(self.weekday_inputs(mon, 2600.0))["need"])

    def test_late_supplier_lot_is_excluded_and_expedite_or_top_up(self):
        late = Lot(5000.0, THU - timedelta(days=1), "giao_cham", 9, "giao chậm")
        r = policy.compute(self.weekday_inputs(THU, 500.0, excluded=[late]))
        self.assertEqual(r["ip_s"], 500)
        self.assertEqual(r["action"], policy.EXPEDITE)  # lô giao chậm đưa về ngày mai thì hết rủi ro
        r = policy.compute(self.weekday_inputs(THU, 500.0, excluded=[Lot(500.0, THU, "giao_cham", 9)]))
        self.assertEqual(r["action"], policy.TOP_UP)

    def test_lot_before_risk_date_means_no_suggestion(self):
        lot = Lot(3000.0, THU + timedelta(days=1), "da_dat", 3)
        r = policy.compute(self.weekday_inputs(THU, 1500.0, lots=[lot]))
        self.assertEqual(r["action"], policy.NONE)
        self.assertEqual(r["ip_s"], 4500)

    def test_lot_after_risk_inside_window_is_not_allowed_to_hide_risk(self):
        sun = date(2026, 10, 18)
        daily = {sun + timedelta(days=j): 2000.0 for j in range(0, 12)}
        lot = Lot(20000.0, sun + timedelta(days=6), "da_dat", 4)
        r = policy.compute(Inputs(today=sun, daily=daily, sigma=[300] * 10, csl=95, available=3000.0, group="B",
                                  review_days=7, target_days=7, review_weekday=6, pack=1000.0, lots=[lot]))
        self.assertGreater(r["ip_S"], r["S"])  # vị thế tồn cổ điển nói đủ
        self.assertEqual(r["risk_date"], sun + timedelta(days=2))
        self.assertIn(r["action"], (policy.TOP_UP, policy.EXPEDITE))
        self.assertGreater(r["packs"], 0)

    def test_short_shelf_life_caps_quantity_with_note_or_expiry_warning(self):
        r = policy.compute(self.weekday_inputs(THU, 0.0, shelf_life=3, target_days=6))
        self.assertEqual(r["binding"], "hạn dùng")
        self.assertLessEqual(r["quantity"], r["caps"]["hạn dùng"] + 1000)
        self.assertTrue(any("Giới hạn bởi hạn dùng" in n for n in r["notes"]))
        r = policy.compute(self.weekday_inputs(THU, 0.0, shelf_life=1, target_days=6))
        self.assertGreater(r["expiry_excess"], 0)

    def test_moq_and_rounding(self):
        r = policy.compute(self.weekday_inputs(THU, 2200.0, moq=5))
        self.assertEqual(r["packs"], 5)
        self.assertEqual(r["delta"], round(5000 - r["q0"], 2))


class AgingTests(SimpleTestCase):
    """EWA (Broekmeulen và van Donselaar 2009): phần tồn sẽ hết hạn trước khi dùng kịp không tính vào vị thế tồn."""

    def test_lots_without_expiry_change_nothing(self):
        plain = policy.compute(milk_inputs())
        aged = policy.compute(milk_inputs(on_hand_lots=[(3900.0, date.max)]))
        self.assertEqual([r["level"] for r in aged["timeline"]], [r["level"] for r in plain["timeline"]])
        self.assertEqual((aged["ip_s"], aged["ip_S"], aged["outdating_s"]), (plain["ip_s"], plain["ip_S"], 0))

    def test_expiring_lot_is_not_counted(self):
        # 3000 ml hết hạn ngay tối nay (đã 22 giờ, không còn bán): chỉ 900 ml mới bảo vệ được cửa sổ.
        r = policy.compute(milk_inputs(on_hand_lots=[(3000.0, THU), (900.0, THU + timedelta(days=6))]))
        self.assertEqual((r["outdating_s"], r["ip_s"], r["ip_S"]), (3000, 900, 900))
        self.assertEqual(r["timeline"][0]["expiring"], 3000)
        self.assertGreater(r["quantity"], policy.compute(milk_inputs())["quantity"])

    def test_fifo_uses_old_lot_first(self):
        # Lô cũ 1500 ml hết hạn ngày mai, ngày mai dùng 2600 ml: lô cũ dùng hết trước hạn, không bỏ gì.
        r = policy.compute(milk_inputs(on_hand_lots=[(1500.0, THU + timedelta(days=1)), (2400.0, THU + timedelta(days=6))]))
        self.assertEqual(r["outdating_S"], 0)
        self.assertEqual(r["ip_S"], policy.compute(milk_inputs())["ip_S"])

    def test_stock_without_receipt_never_expires(self):
        # Tồn đầu kỳ không khớp phiếu nhập nào: coi như không hết hạn, không trừ.
        r = policy.compute(milk_inputs(on_hand_lots=[(900.0, THU + timedelta(days=6))]))
        self.assertEqual((r["outdating_s"], r["ip_s"]), (0, 3900))


class SimulationSmokeTests(SimpleTestCase):
    def test_closed_loop_runs_and_reports(self):
        from apps.forecast import simulation as sim

        specs = [s for s in sim.SPECS if s.name in ("Sữa tươi", "Xoài", "Cà phê bột")]
        r = sim.simulate(sim.Rules(), seed=3, days=45, specs=specs)
        self.assertEqual(set(r["ingredients"]), {s.name for s in specs})
        self.assertEqual(r["ingredients"]["Cà phê bột"]["csl"], 98)  # hàng để lâu
        self.assertEqual(r["ingredients"]["Xoài"]["csl"], 95)
        self.assertGreaterEqual(r["stockouts_per_month"], 0)
