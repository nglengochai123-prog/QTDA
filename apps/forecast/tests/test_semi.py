"""Bán thành phẩm: định mức nhiều tầng, ghi mẻ làm nhập kho, không trừ nguyên liệu gốc hai lần, nhu cầu nguyên liệu gốc
gồm phần đi qua bán thành phẩm."""

import uuid
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.forecast import planning, usage
from apps.forecast.models import IngredientPlan
from apps.inventory import lots, stock
from apps.inventory import operations as ops
from apps.inventory.models import (Ingredient, IngredientKind, RecipeLine, RecipeVersion, SemiBatch, SemiRecipe,
                                   SemiRecipeLine, ShortageCase, StockLot, StockMovement, Waste)
from apps.orders import services
from apps.orders.models import OrderLine
from apps.orders.tests.helpers import PASSWORD, cart, clock_in, levels

from .test_planning import PlanBase, at


def key():
    return uuid.uuid4().hex


class SemiBase(PlanBase):
    """Cà phê sữa M dùng 40 ml cà phê cốt; một mẻ cốt: 500 g cà phê ra 1.000 ml (1 ml cốt = 0,5 g cà phê)."""

    def setUp(self):
        super().setUp()
        store = self.d["store"]
        self.coffee = self.d["coffee"]
        self.cf = Ingredient.objects.create(store=store, name="Cà phê cốt", unit="ml", pack_size=1000, lead_time_days=0,
                                            kind=IngredientKind.SEMI, shelf_life_days=2)
        self.recipe = SemiRecipe.objects.create(store=store, product=self.cf, batch_output=1000, yield_measured=True)
        SemiRecipeLine.objects.create(recipe=self.recipe, ingredient=self.coffee, quantity=500)
        v2 = RecipeVersion.objects.create(item=self.d["item"])
        RecipeLine.objects.create(version=v2, size=self.d["size_m"], ingredient=self.cf, quantity=40)
        RecipeLine.objects.create(version=v2, size=self.d["size_m"], ingredient=self.milk, quantity=30)
        RecipeLine.objects.create(version=v2, option=self.d["cream"], ingredient=self.milk, quantity=15)
        v2.publish(self.owner)
        self.v2 = v2

    def sell_semi_day(self, day, cups):
        line = self.sell_day(day, cups)
        OrderLine.objects.filter(pk=line.pk).update(
            usage_per_unit={str(self.cf.pk): "40", str(self.milk.pk): "30"}, recipe_version=self.v2)
        return line


class ExplodeTests(SemiBase):
    def test_multilevel_recipe_keeps_semi_and_adds_raw(self):
        store = self.d["store"]
        sugar = Ingredient.objects.create(store=store, name="Đường", unit="g", pack_size=1000, lead_time_days=1)
        syrup = Ingredient.objects.create(store=store, name="Nước đường", unit="ml", pack_size=1600, lead_time_days=0,
                                          kind=IngredientKind.SEMI)
        foam = Ingredient.objects.create(store=store, name="Foam", unit="ml", pack_size=400, lead_time_days=0,
                                         kind=IngredientKind.SEMI)
        r = SemiRecipe.objects.create(store=store, product=syrup, batch_output=1600, yield_measured=True)
        SemiRecipeLine.objects.create(recipe=r, ingredient=sugar, quantity=1000)
        r = SemiRecipe.objects.create(store=store, product=foam, batch_output=400)
        SemiRecipeLine.objects.create(recipe=r, ingredient=self.milk, quantity=100)
        SemiRecipeLine.objects.create(recipe=r, ingredient=syrup, quantity=80)
        book = usage.RecipeBook()
        out = book.explode({foam.pk: 40.0, self.cf.pk: 40.0})
        self.assertAlmostEqual(out[foam.pk], 40.0)
        self.assertAlmostEqual(out[syrup.pk], 8.0)  # 80/400 × 40
        self.assertAlmostEqual(out[sugar.pk], 5.0)  # 8 ml × 1000/1600
        self.assertAlmostEqual(out[self.milk.pk], 10.0)
        self.assertAlmostEqual(out[self.coffee.pk], 20.0)
        self.assertEqual(set(book.via_semi({self.cf.pk: 10.0})), {self.coffee.pk})
        line = SemiRecipeLine(recipe=SemiRecipe.objects.get(product=syrup), ingredient=foam, quantity=1)
        with self.assertRaises(ValidationError):
            line.clean()  # nước đường dùng foam mà foam đã dùng nước đường: vòng lặp


