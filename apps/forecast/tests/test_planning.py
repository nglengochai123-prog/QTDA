"""Kế hoạch mua nguyên liệu trên dữ liệu thật của hệ thống (mục 12.4): chuỗi tiêu hao, phương pháp, chống trùng,
đợt rủi ro, giám sát sau biến động và thao tác của Chủ quán."""

import uuid
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from unittest import mock

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from apps.control import alerts
from apps.control.models import Alert
from apps.core import params
from apps.forecast import methods, planning, usage
from apps.forecast.models import IngredientDailyUsage, IngredientPlan, OrderSuggestion, PlanRun
from apps.inventory import operations as ops
from apps.inventory import stock
from apps.inventory.models import (Ingredient, PurchaseOrder, RecipeLine, ShortageCase, StockMovement, Supplier)
from apps.orders.models import Order, OrderLine, OrderLineOption, PostPrepCancellation
from apps.orders.tests.helpers import build_menu
from apps.shifts.models import Shift, ShiftReport


def key():
    return uuid.uuid4().hex


def at(day, hour=8):
    return timezone.make_aware(datetime.combine(day, time(hour)), timezone.get_current_timezone())


class PlanBase(TestCase):
    def setUp(self):
        self.d = build_menu(coffee_opening=50000, milk_opening=1000)
        self.owner = self.d["owner"]
        self.today = timezone.localdate()
        self.supplier = Supplier.objects.create(store=self.d["store"], name="NCC sữa")
        milk = self.milk = self.d["milk"]
        milk.main_supplier, milk.pack_size, milk.shelf_life_days = self.supplier, Decimal(1000), 7
        milk.weekly_low, milk.weekly_typical, milk.weekly_high = 3500, 4200, 5000
        milk.save()
        self.n = 0

    def sell_day(self, day, cups, options=(), voided=0):
        """Một ngày đã chốt: ca đã kết có báo cáo cuối ca và một đơn `cups` ly cà phê sữa M."""
        shift = Shift.objects.create(store=self.d["store"], name="Ca", starts_at=at(day, 6), ends_at=at(day, 22),
                                     approver=self.owner, status=Shift.Status.CLOSED)
        ShiftReport.objects.create(store=self.d["store"], shift=shift, counted_cash=0, transfer_received=0,
                                   submitted_by=self.owner)
        self.n += 1
        order = Order.objects.create(store=self.d["store"], code=f"T{self.n}", table=self.d["table"],
                                     created_by=self.owner, operation_key=key(), shift=shift,
                                     status=Order.Status.PAID)
        usage_per = {str(self.d["coffee"].pk): "20", str(self.milk.pk): "30"}
        if options:
            usage_per[str(self.milk.pk)] = "45"
        line = OrderLine.objects.create(order=order, position=1, item=self.d["item"], size=self.d["size_m"],
                                        item_name="Cà phê sữa", size_name="M", unit_price=25000, quantity=cups,
                                        done_quantity=cups, voided_done_quantity=voided, usage_per_unit=usage_per,
                                        status=OrderLine.Status.SERVED, recipe_version=self.d["v1"])
        for o in options:
            OrderLineOption.objects.create(line=line, option=o, name=o.name, extra_price=0)
        Order.objects.filter(pk=order.pk).update(created_at=at(day, 10))
        return line


