"""Tạo dữ liệu MẪU để chạy thử trên máy cá nhân. Không phải thực đơn hay giá thật của quán."""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.accounts.models import Role, User
from apps.catalog.models import ItemSize, MenuGroup, MenuItem, Option, OptionGroup, Table
from apps.core.models import Store
from apps.inventory import stock
from apps.inventory.models import Ingredient, RecipeLine, RecipeVersion, StockMovement

PASSWORD = "demo-lam-2026"


class Command(BaseCommand):
    help = "Tạo dữ liệu mẫu (bàn, món, định mức, tồn đầu kỳ, tài khoản demo) để chạy thử. Chỉ dùng trên máy cá nhân."

    @transaction.atomic
    def handle(self, *args, **options):
        if MenuItem.objects.exists():
            raise CommandError("Đã có món trong cơ sở dữ liệu; lệnh này chỉ chạy trên cơ sở dữ liệu trống.")
        store = Store.get_default()
        accounts = {
            "demo_chuquan": (Role.CHU_QUAN, "Trần Thị", "Lâm"),
            "demo_phucvu": (Role.PHUC_VU, "Nguyễn Ngọc", "Hà"),
            "demo_phache": (Role.PHA_CHE, "Lê Minh", "Tuấn"),
            "demo_thungan": (Role.THU_NGAN, "Võ Quốc", "Bảo"),
        }
        for username, (role, first, last) in accounts.items():
            user, _ = User.objects.get_or_create(username=username)
            user.role, user.first_name, user.last_name = role, first, last
            user.set_password(PASSWORD)
            user.save()
        owner = User.objects.get(username="demo_chuquan")

        for n in range(1, 13):
            Table.objects.create(store=store, code=str(n), area="Trong nhà" if n <= 8 else "Sân vườn", sort_order=n)

        from datetime import timedelta

        from django.utils import timezone

        today = timezone.localdate()

        def ing(name, unit, pack, opening, critical=False, shelf=None, opening_expiry=None, rule=""):
            """shelf: hạn dùng (ngày) của hàng chưa mở; opening_expiry: số ngày tới hạn của lô tồn đầu kỳ."""
            i = Ingredient.objects.create(store=store, name=name, unit=unit, pack_size=pack, lead_time_days=2,
                                          safety_stock=pack, is_critical=critical, shelf_life_days=shelf,
                                          issue_rule=rule)
            stock.record_opening(i, opening, owner, "Dữ liệu mẫu",
                                 expiry_date=today + timedelta(days=opening_expiry) if opening_expiry else None)
            return i

        # Hạn dùng mẫu theo loại hàng: sữa tươi và kem tươi ngắn ngày (xuất FEFO), hàng khô dài ngày (vẫn FEFO vì có
        # hạn in trên bao bì), ly nhựa không có hạn (LIFO: thùng mới chồng lên trên, lấy thùng trên cùng).
        coffee = ing("Cà phê rang xay", "g", 1000, 3000, critical=True, shelf=60, opening_expiry=40)
        condensed = ing("Sữa đặc", "ml", 380, 2000, critical=True, shelf=180, opening_expiry=120)
        fresh_milk = ing("Sữa tươi", "ml", 1000, 3000, critical=True, shelf=7, opening_expiry=4)
        tea = ing("Trà đen", "g", 500, 800, shelf=365, opening_expiry=18)
        peach = ing("Đào ngâm", "g", 820, 1200, shelf=365, opening_expiry=25)
        matcha = ing("Bột matcha", "g", 100, 60, critical=True, shelf=180, opening_expiry=90)
        pearl = ing("Trân châu", "g", 1000, 1500, shelf=180, opening_expiry=100)
        salted_cream = ing("Kem muối", "ml", 500, 600, shelf=5, opening_expiry=3)
        cup = ing("Ly nhựa", "cai", 50, 300, rule="lifo")

        sugar = OptionGroup.objects.create(store=store, name="Đường")
        for name in ("Bình thường", "Ít đường", "Không đường"):
            Option.objects.create(group=sugar, name=name, no_ingredients=True)
        ice = OptionGroup.objects.create(store=store, name="Đá")
        for name in ("Bình thường", "Ít đá", "Không đá"):
            Option.objects.create(group=ice, name=name, no_ingredients=True)
        topping = OptionGroup.objects.create(store=store, name="Topping", selection=OptionGroup.Selection.MULTIPLE)
        opt_pearl = Option.objects.create(group=topping, name="Trân châu", extra_price=6000)
        opt_cream = Option.objects.create(group=topping, name="Kem muối", extra_price=8000)

        coffee_group = MenuGroup.objects.create(store=store, name="Cà phê", sort_order=1)
        tea_group = MenuGroup.objects.create(store=store, name="Trà", sort_order=2)
        other_group = MenuGroup.objects.create(store=store, name="Đá xay và khác", sort_order=3)

        def item(group, name, sizes, recipe, groups=(sugar, ice), toppings=True):
            menu_item = MenuItem.objects.create(store=store, group=group, name=name)
            menu_item.option_groups.add(*groups, *([topping] if toppings else []))
            created = {n: ItemSize.objects.create(item=menu_item, name=n, price=p, sort_order=i)
                       for i, (n, p) in enumerate(sizes)}
            version = RecipeVersion.objects.create(item=menu_item, note="Dữ liệu mẫu")
            for size_name, lines in recipe.items():
                for ingredient, qty in lines:
                    RecipeLine.objects.create(version=version, size=created[size_name], ingredient=ingredient,
                                              quantity=qty)
                RecipeLine.objects.create(version=version, size=created[size_name], ingredient=cup, quantity=1)
            if toppings:
                RecipeLine.objects.create(version=version, option=opt_pearl, ingredient=pearl, quantity=40)
                RecipeLine.objects.create(version=version, option=opt_cream, ingredient=salted_cream, quantity=30)
            version.publish(owner)
            menu_item.status = MenuItem.Status.ON_SALE
            menu_item.full_clean()
            menu_item.save()

        item(coffee_group, "Cà phê đen", [("M", 22000), ("L", 27000)],
             {"M": [(coffee, 20)], "L": [(coffee, 28)]})
        item(coffee_group, "Cà phê sữa", [("M", 25000), ("L", 30000)],
             {"M": [(coffee, 20), (condensed, 30)], "L": [(coffee, 28), (condensed, 40)]})
        item(coffee_group, "Bạc xỉu", [("M", 29000), ("L", 34000)],
             {"M": [(coffee, 12), (condensed, 25), (fresh_milk, 80)], "L": [(coffee, 16), (condensed, 30), (fresh_milk, 110)]})
        item(tea_group, "Trà đào", [("M", 35000), ("L", 40000)],
             {"M": [(tea, 6), (peach, 60)], "L": [(tea, 8), (peach, 80)]})
        item(tea_group, "Trà sữa", [("M", 32000), ("L", 37000)],
             {"M": [(tea, 6), (fresh_milk, 100)], "L": [(tea, 8), (fresh_milk, 130)]})
        item(coffee_group, "Cà phê muối", [("M", 32000), ("L", 37000)],
             {"M": [(coffee, 20), (condensed, 20), (salted_cream, 40)], "L": [(coffee, 26), (condensed, 25), (salted_cream, 50)]})
        item(coffee_group, "Latte", [("M", 39000), ("L", 44000)],
             {"M": [(coffee, 18), (fresh_milk, 160)], "L": [(coffee, 24), (fresh_milk, 210)]})
        item(tea_group, "Trà sữa trân châu", [("M", 38000), ("L", 43000)],
             {"M": [(tea, 6), (fresh_milk, 100), (pearl, 50)], "L": [(tea, 8), (fresh_milk, 130), (pearl, 60)]})
        item(other_group, "Matcha đá xay", [("M", 45000)], {"M": [(matcha, 8), (fresh_milk, 150)]}, toppings=False)
        item(other_group, "Matcha latte", [("M", 42000), ("L", 47000)],
             {"M": [(matcha, 5), (fresh_milk, 180)], "L": [(matcha, 7), (fresh_milk, 230)]}, toppings=False)

        from apps.shifts.models import Shift

        start = timezone.localtime().replace(hour=6, minute=0, second=0, microsecond=0)
        Shift.objects.create(store=store, name="Ca mẫu cả ngày", starts_at=start, ends_at=start + timedelta(hours=18),
                             approver=User.objects.get(username="demo_chuquan"),
                             payment_authorizer=User.objects.get(username="demo_thungan"))

        self.stdout.write(self.style.WARNING(
            "Đã tạo DỮ LIỆU MẪU (không phải thực đơn, giá hay tồn kho thật). "
            f"Tài khoản demo_* mật khẩu {PASSWORD}. {StockMovement.objects.count()} dòng tồn đầu kỳ."))
