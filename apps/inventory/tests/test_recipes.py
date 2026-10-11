from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import Role, User
from apps.audit.models import Action, AuditLog
from apps.catalog.models import ItemSize, MenuGroup, MenuItem, Option, OptionGroup
from apps.core.models import Store
from apps.inventory.models import Ingredient, RecipeLine, RecipeVersion, Supplier
from apps.inventory.services import ingredient_usage, recipe_gaps


class Fixture(TestCase):
    def setUp(self):
        self.store = Store.get_default()
        self.owner = User.objects.create_user("chuquan", password="matkhau-thu-123", role=Role.CHU_QUAN)
        self.supplier = Supplier.objects.create(store=self.store, name="Nhà cung cấp A")
        self.coffee = Ingredient.objects.create(store=self.store, name="Cà phê", unit="g", pack_size=1000,
                                                lead_time_days=2)
        self.condensed = Ingredient.objects.create(store=self.store, name="Sữa đặc", unit="ml", pack_size=380,
                                                   lead_time_days=2)
        self.group = MenuGroup.objects.create(store=self.store, name="Pha phin")
        self.item = MenuItem.objects.create(store=self.store, group=self.group, name="Cà phê sữa")
        self.m = ItemSize.objects.create(item=self.item, name="M", price=25000)

    def publish_v1(self):
        v1 = RecipeVersion.objects.create(item=self.item)
        RecipeLine.objects.create(version=v1, size=self.m, ingredient=self.coffee, quantity=20)
        RecipeLine.objects.create(version=v1, size=self.m, ingredient=self.condensed, quantity=30)
        v1.publish(self.owner)
        return v1


class IngredientTests(Fixture):
    def test_ingredient_requires_lead_time(self):
        # AC-44
        milk = Ingredient(store=self.store, name="Sữa tươi", unit="ml", pack_size=1000, pack_label="hộp",
                          main_supplier=self.supplier, shelf_life_days=7, storage_capacity=20000,
                          is_critical=True)
        with self.assertRaises(ValidationError) as ctx:
            milk.full_clean()
        self.assertIn("lead_time_days", ctx.exception.message_dict)
        milk.lead_time_days = 2
        milk.full_clean()
        milk.save()
        self.assertTrue(milk.safety_stock_is_provisional)


class RecipeVersionTests(Fixture):
    def test_versions_and_current(self):
        # AC-46: sửa định mức tạo phiên bản mới; ly đã nhận giữ bản cũ.
        v1 = self.publish_v1()
        draft = v1.copy_as_draft()
        self.assertEqual(draft.number, 2)
        line = draft.lines.get(ingredient=self.coffee)
        line.quantity = 25
        line.save()
        draft.publish(self.owner)
        self.assertEqual(RecipeVersion.objects.current_for(self.item), draft)
        self.assertEqual(ingredient_usage(v1, self.m)[self.coffee.pk], Decimal("20"))
        self.assertEqual(ingredient_usage(draft, self.m)[self.coffee.pk], Decimal("25"))
        self.assertEqual(ingredient_usage(draft, self.m)[self.condensed.pk], Decimal("30"))

    def test_published_version_is_immutable(self):
        v1 = self.publish_v1()
        line = v1.lines.first()
        line.quantity = 99
        with self.assertRaises(ValidationError):
            line.save()
        with self.assertRaises(ValidationError):
            line.delete()
        with self.assertRaises(ValidationError):
            v1.delete()
        v1.note = "đổi"
        with self.assertRaises(ValidationError):
            v1.save()

    def test_only_one_draft_per_item(self):
        RecipeVersion.objects.create(item=self.item)
        with self.assertRaises(Exception):
            RecipeVersion.objects.create(item=self.item)

    def test_cannot_publish_empty_version(self):
        with self.assertRaises(ValidationError):
            RecipeVersion.objects.create(item=self.item).publish(self.owner)

    def test_line_must_target_size_or_option_of_item(self):
        v = RecipeVersion.objects.create(item=self.item)
        with self.assertRaises(ValidationError):
            RecipeLine(version=v, ingredient=self.coffee, quantity=1).full_clean()
        other = MenuItem.objects.create(store=self.store, group=self.group, name="Bạc xỉu")
        other_size = ItemSize.objects.create(item=other, name="M", price=29000)
        with self.assertRaises(ValidationError):
            RecipeLine(version=v, ingredient=self.coffee, size=other_size, quantity=1).full_clean()


