from django.contrib import admin

from apps.accounts.permissions import OwnerOnlyAdminMixin
from apps.audit.admin_mixins import AuditedAdminMixin

from .models import Store


@admin.register(Store)
class StoreAdmin(OwnerOnlyAdminMixin, AuditedAdminMixin, admin.ModelAdmin):
    list_display = ("code", "name", "is_active")
    search_fields = ("code", "name")
