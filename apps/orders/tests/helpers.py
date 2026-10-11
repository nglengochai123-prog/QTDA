from decimal import Decimal

from apps.accounts.models import Role, User
from apps.catalog.models import ItemSize, MenuGroup, MenuItem, Option, OptionGroup, Table
from apps.core.models import Store
from apps.inventory import stock
from apps.inventory.models import Ingredient, RecipeLine, RecipeVersion

PASSWORD = "matkhau-thu-123"


def build_menu(coffee_opening=2000, milk_opening=1000):
    """Cà phê sữa M: 20 g cà phê + 30 ml sữa đặc (AC-46, AC-48). Topping Kem muối: +15 ml sữa đặc."""
    data = {}
    store = Store.get_default()
    data["owner"] = User.objects.create_user("chuquan", password=PASSWORD, role=Role.CHU_QUAN)
    data["waiter"] = User.objects.create_user("phucvu", password=PASSWORD, role=Role.PHUC_VU)
    data["barista"] = User.objects.create_user("phache", password=PASSWORD, role=Role.PHA_CHE)
    data["coffee"] = Ingredient.objects.create(store=store, name="Cà phê", unit="g", pack_size=1000, lead_time_days=2)
    data["milk"] = Ingredient.objects.create(store=store, name="Sữa đặc", unit="ml", pack_size=380, lead_time_days=2)
    group = MenuGroup.objects.create(store=store, name="Pha phin")
    item = MenuItem.objects.create(store=store, group=group, name="Cà phê sữa")
    size_m = ItemSize.objects.create(item=item, name="M", price=25000)
    toppings = OptionGroup.objects.create(store=store, name="Topping", selection="multiple")
    cream = Option.objects.create(group=toppings, name="Kem muối", extra_price=8000)
    ice = OptionGroup.objects.create(store=store, name="Đá")
    less_ice = Option.objects.create(group=ice, name="Ít đá", no_ingredients=True)
    item.option_groups.add(toppings, ice)
    version = RecipeVersion.objects.create(item=item)
    RecipeLine.objects.create(version=version, size=size_m, ingredient=data["coffee"], quantity=20)
    RecipeLine.objects.create(version=version, size=size_m, ingredient=data["milk"], quantity=30)
    RecipeLine.objects.create(version=version, option=cream, ingredient=data["milk"], quantity=15)
    version.publish(data["owner"])
    item.status = MenuItem.Status.ON_SALE
    item.full_clean()
    item.save()
    data.update(store=store, item=item, size_m=size_m, cream=cream, less_ice=less_ice, v1=version,
                table=Table.objects.create(store=store, code="5"))
    if coffee_opening is not None:
        stock.record_opening(data["coffee"], coffee_opening, data["owner"])
    if milk_opening is not None:
        stock.record_opening(data["milk"], milk_opening, data["owner"])
    return data


def cart(data, quantity=1, options=(), note=""):
    return {"table": data["table"].pk, "note": "",
            "lines": [{"item": data["item"].pk, "size": data["size_m"].pk, "options": [o.pk for o in options],
                       "quantity": quantity, "note": note}]}


def levels(ingredient):
    ingredient.stock.refresh_from_db()
    s = ingredient.stock
    return s.physical, s.reserved, s.physical - s.reserved


def D(value):
    return Decimal(str(value))
