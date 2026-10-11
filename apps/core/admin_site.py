from django.contrib import admin


class OwnerAdminSite(admin.AdminSite):
    """Trang quản trị dữ liệu nền: chỉ Chủ quán (kiểm tra theo vai trò, không chỉ is_staff)."""

    site_header = "LAM Coffee · Dữ liệu nền"
    site_title = "LAM Coffee"
    index_title = "Dữ liệu nền"

    def has_permission(self, request):
        from apps.accounts.permissions import Cap, user_can

        return request.user.is_active and user_can(request.user, Cap.MASTER_DATA)