class UsageSeriesTests(PlanBase):
    def test_eligible_days_skip_closed_unfinalized_and_stockout(self):
        y = self.today - timedelta(days=1)
        for j in range(2, 9):
            if j != 4:  # ngày y-3 đóng cửa
                self.sell_day(self.today - timedelta(days=j), 10)
        ShortageCase.objects.create(store=self.d["store"], ingredient=self.milk, day=self.today - timedelta(days=5),
                                    source="bao_het")
        Shift.objects.create(store=self.d["store"], name="Ca", starts_at=at(y, 6), ends_at=at(y, 22),
                             approver=self.owner)  # hôm qua chưa kết ca
        data = usage.build(self.today)
        series = dict((d, (x, st)) for d, x, st in usage.series_for(data, self.milk.pk))
        self.assertEqual(series[self.today - timedelta(days=4)][1], "dong_cua")
        self.assertEqual(series[self.today - timedelta(days=5)][1], "bo_qua")  # hết hàng: nhu cầu bị chặn
        self.assertEqual(series[y][1], "bo_qua")  # chưa chốt
        self.assertEqual(series[self.today - timedelta(days=2)], (300.0, "ok"))
        self.assertEqual(usage.save(data), IngredientDailyUsage.objects.count())

    def test_option_ingredient_shortage_blocks_day_for_main_ingredient(self):
        """Ngày thiếu nguyên liệu của tùy chọn: món bị ngừng bán chiếm 100% tiêu hao sữa nên sữa bị chặn gián tiếp."""
        cream = Ingredient.objects.create(store=self.d["store"], name="Kem tươi", unit="ml", pack_size=1000,
                                          lead_time_days=1)
        draft = self.d["v1"].copy_as_draft()
        RecipeLine.objects.create(version=draft, option=self.d["cream"], ingredient=cream, quantity=10)
        draft.publish(self.owner)
        for j in range(1, 8):
            self.sell_day(self.today - timedelta(days=j), 10, options=[self.d["cream"]])
        bad = self.today - timedelta(days=3)
        ShortageCase.objects.create(store=self.d["store"], ingredient=cream, day=bad, source="bao_het")
        data = usage.build(self.today)
        status = {d: st for d, _, st in usage.series_for(data, self.milk.pk)}
        self.assertEqual(status[bad], "bo_qua")
        self.assertTrue(data["rows"][self.milk.pk][bad]["indirect_block"])
        self.assertEqual({d: st for d, _, st in usage.series_for(data, cream.pk)}[bad], "bo_qua")
        # tùy chọn được tính đủ: 10 ly × (30 + 15) ml
        self.assertEqual(data["rows"][self.milk.pk][self.today - timedelta(days=2)]["sales"], 450.0)

    def test_post_prep_voids_are_not_sales_and_reconcile_with_ledger(self):
        """5 ly hủy sau pha chế: không vào chuỗi bán, vào tỷ lệ hủy; đối soát với sổ kho khớp.

        Sổ kho chỉ thêm mới nên không lùi ngày được: dùng ngày hôm nay và dựng chuỗi như khi tính vào ngày mai."""
        day, tomorrow = self.today, self.today + timedelta(days=1)
        line = self.sell_day(day, 20, voided=5)
        from apps.orders.models import AdjustmentReason, AdjustmentRequest

        reason = AdjustmentReason.objects.create(store=self.d["store"], name="Khách đổi ý")
        req = AdjustmentRequest.objects.create(store=self.d["store"], order=line.order, kind="huy_mon",
                                               reason=reason, requested_by=self.owner, status="da_duyet",
                                               level_since=timezone.now())
        PostPrepCancellation.objects.create(line=line, cups=5, reason=reason, request=req,
                                            usage={str(self.milk.pk): "150", str(self.d["coffee"].pk): "100"})
        stock.move(self.milk.pk, -600, kind=StockMovement.Kind.CONSUME, actor=self.owner, store=self.d["store"],
                   source_type="pha_che")
        data = usage.build(tomorrow)
        row = data["rows"][self.milk.pk][day]
        self.assertEqual((row["sales"], row["voided"], row["consumed_ledger"]), (450.0, 150.0, 600.0))
        r = usage.rates(data, self.milk.pk)
        self.assertAlmostEqual(r["r_h"], 150 / 450, places=3)
        self.assertFalse(r["recon"]["flag"])
        stock.move(self.milk.pk, -100, kind=StockMovement.Kind.CONSUME, actor=self.owner, store=self.d["store"],
                   source_type="pha_che")
        self.assertTrue(usage.rates(usage.build(tomorrow), self.milk.pk)["recon"]["flag"])

    def test_one_off_and_stock_losses_are_not_demand(self):
        day = self.today - timedelta(days=1)
        self.sell_day(day, 10)
        ops.record_waste(self.owner, key(), self.milk.pk, 30, "pha_hong")
        ops.record_waste(self.owner, key(), self.milk.pk, 100, "do_vo", is_one_off=True)
        ops.record_waste(self.owner, key(), self.milk.pk, 200, "het_han")
        from apps.inventory.models import Waste

        Waste.objects.update(created_at=at(day, 15))
        r = usage.rates(usage.build(self.today), self.milk.pk)
        self.assertAlmostEqual(r["r_vh"], 30 / 300, places=4)
        self.assertEqual((r["waste_one_off_8w"], r["waste_stock_8w"]), (100, 200))

    def test_recipe_change_from_monday_changes_forecast_from_monday_only(self):
        for j in range(1, 22):
            self.sell_day(self.today - timedelta(days=j), 20)
        monday = self.today + timedelta(days=(7 - self.today.weekday()) % 7 or 7)
        draft = self.d["v1"].copy_as_draft()
        line = draft.lines.get(size=self.d["size_m"], ingredient=self.milk)
        RecipeLine.objects.filter(pk=line.pk).update(quantity=24)  # giảm 20% sữa
        draft.publish(self.owner, effective_from=at(monday, 0))
        fc = planning.build_forecasts(timezone.now())[self.milk.pk]
        self.assertAlmostEqual(fc["recipe_ratio"][monday.isoformat()], 0.8, places=3)
        self.assertNotIn((monday - timedelta(days=1)).isoformat(), fc["recipe_ratio"])
        before = planning.demand(fc, monday - timedelta(days=7)) if monday - timedelta(days=7) >= self.today else None
        after = planning.demand(fc, monday + timedelta(days=7))
        self.assertAlmostEqual(after, fc["daily"][(monday + timedelta(days=7)).isoformat()] * fc["factor"] * 0.8)
        if before is not None:
            self.assertAlmostEqual(before, fc["daily"][(monday - timedelta(days=7)).isoformat()] * fc["factor"])


