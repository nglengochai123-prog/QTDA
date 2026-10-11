from django.contrib import admin

from apps.accounts.permissions import Cap, OwnerOnlyAdminMixin

from .models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(OwnerOnlyAdminMixin, admin.ModelAdmin):
    """Tra cứu nhật ký (AC-115): chỉ xem, lọc; không có thêm, sửa, xóa."""

    owner_capability = Cap.AUDIT_LOG
    list_display = ("created_at", "actor_label", "action", "object_type", "object_repr", "reason")
    list_filter = ("action", ("created_at", admin.DateFieldListFilter), "object_type")
    search_fields = ("actor_label", "object_repr", "reason", "object_id")
    date_hierarchy = "created_at"
    readonly_fields = [f.name for f in AuditLog._meta.fields]
    actions = None

    def has_add_permission(self, request, *args):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