class ProduceTests(SemiBase):
    def test_batch_moves_raw_once_and_sale_deducts_semi_only(self):
        result, _ = ops.produce_semi(self.owner, k := key(), self.cf.pk, "2")
        again, repeated = ops.produce_semi(self.owner, k, self.cf.pk, "2")
        self.assertTrue(repeated)
        self.assertEqual(levels(self.coffee)[0], Decimal(49000))
        self.assertEqual(levels(self.cf)[0], Decimal(2000))
        batch = SemiBatch.objects.get()
        self.assertEqual((batch.expected_output, batch.actual_output), (Decimal(2000), Decimal(2000)))
        lot = StockLot.objects.get(ingredient=self.cf)
        self.assertEqual((lot.source, lot.expiry_date), (StockLot.Source.BATCH, timezone.localdate() + timedelta(days=1)))
        self.assertEqual(set(StockMovement.objects.filter(source_type="me_btp").values_list("kind", flat=True)),
                         {StockMovement.Kind.PRODUCE})
        order, _ = services.submit_order(self.d["waiter"], key(), cart(self.d))
        line = OrderLine.objects.get(order_id=order["order_id"])
        services.complete_line(self.d["barista"], key(), line.pk, 1, 0)
        self.assertEqual(levels(self.cf)[0], Decimal(1960))
        self.assertEqual(levels(self.coffee)[0], Decimal(49000))  # không trừ cà phê lần hai
        self.assertGreater(lots.daily_usage([self.coffee.pk])[self.coffee.pk], 0)

    def test_out_of_semi_says_make_a_batch(self):
        with self.assertRaises(stock.InsufficientStock) as ctx:
            services.submit_order(self.d["waiter"], key(), cart(self.d))  # chưa làm mẻ cốt nào
        short = {s["ingredient"]: s for s in ctx.exception.shortages}
        self.assertTrue(short["Cà phê cốt"]["semi"])
        clock_in(self.d["waiter"])
        self.client.login(username=self.d["waiter"].username, password=PASSWORD)
        r = self.client.post(reverse("orders:submit"), {"operation_key": key(), "order": cart(self.d)},
                             content_type="application/json")
        self.assertEqual(r.status_code, 409)
        self.assertEqual([s["semi"] for s in r.json()["shortages"] if s["ingredient"] == "Cà phê cốt"], [True])

    def test_short_raw_writes_nothing_and_actual_yield_is_kept(self):
        with self.assertRaises(ValidationError):
            ops.produce_semi(self.owner, key(), self.cf.pk, "101")  # cần 50.500 g, còn 50.000 g
        self.assertFalse(SemiBatch.objects.exists())
        self.assertEqual(levels(self.coffee)[0], Decimal(50000))
        ops.produce_semi(self.owner, key(), self.cf.pk, "1", actual_output="950")
        self.assertEqual(levels(self.cf)[0], Decimal(950))
        with self.assertRaises(ValidationError):
            ops.produce_semi(self.owner, key(), self.coffee.pk, "1")  # nguyên liệu mua vào không có định mức mẻ

    def test_semi_cannot_be_bought(self):
        from apps.inventory.models import Supplier

        supplier = Supplier.objects.create(store=self.d["store"], name="NCC")
        with self.assertRaises(ValidationError):
            ops.create_purchase_order(self.owner, supplier.pk, self.cf.pk, 1000, self.today, operation_key=key())
        with self.assertRaises(ValidationError):
            ops.create_receipt(self.owner, key(), supplier.pk, [{"ingredient": self.cf.pk, "quantity": "1000",
                                                                 "unit_price": 0}], "tra_ngay")