class MethodStageTests(PlanBase):
    def test_short_history_uses_owner_estimate_with_provisional_label(self):
        for j in range(1, 6):
            self.sell_day(self.today - timedelta(days=j), 20)
        fc = planning.build_forecasts(at(self.today))[self.milk.pk]
        self.assertEqual((fc["method"], fc["stage"], fc["provisional"]), ("M0", "uoc_tinh", True))
        self.assertAlmostEqual(fc["sigma"][6], (5000 - 3500) / 3.29, places=1)  # tuần: (cao − thấp) / 3,29
        self.assertAlmostEqual(sum(list(fc["daily"].values())[:7]), 4200, places=0)

    def test_no_estimate_and_no_data_is_reported_not_guessed(self):
        self.milk.weekly_low = self.milk.weekly_typical = self.milk.weekly_high = None
        self.milk.save()
        run = planning.run_full(at(self.today))
        plan = self.milk.plans.get(run=run)
        self.assertEqual(plan.action, IngredientPlan.Action.NO_DATA)


class SeriesMethodTests(SimpleTestCase):
    def series(self, days, level=lambda j: 1000.0, weekend=1.4, start=date(2026, 1, 5)):
        out = []
        for j in range(days):
            d = start + timedelta(days=j)
            out.append((d, level(j) * (weekend if d.weekday() >= 5 else 1.0), "ok"))
        return out

    def test_weighted_same_weekday_and_day_type_average(self):
        s = self.series(56, level=lambda j: 100.0 + j)  # thứ Hai 05/01/2026 là j = 0
        end = s[-1][0]
        wma = methods.wma_table(s, end)
        mondays = [100.0 + j for j in (49, 42, 35, 28)]  # 4 thứ Hai gần nhất, mới nhất trước
        self.assertAlmostEqual(wma[0], 0.4 * mondays[0] + 0.3 * mondays[1] + 0.2 * mondays[2] + 0.1 * mondays[3])
        ln = methods.ln_table(s, end)
        recent = s[-28:]
        weekdays = [x for d, x, _ in recent if d.weekday() < 5]
        self.assertAlmostEqual(ln[False], sum(weekdays) / len(weekdays))
        gaps = [(d, x if d.weekday() != 0 or d > end - timedelta(days=14) else None,
                 "ok" if d.weekday() != 0 or d > end - timedelta(days=14) else "bo_qua") for d, x, _ in s]
        two = methods.wma_table(gaps, end)  # thứ Hai chỉ còn 2 lần: chia lại trọng số 0,4 / 0,3
        self.assertAlmostEqual(two[0], (0.4 * mondays[0] + 0.3 * mondays[1]) / 0.7)

    def test_level_drop_weighted_average_and_holt_winters_catch_up(self):
        s = self.series(105, level=lambda j: 1000.0 if j < 84 else 750.0)
        today = s[-1][0] + timedelta(days=1)
        weekday = next(today + timedelta(days=j) for j in range(7) if (today + timedelta(days=j)).weekday() == 2)
        wma = methods.predictor(s, "WMA")(weekday)
        hw = methods.predictor(s, "HW")(weekday)
        ln = methods.predictor(s, "LN")(weekday)
        self.assertAlmostEqual(wma, 775.0)  # ba tuần mới 750, tuần thứ tư còn 1000 với trọng số 0,1
        self.assertLess(hw, 850)
        self.assertLess(ln, 850)
        fc = methods.forecast_series(s, today=today, horizon=14, candidates=("LN", "WMA", "HW"), decision_h=2)
        self.assertEqual(fc["stage"], "mo_hinh")
        self.assertTrue(fc["auto_pick"])  # chưa có lựa chọn: tự chọn lần đầu theo sai số
        self.assertIn(fc["method"], ("LN", "WMA", "HW"))

    def test_holt_winters_needs_eight_weeks(self):
        self.assertIsNone(methods.predictor(self.series(50), "HW"))
        self.assertIsNotNone(methods.predictor(self.series(60), "HW"))

    def test_stages_follow_amount_of_data(self):
        est = (6000, 7000, 8000)
        short = self.series(10)
        today = short[-1][0] + timedelta(days=1)
        fc = methods.forecast_series(short, today=today, horizon=7, estimate=est, candidates=("LN", "WMA"))
        self.assertEqual((fc["method"], fc["stage"]), ("M0", methods.STAGE_OWNER))
        mid = self.series(35)
        today = mid[-1][0] + timedelta(days=1)
        fc = methods.forecast_series(mid, today=today, horizon=7, estimate=est, candidates=("LN", "WMA"))
        self.assertEqual((fc["method"], fc["stage"]), ("WMA", methods.STAGE_EARLY))  # đủ 4 tuần: cùng thứ
        self.assertAlmostEqual(fc["prior_weight"], 7 / 42, places=3)  # ước tính nặng như 7 ngày dữ liệu
        fc = methods.forecast_series(self.series(20), today=self.series(20)[-1][0] + timedelta(days=1), horizon=7,
                                     candidates=("LN", "WMA"))
        self.assertEqual(fc["method"], "LN")  # chưa đủ 4 lần mỗi thứ: theo loại ngày

    def test_intermittent_series_uses_tsb(self):
        start = date(2026, 1, 5)
        s = [(start + timedelta(days=j), 6.0 if j % 4 == 0 else 0.0, "ok") for j in range(80)]
        cls = methods.demand_class(s, s[-1][0])
        self.assertTrue(cls["intermittent"])
        self.assertEqual(cls["kind"], "lac_dac")
        value = methods.predictor(s, "TSB")(s[-1][0] + timedelta(days=1))
        self.assertAlmostEqual(value, 1.5, delta=0.4)  # khoảng 1 ngày có bán mỗi 4 ngày × 6
        steady = methods.demand_class(self.series(80), date(2026, 3, 25))
        self.assertFalse(steady["intermittent"])

    def test_biased_methods_are_dropped_with_warning(self):
        s = self.series(120, level=lambda j: 1000.0 + 6 * j)  # xu hướng tăng đều: bình quân luôn dự báo thấp
        today = s[-1][0] + timedelta(days=1)
        fc = methods.forecast_series(s, today=today, horizon=14, candidates=("LN", "WMA"), decision_h=2,
                                     approved="LN")
        self.assertTrue(any("lệch hệ thống" in w for w in fc["warnings"]))
        self.assertIn(fc["method"], ("LN", "WMA"))

    def test_switch_is_only_proposed_after_five_percent_gain_over_four_weeks(self):
        start = date(2026, 3, 1)
        inc = [(start + timedelta(days=j), {2: (100.0, 0.0)}) for j in range(40)]
        close = [(d, {2: (97.0, 0.0)}) for d, _ in inc]
        better = [(d, {2: (90.0, 0.0)}) for d, _ in inc]
        self.assertAlmostEqual(methods._recent_gain(inc, close, 2, 28), 0.03)
        self.assertAlmostEqual(methods._recent_gain(inc, better, 2, 28), 0.10)
        self.assertIsNone(methods._recent_gain(inc[:20], better[:20], 2, 28))  # chưa đủ 4 tuần
        flat = self.series(120)
        today = flat[-1][0] + timedelta(days=1)

        def fake(series, method, cfg=methods.DEFAULT, **kw):
            err = {"LN": 100.0, "WMA": 97.0 if kw.get("_close", True) else 90.0}[method]
            origins = [(start + timedelta(days=j), {h: (1000.0 + err * (1 if j % 2 else -1), 1000.0)
                                                    for h in range(1, 32)}) for j in range(60)]
            return {"origins": origins, "by_h": methods.summarize(origins), "predictions": {}}

        with mock.patch.object(methods, "rolling", side_effect=fake):
            kept = methods.forecast_series(flat, today=today, horizon=7, decision_h=2, candidates=("LN", "WMA"),
                                           approved="LN")
        self.assertEqual((kept["method"], kept["proposal"]), ("LN", None))  # chỉ thấp hơn 3%: không đề xuất
        with mock.patch.object(methods, "rolling",
                               side_effect=lambda series, method, cfg=methods.DEFAULT, **kw: fake(
                                   series, method, _close=False)):
            proposed = methods.forecast_series(flat, today=today, horizon=7, decision_h=2, candidates=("LN", "WMA"),
                                               approved="LN")
            auto = methods.forecast_series(flat, today=today, horizon=7, decision_h=2, candidates=("LN", "WMA"),
                                           approved="LN", cfg=methods.with_overrides(methods.DEFAULT,
                                                                                     auto_switch=True))
        # BRU-37: cách tốt hơn 10% chỉ được đề xuất, chờ Chủ quán duyệt; không tự đổi
        self.assertEqual(proposed["method"], "LN")
        self.assertEqual((proposed["proposal"]["method"], proposed["proposal"]["gain"]), ("WMA", 0.1))
        self.assertEqual(auto["method"], "WMA")


