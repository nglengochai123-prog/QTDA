from django.contrib.auth.decorators import login_required
from django.db import connection
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET


@login_required
def home(request):
    """Trang đầu sau khi đăng nhập. Mỗi vai trò sẽ có màn hình riêng ở các phần sau."""
    from apps.accounts.permissions import Cap, user_can

    context = {}
    if user_can(request.user, Cap.MASTER_DATA):
        from django.urls import reverse

        from apps.catalog.models import MenuItem, Table
        from apps.inventory.models import Ingredient, RecipeVersion
        from apps.staff.models import Employee

        drafts = MenuItem.objects.filter(status=MenuItem.Status.DRAFT).count()
        context["master_data"] = [
            ("Hồ sơ nhân viên", reverse("admin:staff_employee_changelist"),
             f"{Employee.objects.filter(status='dang_lam').count()} đang làm", False),
            ("Bàn", reverse("admin:catalog_table_changelist"),
             f"{Table.objects.filter(is_active=True).count()} bàn", False),
            ("Món, kích cỡ và giá", reverse("admin:catalog_menuitem_changelist"),
             f"{MenuItem.objects.sellable().count()} đang bán"
             + (f", {drafts} đang soạn" if drafts else ""), bool(drafts)),
            ("Nhóm tùy chọn", reverse("admin:catalog_optiongroup_changelist"), "", False),
            ("Nguyên vật liệu", reverse("admin:inventory_ingredient_changelist"),
             f"{Ingredient.objects.filter(is_active=True).count()} loại", False),
            ("Định mức món", reverse("admin:inventory_recipeversion_changelist"),
             f"{RecipeVersion.objects.filter(status='nhap').count()} bản nháp", False),
            ("Nhật ký thao tác", reverse("admin:audit_auditlog_changelist"), "", False),
        ]
    context["can_dashboard"] = user_can(request.user, Cap.VIEW_DASHBOARD)
    if request.user.is_owner:
        from apps.shifts.services import shifts_missing_backup

        context["missing_backup"] = shifts_missing_backup()
    return render(request, "core/home.html", context)


@require_GET
@never_cache
def healthz(request):
    """Kiểm tra máy chủ và cơ sở dữ liệu còn sống (dùng cho giám sát NFR-05)."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
    return JsonResponse({"status": "ok"})


@require_GET
def manifest(request):
    return render(request, "pwa/manifest.webmanifest", content_type="application/manifest+json")


@require_GET
def service_worker(request):
    # Phục vụ ở gốc trang để service worker có phạm vi toàn ứng dụng.
    response = render(request, "pwa/sw.js", content_type="application/javascript")
    response["Service-Worker-Allowed"] = "/"
    response["Cache-Control"] = "no-cache"
    return response


@require_GET
def offline(request):
    return render(request, "pwa/offline.html")