class SemiDemandTests(SemiBase):
    def setUp(self):
        super().setUp()
        for j in range(1, 29):
            self.sell_semi_day(self.today - timedelta(days=j), 20)

    def test_raw_demand_goes_through_semi_and_semi_waste_counts(self):
        ops.produce_semi(self.owner, key(), self.cf.pk, "1")
        ops.record_waste(self.owner, key(), self.cf.pk, 200, "het_han")  # cốt đổ bỏ cuối ngày
        y = self.today - timedelta(days=1)
        Waste.objects.update(created_at=at(y, 21))
        data = usage.build(self.today)
        self.assertAlmostEqual(data["rows"][self.coffee.pk][y]["via_semi"], 100.0)
        self.assertAlmostEqual(data["rows"][self.cf.pk][y]["sales"], 800.0)  # 20 ly × 40 ml
        self.assertAlmostEqual(data["rows"][self.coffee.pk][y]["sales"], 400.0)  # 800 ml × 0,5 g
        # Đối soát vẫn theo lượng chụp lúc bán: cà phê không có dòng trực tiếp nên không lệch.
        self.assertAlmostEqual(data["rows"][self.coffee.pk][y]["sales_as_sold"], 0.0)
        r = usage.rates(data, self.coffee.pk)
        self.assertGreater(r["r_btp"], 0)  # 100 g cà phê đổ bỏ theo cốt hết hạn

    def test_semi_used_up_is_not_a_stockout_but_a_shortage_case_is(self):
        y = self.today - timedelta(days=1)
        with mock.patch("django.utils.timezone.now", return_value=at(y, 9)):
            ops.produce_semi(self.owner, key(), self.cf.pk, "1")
        with mock.patch("django.utils.timezone.now", return_value=at(y, 12)):
            stock.move(self.cf.pk, Decimal(-1000), kind=StockMovement.Kind.CONSUME, actor=self.owner,
                       store=self.d["store"], source_type="dong_mon")  # dùng hết mẻ giữa ngày rồi làm mẻ mới
        data = usage.build(self.today)
        self.assertFalse(data["rows"][self.cf.pk][y]["own_stockout"])
        self.assertFalse(data["rows"][self.coffee.pk][y]["indirect_block"])
        ShortageCase.objects.create(store=self.d["store"], ingredient=self.cf, day=y, source=ShortageCase.Source.CUSTOMER_SWITCH)
        data = usage.build(self.today)
        self.assertTrue(data["rows"][self.cf.pk][y]["own_stockout"])
        self.assertTrue(data["rows"][self.coffee.pk][y]["indirect_block"])  # khách bị từ chối: cà phê bán bị chặn

    def test_plan_skips_semi_and_counts_its_stock_for_raw(self):
        ops.produce_semi(self.owner, key(), self.cf.pk, "1")
        run = planning.run_full(timezone.now())
        self.assertFalse(IngredientPlan.objects.filter(ingredient=self.cf).exists())
        self.assertIn(str(self.cf.pk), run.summary["ban_thanh_pham"])
        plan = IngredientPlan.objects.get(ingredient=self.coffee, is_current=True)
        self.assertEqual(plan.result["semi_equivalent"], 500.0)
        self.assertGreater(plan.forecast["daily"][self.today.isoformat()], 300)  # nhu cầu cà phê đi qua cốt
        rows = planning.production_suggestions()
        self.assertEqual([r["ingredient"] for r in rows], [self.cf])
        self.assertIsNotNone(rows[0]["batches"])

    def test_unmeasured_yield_warns_on_raw_plan(self):
        SemiRecipe.objects.filter(pk=self.recipe.pk).update(yield_measured=False)
        fc = planning.build_forecasts(timezone.now(), ingredients=[self.coffee.pk])[self.coffee.pk]
        self.assertTrue(any("chưa cân đo" in w for w in fc["warnings"]))

    def test_production_page_and_lists(self):
        planning.run_full(timezone.now())
        self.client.login(username=self.owner.username, password=PASSWORD)
        page = self.client.get(reverse("inventory:semi"))
        self.assertContains(page, "Cà phê cốt")
        self.assertContains(page, "theo gợi ý từ dự báo bán")
        self.client.post(reverse("inventory:semi"), {"operation_key": key(), "product": self.cf.pk, "batches": "1"})
        self.assertEqual(SemiBatch.objects.count(), 1)
        self.assertNotContains(self.client.get(reverse("inventory:receipt")), "Cà phê cốt")
        self.assertRedirects(self.client.get(reverse("forecast:plan", args=[self.cf.pk])), reverse("inventory:semi"))
        self.assertContains(self.client.get(reverse("masterdata:list", args=["ban-thanh-pham"])), "Cà phê cốt")


