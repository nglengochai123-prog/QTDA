from django.contrib import admin

from apps.accounts.permissions import OwnerOnlyAdminMixin

from .models import Order, OrderLine


class OrderLineInline(admin.TabularInline):
    model = OrderLine
    fields = ("position", "item_name", "size_name", "quantity", "done_quantity", "unit_price", "recipe_version",
              "status", "note")
    readonly_fields = fields
    extra = 0
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_view_permission(self, request, obj=None):
        return True


@admin.register(Order)
class OrderAdmin(OwnerOnlyAdminMixin, admin.ModelAdmin):
    """Tra cứu đơn; đơn đã gửi bị khóa nên không sửa hay xóa ở đây."""

    list_display = ("code", "table", "status", "total", "created_by", "created_at")
    list_filter = ("status",)
    search_fields = ("code",)
    readonly_fields = ("code", "table", "status", "note", "created_by", "operation_key", "total", "store")
    inlines = [OrderLineInline]

    def has_add_permission(self, request, *args):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_view_permission(self, request, obj=None):
        return self._owner(request)
