from django.contrib import admin

from apps.accounts.permissions import AppManagedAdminMixin, OwnerOnlyAdminMixin

from .models import AdjustmentReason, Order, OrderLine


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


@admin.register(AdjustmentReason)
class AdjustmentReasonAdmin(AppManagedAdminMixin, admin.ModelAdmin):
    """Chủ quán sửa danh mục lý do điều chỉnh ở mục Dữ liệu nền; lý do đã dùng thì ngừng dùng thay vì xóa (BRU-08)."""

    app_resource = "ly-do"
    list_display = ("name", "sort_order", "is_active")
    exclude = ("store",)