class ImportTests(TestCase):
    def test_lam_menu_with_semi(self):
        call_command("nhap_thuc_don_lam", ban_thanh_pham=True, verbosity=0)
        cf = Ingredient.objects.get(name="Cà phê cốt")
        self.assertEqual(cf.kind, IngredientKind.SEMI)
        self.assertEqual({str(l.ingredient.name): l.quantity for l in cf.semi_recipe.lines.all()},
                         {"Cà phê bột": Decimal(500)})
        self.assertFalse(SemiRecipe.objects.get(product__name="Foam muối").yield_measured)
        lines = {l.ingredient.name: l.quantity for l in RecipeLine.objects.filter(version__item__name="Cà phê đen")}
        self.assertEqual(lines["Cà phê cốt"], Decimal(40))
        self.assertNotIn("Cà phê bột", lines)


class SemiTodayTests(SemiBase):
    def test_barista_marks_batch_done_and_owner_sees_it(self):
        """Hai 28/11: pha chế bấm Đã làm xong mẻ hôm nay; quầy nhắc khi còn chưa làm; Chủ quán thấy trên bảng điều
        khiển và nhận thông báo trên chuông."""
        from apps.core.models import Notification
        from apps.inventory.semi_today import missing_today, today_status
        from apps.reports import services as reports

        self.assertEqual(missing_today(), ["Cà phê cốt"])
        self.client.login(username=self.d["barista"].username, password=PASSWORD)
        self.assertContains(self.client.get(reverse("orders:bar")), "Làm mẻ hôm nay (còn 1)")
        page = self.client.get(reverse("inventory:semi"))
        self.assertContains(page, "Chưa làm")
        op = page.context["today_rows"][0]["operation_key"]
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse("inventory:semi"), {"operation_key": op, "product": self.cf.pk, "batches": "1"})
        row = today_status()[0]
        self.assertEqual((row["done"], row["batches"], row["last"].actor), (True, 1, self.d["barista"]))
        self.assertEqual(missing_today(), [])
        self.assertContains(self.client.get(reverse("inventory:semi")), ">Xong<")
        self.assertTrue(Notification.objects.filter(user=self.owner, title__contains="mẻ Cà phê cốt").exists())
        with mock.patch("django.utils.timezone.now", return_value=at(timezone.localdate(), 23)):
            items = reports.attention({})
        self.assertFalse([i for i in items if "Bán thành phẩm" in i["title"]])


