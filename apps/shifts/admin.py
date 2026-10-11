from django.contrib import admin

from apps.accounts.permissions import OwnerOnlyAdminMixin
from apps.audit.admin_mixins import AuditedAdminMixin

from .models import Shift


@admin.register(Shift)
class ShiftAdmin(OwnerOnlyAdminMixin, AuditedAdminMixin, admin.ModelAdmin):
    list_display = ("name", "starts_at", "ends_at", "approver", "backup_approver", "payment_authorizer",
                    "status", "missing")
    list_filter = ("status",)
    exclude = ("store",)

    @admin.display(description="Còn thiếu")
    def missing(self, obj):
        return ", ".join(obj.missing_roles) or "Đủ"

    def save_model(self, request, obj, form, change):
        if obj.store_id is None:
            obj.store = request.user.store
        super().save_model(request, obj, form, change)
