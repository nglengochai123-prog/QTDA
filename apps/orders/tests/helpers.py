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


def confirm_opening(shift, amount=0):
    """Ghi tiền đầu ca cho ca thử: từ 28/11/2026 thu tiền mặt cần ca đã xác nhận tiền đầu ca (QA BUG-08).
    Ghi thẳng bút toán như thu ngân đã làm ở màn Ca của tôi; test riêng về tiền đầu ca thì không gọi hàm này."""
    from apps.shifts.models import CashEntry

    return CashEntry.objects.create(store=shift.store, shift=shift, kind=CashEntry.Kind.OPENING, amount=amount,
                                    actor=shift.approver or shift.payment_authorizer or User.objects.order_by("pk").first(),
                                    operation_key=f"dau-ca-thu-{shift.pk}")


def clock_in(*users, role=None):
    """Cho nhân viên vào ca (màn Tạo đơn chặn người chưa vào ca, quyết định 28/11/2026 – QA BUG-09)."""
    from django.utils import timezone

    from apps.staff.models import Attendance

    for user in users:
        Attendance.objects.create(store=Store.get_default(), user=user, role=role or user.role,
                                  clock_in=timezone.now() - timezone.timedelta(minutes=5))


def open_shift(owner, hours_before=1, hours_after=6):
    """Một ca đang mở quanh lúc này: màn Tạo đơn chỉ nhận đơn khi có ca (Hai, 28/11/2026)."""
    from django.utils import timezone

    from apps.shifts.models import Shift

    now = timezone.now()
    return Shift.objects.create(store=Store.get_default(), name="Ca thử", starts_at=now - timezone.timedelta(hours=hours_before),
                                ends_at=now + timezone.timedelta(hours=hours_after), approver=owner)