class OpenForSaleTests(Fixture):
    def test_blocked_until_every_size_has_recipe(self):
        # AC-47: có M, thiếu L thì không mở bán được và báo thiếu size L.
        ItemSize.objects.create(item=self.item, name="L", price=29000)
        self.publish_v1()
        self.item.status = MenuItem.Status.ON_SALE
        with self.assertRaises(ValidationError) as ctx:
            self.item.full_clean()
        self.assertIn("kích cỡ L", str(ctx.exception))
        self.assertNotIn(self.item, MenuItem.objects.sellable())

    def test_option_needs_recipe_or_no_ingredient_flag(self):
        self.publish_v1()
        toppings = OptionGroup.objects.create(store=self.store, name="Topping", selection="multiple")
        pearl = Option.objects.create(group=toppings, name="Trân châu", extra_price=5000)
        ice = OptionGroup.objects.create(store=self.store, name="Đá")
        Option.objects.create(group=ice, name="Ít đá", no_ingredients=True)
        self.item.option_groups.add(toppings, ice)
        self.assertEqual(len(recipe_gaps(self.item)), 1)
        self.assertIn("Trân châu", recipe_gaps(self.item)[0])
        pearl.no_ingredients = True
        pearl.save()
        self.assertEqual(recipe_gaps(self.item), [])

    def test_complete_item_can_go_on_sale(self):
        self.publish_v1()
        self.item.status = MenuItem.Status.ON_SALE
        self.item.full_clean()
        self.item.save()
        self.assertIn(self.item, MenuItem.objects.sellable())

    def test_no_ingredient_item_needs_no_recipe(self):
        toy = MenuItem.objects.create(store=self.store, group=self.group, name="Tô tượng", no_ingredients=True)
        ItemSize.objects.create(item=toy, name="Chuẩn", price=50000)
        toy.status = MenuItem.Status.ON_SALE
        toy.full_clean()

    def test_item_without_sizes_cannot_go_on_sale(self):
        empty = MenuItem.objects.create(store=self.store, group=self.group, name="Món mới", no_ingredients=True,
                                        status=MenuItem.Status.ON_SALE)
        with self.assertRaises(ValidationError):
            empty.full_clean()


class RecipeAdminTests(Fixture):
    def test_publish_and_copy_through_admin_are_logged(self):
        self.client.force_login(self.owner)
        draft = RecipeVersion.objects.create(item=self.item)
        RecipeLine.objects.create(version=draft, size=self.m, ingredient=self.coffee, quantity=20)
        response = self.client.post(reverse("admin:inventory_recipeversion_publish", args=[draft.pk]))
        self.assertEqual(response.status_code, 302)
        draft.refresh_from_db()
        self.assertTrue(draft.is_published)
        self.assertTrue(AuditLog.objects.filter(action=Action.PUBLISH_RECIPE, object_id=str(draft.pk)).exists())
        # Bản đã áp dụng chỉ xem được, không có nút lưu.
        page = self.client.get(reverse("admin:inventory_recipeversion_change", args=[draft.pk]))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Tạo bản nháp mới từ bản này")
        self.assertNotContains(page, 'name="_save"')
        response = self.client.post(reverse("admin:inventory_recipeversion_copy", args=[draft.pk]))
        self.assertEqual(RecipeVersion.objects.filter(item=self.item).count(), 2)

    def test_non_owner_cannot_publish(self):
        barista = User.objects.create_user("phache", password="matkhau-thu-123", role=Role.PHA_CHE)
        draft = RecipeVersion.objects.create(item=self.item)
        RecipeLine.objects.create(version=draft, size=self.m, ingredient=self.coffee, quantity=20)
        self.client.force_login(barista)
        self.client.post(reverse("admin:inventory_recipeversion_publish", args=[draft.pk]))
        draft.refresh_from_db()
        self.assertFalse(draft.is_published)