class HierarchyTests(SimpleTestCase):
    def test_total_split_by_item_shares_and_recipe(self):
        from apps.forecast import hierarchy

        start = date(2026, 1, 5)
        days = [start + timedelta(days=j) for j in range(70)]
        a = [(d, 60.0, "ok") for d in days]
        b = [(d, 40.0 if d.weekday() < 5 else 80.0, "ok") for d in days]
        total = [(d, a[i][1] + b[i][1], "ok") for i, d in enumerate(days)]
        items = [hierarchy.Item("a", a, {"milk": 30.0}), hierarchy.Item("b", b, {"milk": 10.0, "tea": 5.0}),
                 hierarchy.Item("new", [(d, 0.0, "ok") for d in days], {"tea": 4.0}, judgement={False: 5, True: 5})]
        today = days[-1] + timedelta(days=1)
        h = hierarchy.build(total, items, today=today, horizon=7)
        sat = next(today + timedelta(days=j) for j in range(7) if (today + timedelta(days=j)).weekday() == 5).isoformat()
        cups = h["today"][sat]
        self.assertAlmostEqual(sum(cups.values()), h["total"]["daily"][sat])  # tổng các món bằng tổng cả quán
        self.assertAlmostEqual(cups["b"] / cups["a"], 80 / 60, places=6)
        self.assertGreater(cups["new"], 0)  # món mới chưa bán: theo nhận định của Chủ quán
        external, daily = hierarchy.ingredient_forecast(h, items, "milk")
        self.assertAlmostEqual(daily[sat], cups["a"] * 30 + cups["b"] * 10)
        self.assertTrue(external)
        origin = sorted(external)[-1]
        self.assertTrue(all(iso > origin for iso in external[origin]))  # dự báo của gốc chỉ cho ngày sau gốc
        self.assertEqual(hierarchy.ingredient_forecast(h, items, "coffee"), (None, None))
        shares = hierarchy.group_shares(items, "milk", {"a": 100, "b": 100})
        self.assertEqual(shares, {None: 1.0})


