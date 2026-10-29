from django.contrib import admin
from django.contrib.humanize.templatetags.humanize import intcomma

from apps.accounts.permissions import AppManagedAdminMixin, AppManagedInlineMixin

from .models import ItemSize, MenuGroup, MenuItem, Option, OptionGroup, Table


class CatalogAdmin(AppManagedAdminMixin, admin.ModelAdmin):
    exclude = ("store",)


@admin.register(Table)
class TableAdmin(CatalogAdmin):
    app_resource = "ban"
    list_display = ("code", "area", "seats", "is_active")
    list_filter = ("area", "is_active")


@admin.register(MenuGroup)
class MenuGroupAdmin(CatalogAdmin):
    app_resource = "nhom-mon"
    list_display = ("name", "load_factor", "is_active", "sort_order")


class OptionInline(AppManagedInlineMixin, admin.TabularInline):
    model = Option
    extra = 1
    fields = ("name", "extra_price", "no_ingredients", "is_active", "sort_order")


@admin.register(OptionGroup)
class OptionGroupAdmin(CatalogAdmin):
    app_resource = "tuy-chon"
    list_display = ("name", "selection", "is_required")
    inlines = [OptionInline]


class ItemSizeInline(AppManagedInlineMixin, admin.TabularInline):
    model = ItemSize
    extra = 1
    fields = ("name", "price", "is_active", "sort_order")


@admin.register(MenuItem)
class MenuItemAdmin(CatalogAdmin):
    app_resource = "mon"
    list_display = ("name", "group", "status", "price_list", "sale_check")
    list_filter = ("status", "group")
    search_fields = ("name",)
    filter_horizontal = ("option_groups",)
    inlines = [ItemSizeInline]

    @admin.display(description="Giá")
    def price_list(self, obj):
        return " · ".join(f"{s.name} {intcomma(s.price)} đ" for s in obj.active_sizes())

    @admin.display(description="Điều kiện mở bán")
    def sale_check(self, obj):
        blockers = obj.sale_blockers()
        return "Đủ" if not blockers else "Thiếu: " + "; ".join(blockers)