class SemiPlanTests(SemiBase):
    def test_owner_plans_day_barista_follows_and_owner_adds_new_type(self):
        """Hai 28/11: Chủ quán thêm loại bán thành phẩm mới, đặt kế hoạch ngày nào làm mẻ nào; pha chế thấy đúng kế
        hoạch, làm đủ số mẻ mới là xong."""
        from apps.inventory.models import SemiTask
        from apps.inventory.semi_today import missing_today, today_status

        today = timezone.localdate()
        self.client.login(username=self.owner.username, password=PASSWORD)
        self.client.post(reverse("inventory:semi_types"), {"name": "Nước đường", "unit": "ml", "output": "1600",
                                                          "shelf": "3", "ing_1": self.milk.pk, "qty_1": "1000"})
        syrup = Ingredient.objects.get(name="Nước đường")
        self.assertEqual((syrup.kind, syrup.semi_recipe.batch_output), (IngredientKind.SEMI, 1600))
        url = reverse("inventory:semi_plan")
        self.client.post(url, {"ngay": f"{today:%Y-%m-%d}", "action": "add", "product": self.cf.pk, "batches": "2"})
        self.client.post(url, {"ngay": f"{today:%Y-%m-%d}", "action": "add", "product": syrup.pk, "batches": "1"})
        self.assertEqual(sorted(missing_today()), ["Cà phê cốt", "Nước đường"])
        task = SemiTask.objects.get(day=today, product=syrup)
        self.client.post(url, {"ngay": f"{today:%Y-%m-%d}", "action": "delete", "task": task.pk})
        self.assertEqual(missing_today(), ["Cà phê cốt"])
        ops.produce_semi(self.d["barista"], key(), self.cf.pk, 1)
        row = today_status()[0]
        self.assertEqual((row["done"], row["left"]), (False, 1))  # cần 2 mẻ, mới làm 1
        ops.produce_semi(self.d["barista"], key(), self.cf.pk, 1)
        self.assertEqual(missing_today(), [])
        tomorrow = today + timedelta(days=1)
        self.client.post(url, {"ngay": f"{tomorrow:%Y-%m-%d}", "action": "copy"})
        self.assertEqual(SemiTask.objects.get(day=tomorrow).batches, 2)
        self.assertContains(self.client.get(url + f"?ngay={today:%Y-%m-%d}"), "Đã làm")
        yesterday = today - timedelta(days=1)
        self.client.post(url, {"ngay": f"{yesterday:%Y-%m-%d}", "action": "add", "product": self.cf.pk})
        self.assertFalse(SemiTask.objects.filter(day=yesterday).exists())  # ngày đã qua không sửa
        self.client.force_login(self.d["barista"])
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.client.get(reverse("inventory:semi")).status_code, 200)


class CupsCheckTests(SemiBase):
    def test_both_branches_compared_and_big_gap_flagged(self):
        """Đánh giá mô hình 28/11: số ly mỗi ngày của nhánh nhân sự và nhánh mua hàng hiện cạnh nhau, chênh lớn bị đánh dấu."""
        from apps.forecast.models import PlanRun

        today = timezone.localdate()
        run = PlanRun.objects.create(kind=PlanRun.Kind.FULL, started_at=timezone.now(),
                                     summary={"tong": {"method": "WMA", "daily": {today.isoformat(): 120.0,
                                                                                 (today + timedelta(days=1)).isoformat(): 100.0}}})
        from types import SimpleNamespace

        rel = SimpleNamespace(issued_at=timezone.now())
        with mock.patch("apps.forecast.services.latest_release", return_value=rel), \
                mock.patch("apps.schedule.services._daily_cups", side_effect=lambda d, t: (100.0, "thử")):
            data = planning.cups_check(today, days=2)
        self.assertEqual([(r["staff"], r["stock"], r["flag"]) for r in data["rows"]], [(100.0, 120.0, True), (100.0, 100.0, False)])
        self.assertEqual(data["flagged"], 1)
        self.assertTrue(run.pk)
        self.client.login(username=self.owner.username, password=PASSWORD)
        self.assertContains(self.client.get(reverse("forecast:overview")), "Đối chiếu số ly giữa nhân sự và mua hàng")


class ErrorCostTests(TestCase):
    def test_under_forecast_weighs_more_than_over(self):
        """Đánh giá mô hình 28/11: MAE coi thiếu 10 như thừa 10; khi chọn cách tính cho mua hàng, thiếu nặng gấp đôi."""
        from apps.forecast import methods

        under = [10.0] * 8  # thực > dự báo: dự báo thiếu
        over = [-12.0] * 8  # dự báo thừa
        self.assertLess(methods.error_cost(under, 1.0), methods.error_cost(over, 1.0))  # theo MAE: chọn cách dự báo thiếu
        self.assertGreater(methods.error_cost(under, 2.0), methods.error_cost(over, 2.0))  # thiếu ×2: chọn cách dự báo thừa
        self.assertEqual(methods.error_cost([], 2.0), None)