class PlanRunTests(PlanBase):
    def test_rerun_returns_same_row_and_no_duplicate_alert(self):
        morning = at(self.today, 8)
        planning.run_full(morning)
        planning.run_full(morning)
        self.assertEqual(PlanRun.objects.count(), 2)
        self.assertEqual(IngredientPlan.objects.filter(ingredient=self.milk).count(), 1)
        plan = self.milk.plans.get()
        self.assertTrue(plan.alert_on)
        alerts.sync(morning)
        alerts.sync(morning)
        self.assertEqual(Alert.objects.filter(kind=Alert.Kind.ORDER_NEEDED).count(), 1)
        self.assertEqual(planning.recompute(self.milk.pk, morning).pk, plan.pk)

    def test_runs_never_create_orders_and_accept_creates_one_draft(self):
        morning = at(self.today, 8)
        planning.run_full(morning)
        self.assertFalse(PurchaseOrder.objects.exists())  # không tự đặt, không liên hệ nhà cung cấp
        plan = self.milk.plans.get()
        k = key()
        po = planning.accept(self.owner, plan, plan.suggested_quantity, "", self.today + timedelta(days=1), k)
        again = planning.accept(self.owner, plan, plan.suggested_quantity, "", self.today + timedelta(days=1), k)
        self.assertEqual(po.pk, again.pk)
        self.assertEqual((PurchaseOrder.objects.count(), OrderSuggestion.objects.count()), (1, 1))
        self.assertEqual(po.status, PurchaseOrder.Status.DRAFT)
        self.assertEqual(OrderSuggestion.objects.get().decision, "chap_nhan")
        # Đơn nháp được tính là hàng đang về: lần tính sau không đề xuất trùng
        after = planning.recompute(self.milk.pk, morning)
        self.assertNotEqual(after.pk, plan.pk)
        self.assertIn(after.action, ("khong_can", "mua_bo_sung"))
        self.assertEqual(after.result["ip_s"], 1000 + float(po.quantity))
        with self.assertRaises(ValidationError):
            planning.accept(self.owner, after, after.suggested_quantity + 1000, "", self.today, key())
        with self.assertRaises(ValidationError):
            planning.skip(self.owner, after, "", key())
        planning.skip(self.owner, after, "Đã mua ngoài chợ", key())
        self.assertEqual(OrderSuggestion.objects.filter(decision="bo_qua").count(), 1)
        ops.mark_ordered(self.owner, po.pk, self.today + timedelta(days=1))
        po.refresh_from_db()
        self.assertEqual(po.status, PurchaseOrder.Status.ORDERED)
        self.assertIsNotNone(po.ordered_at)

    def test_manually_closed_alert_reopens_for_new_episode(self):
        morning = at(self.today, 8)
        planning.run_full(morning)
        alerts.sync(morning)
        alert = Alert.objects.get(kind=Alert.Kind.ORDER_NEEDED)
        alerts.close(self.owner, alert.pk, "Đã mua ngoài chợ")
        stock.move(self.milk.pk, 20000, kind=StockMovement.Kind.RECEIPT, actor=self.owner, store=self.d["store"],
                   source_type="phieu_nhap")
        self.assertFalse(planning.recompute(self.milk.pk, morning).alert_on)
        alerts.sync(morning)
        stock.move(self.milk.pk, -20000, kind=StockMovement.Kind.WASTE, actor=self.owner, store=self.d["store"],
                   source_type="hao_hut")
        again = planning.recompute(self.milk.pk, morning)
        self.assertTrue(again.alert_on)
        alerts.sync(morning)
        self.assertEqual(Alert.objects.filter(kind=Alert.Kind.ORDER_NEEDED).count(), 2)
        self.assertEqual(Alert.objects.filter(kind=Alert.Kind.ORDER_NEEDED, status="moi").count(), 1)

    def test_draft_counts_until_order_by_then_drops_and_reminds(self):
        po = PurchaseOrder.objects.create(store=self.d["store"], supplier=self.supplier, ingredient=self.milk,
                                          quantity=3000, expected_date=self.today + timedelta(days=1),
                                          created_by=self.owner, status="nhap", order_by=self.today)
        self.assertTrue(po.is_incoming(self.today))
        self.assertFalse(po.is_incoming(self.today + timedelta(days=1)))
        self.assertTrue(any(i["episode"] == f"nhap-{po.pk}" for i in planning.alert_items(self.today)))
        late = PurchaseOrder.objects.create(store=self.d["store"], supplier=self.supplier, ingredient=self.milk,
                                            quantity=3000, expected_date=self.today - timedelta(days=1),
                                            created_by=self.owner)
        self.assertEqual(late.effective_status(self.today), PurchaseOrder.Status.LATE)
        lots, excluded, _ = planning._lots(self.milk, self.today)
        self.assertEqual([lot.po_id for lot in lots], [po.pk])
        self.assertEqual([lot.po_id for lot in excluded], [late.pk])

    def test_partial_delivery_counts_only_remaining(self):
        po = PurchaseOrder.objects.create(store=self.d["store"], supplier=self.supplier, ingredient=self.milk,
                                          quantity=10000, received_quantity=6000, status="giao_mot_phan",
                                          expected_date=self.today + timedelta(days=1), created_by=self.owner)
        lots, _, _ = planning._lots(self.milk, self.today)
        self.assertEqual([(lot.po_id, lot.quantity) for lot in lots], [(po.pk, 4000.0)])

    def test_over_receipt_is_recorded_with_warning(self):
        po = PurchaseOrder.objects.create(store=self.d["store"], supplier=self.supplier, ingredient=self.milk,
                                          quantity=2000, expected_date=self.today, created_by=self.owner)
        photo = SimpleUploadedFile("hd.jpg", b"\xff\xd8\xff", content_type="image/jpeg")
        result, _ = ops.create_receipt(self.owner, key(), self.supplier.pk, [
            {"ingredient": self.milk.pk, "quantity": "2500", "unit_price": 30, "purchase_order": po.pk,
             "expiry_date": (self.today + timedelta(days=7)).isoformat()}], "tra_sau", invoice_photo=photo)
        po.refresh_from_db()
        self.assertEqual((po.status, po.remaining, po.over_received), ("da_giao_du", 0, 500))
        self.assertTrue(result["warnings"])
        self.assertEqual(po.receipt_lines.get().expiry_date, self.today + timedelta(days=7))

    def test_on_hand_lots_come_from_stock_lots(self):
        photo = SimpleUploadedFile("hd.jpg", b"\xff\xd8\xff", content_type="image/jpeg")
        for qty, expiry in (("2000", None), ("3000", (self.today + timedelta(days=3)).isoformat())):
            ops.create_receipt(self.owner, key(), self.supplier.pk, [
                {"ingredient": self.milk.pk, "quantity": qty, "unit_price": 30, "expiry_date": expiry}], "tra_ngay",
                invoice_photo=photo)
        # Mỗi dòng phiếu nhập là một lô: hạn ghi trên phiếu, không ghi thì ngày nhập + 7 − 1.
        lots = planning.on_hand_lots(self.milk)
        self.assertIn((2000.0, self.today + timedelta(days=6)), lots)
        self.assertIn((3000.0, self.today + timedelta(days=3)), lots)
        self.milk.stock.refresh_from_db()
        self.assertEqual(sum(q for q, _ in lots), float(self.milk.stock.physical))

    def test_long_life_items_get_higher_service_level(self):
        self.assertEqual(planning.settings_for(self.milk)["csl"], params.get("plan_csl_normal_percent"))  # nhóm A
        coffee = self.d["coffee"]
        cfg = planning.settings_for(coffee)  # không có hạn dùng: nhóm B
        self.assertEqual((cfg["group"], cfg["csl"]), ("B", 98))
        coffee.service_level = 92
        coffee.save()
        self.assertEqual(planning.settings_for(coffee)["csl"], 92)  # Chủ quán đặt riêng thì giữ

    def test_stock_movement_triggers_one_coalesced_recompute_after_commit(self):
        planning.run_full(at(self.today, 8))
        with mock.patch.object(planning, "recompute") as rc:
            with self.captureOnCommitCallbacks(execute=True):
                with transaction.atomic():
                    for _ in range(3):
                        stock.move(self.milk.pk, -10, kind=StockMovement.Kind.WASTE, actor=self.owner,
                                   store=self.d["store"], source_type="hao_hut")
                    self.assertFalse(rc.called)  # chưa chạy trong giao dịch ghi tồn
        rc.assert_called_once_with(self.milk.pk)

    def test_periodic_runs_once_after_close(self):
        evening = at(self.today, params_close() + 1) if params_close() < 23 else at(self.today, 23)
        self.assertIsNotNone(planning.ensure_daily(evening))
        self.assertIsNone(planning.ensure_daily(evening + timedelta(minutes=1)))


def params_close():
    from apps.core import params

    return params.get("close_hour")
