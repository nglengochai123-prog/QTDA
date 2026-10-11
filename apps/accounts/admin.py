from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import Group

from apps.audit.admin_mixins import AuditedAdminMixin

from .permissions import OwnerOnlyAdminMixin
from .models import User

admin.site.unregister(Group)  # Dùng 5 vai trò cố định thay cho nhóm quyền tự do.


@admin.register(User)
class UserAdmin(OwnerOnlyAdminMixin, AuditedAdminMixin, BaseUserAdmin):
    list_display = ("username", "first_name", "last_name", "role", "is_active", "locked_until")
    list_filter = ("role", "is_active")
    readonly_fields = ("last_login", "date_joined", "failed_login_count")
    fieldsets = (
        (None, {"fields": ("username", "password")}),
        ("Thông tin", {"fields": ("first_name", "last_name", "email")}),
        ("Vai trò và trạng thái", {"fields": ("role", "store", "is_active", "locked_until", "failed_login_count")}),
        ("Mốc thời gian", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (None, {"fields": ("username", "password1", "password2")}),
        ("Vai trò", {"fields": ("role", "first_name", "last_name")}),
    )
    actions = ["unlock_accounts"]

    @admin.action(description="Mở tạm khóa do sai mật khẩu")
    def unlock_accounts(self, request, queryset):
        for user in queryset:
            user.reset_failed_logins()
        self.message_user(request, f"Đã mở tạm khóa {queryset.count()} tài khoản.", messages.SUCCESS)
