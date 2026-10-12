"""Nhập thực đơn và công thức thật của quán (apps/catalog/thuc_don_lam.py). Chạy lại không tạo trùng."""

from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.catalog import thuc_don_lam as data
from apps.catalog.models import ItemSize, MenuGroup, MenuItem, Option, OptionGroup
from apps.core.models import Store
from apps.inventory.models import Ingredient, RecipeLine, RecipeVersion


class Command(BaseCommand):
    help = "Nhập thực đơn, nguyên liệu và định mức thật của LAM Coffee. Món đã có cùng tên thì bỏ qua."

    @transaction.atomic
    def handle(self, *args, **options):
        store = Store.get_default()
        ingredients, new_ing = {}, 0
        for name, unit in data.INGREDIENTS.items():
            ing = Ingredient.objects.filter(store=store, name=name).first()
            if ing is None:
                ing = Ingredient.objects.create(store=store, name=name, unit=unit, pack_size=Decimal(1),
                                                lead_time_days=1)
                new_ing += 1
            elif ing.unit != unit:
                self.stderr.write(f"Nguyên liệu {name} đã có với đơn vị {ing.unit}, công thức dùng {unit}.")
            ingredients[name] = ing

        opts = {}
        for group_name, names in data.OPTION_GROUPS.items():
            group, _ = OptionGroup.objects.get_or_create(store=store, name=group_name,
                                                         defaults={"is_required": True})
            for i, n in enumerate(names):
                opts[(group_name, n)] = Option.objects.get_or_create(group=group, name=n,
                                                                     defaults={"sort_order": i})[0]

        groups = {}
        for i, name in enumerate(data.GROUPS):
            groups[name] = MenuGroup.objects.get_or_create(store=store, name=name, defaults={"sort_order": i + 1})[0]

        created, skipped = 0, []
        for order, (group, name, _text, lines, variants, _notes) in enumerate(data.ITEMS, start=1):
            if MenuItem.objects.filter(store=store, name=name).exists():
                skipped.append(name)
                continue
            item = MenuItem.objects.create(store=store, group=groups[group], name=name, sort_order=order)
            size = ItemSize.objects.create(item=item, name="Chuẩn", price=0)
            version = RecipeVersion.objects.create(item=item, note="Công thức Chủ quán gửi 12/10/2026")
            for ing, qty in data.expand(lines).items():
                RecipeLine.objects.create(version=version, size=size, ingredient=ingredients[ing], quantity=qty)
            for group_name, choices in variants.items():
                item.option_groups.add(opts[(group_name, next(iter(choices)))].group)
                for choice, extra in choices.items():
                    for ing, qty in data.expand(extra).items():
                        RecipeLine.objects.create(version=version, option=opts[(group_name, choice)],
                                                  ingredient=ingredients[ing], quantity=qty)
            created += 1

        self.stdout.write(self.style.SUCCESS(
            f"Đã tạo {created} món (Đang soạn, định mức bản nháp), {new_ing} nguyên liệu mới."))
        if skipped:
            self.stdout.write("Bỏ qua vì đã có món cùng tên: " + ", ".join(skipped))
