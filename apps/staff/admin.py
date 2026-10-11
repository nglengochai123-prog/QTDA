from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

from apps.accounts.permissions import OwnerOnlyAdminMixin
from apps.audit.admin_mixins import AuditedAdminMixin

from .forms import EmployeeForm
from .models import Employee


@admin.register(Employee)
class EmployeeAdmin(OwnerOnlyAdminMixin, AuditedAdminMixin, admin.ModelAdmin):
    form = EmployeeForm
    list_display = ("full_name", "phone", "role_labels", "status", "account_link")
    list_filter = ("status",)
    search_fields = ("full_name", "phone")

    def get_fields(self, request, obj=None):
        fields = ["full_name", "phone", "roles", "hourly_wage", "status"]
        return fields + (["username"] if obj is None else [])

    @admin.display(description="Tài khoản")
    def account_link(self, obj):
        url = reverse("admin:accounts_user_change", args=[obj.user_id])
        return format_html('<a href="{}">{}</a>', url, obj.user.username)

    def save_model(self, request, obj, form, change):
        if not change:
            obj.attach_new_account(form.cleaned_data.get("username"))
        super().save_model(request, obj, form, change)
