from django.contrib.auth.decorators import login_required
from django.db import connection
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST


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


@login_required
@require_POST
def push_subscribe(request):
    """Lưu đăng ký nhận thông báo đẩy của thiết bị đang dùng."""
    import json

    from .models import PushSubscription

    try:
        body = json.loads(request.body.decode("utf-8"))
        endpoint, keys = body["endpoint"], body["keys"]
        PushSubscription.objects.update_or_create(
            endpoint=endpoint, defaults={"user": request.user, "p256dh": keys["p256dh"], "auth": keys["auth"],
                                         "user_agent": request.headers.get("User-Agent", "")[:200], "is_active": True})
    except (ValueError, KeyError, TypeError):
        return JsonResponse({"ok": False, "error": "Đăng ký không hợp lệ."}, status=400)
    return JsonResponse({"ok": True})


@login_required
@require_GET
def push_status(request):
    from . import push

    ready, reason = push.status()
    return JsonResponse({"ready": ready, "reason": reason, "public_key": push.public_key(),
                         "devices": request.user.push_subscriptions.filter(is_active=True).count()})


@csrf_exempt
@require_POST
def push_receipt(request, message_id, stage):
    """Service worker báo điện thoại đã hiện (nhan) hoặc người dùng đã chạm mở (mo) một thông báo.

    Mã thông báo là UUID ngẫu nhiên chỉ có trong nội dung đã gửi tới thiết bị, nên không cần phiên đăng nhập.
    """
    from django.utils import timezone

    from .models import PushMessage

    field = {"nhan": "received_at", "mo": "opened_at"}.get(stage)
    if field is None:
        return JsonResponse({"ok": False}, status=400)
    PushMessage.objects.filter(pk=message_id, **{f"{field}__isnull": True}).update(**{field: timezone.now()})
    if stage == "mo":
        PushMessage.objects.filter(pk=message_id, received_at__isnull=True).update(received_at=timezone.now())
    return JsonResponse({"ok": True})


@login_required
@require_POST
def push_test(request):
    """Gửi một thông báo thử đến các thiết bị của chính người đang đăng nhập."""
    from . import push

    sent, reason = push.send_to_user(request.user, "Thử thông báo LAM Coffee",
                                     "Nếu bạn thấy dòng này trên điện thoại, thông báo đẩy đã hoạt động.",
                                     "/canh-bao/", kind="thu")
    return JsonResponse({"ok": bool(sent), "accepted": sent, "reason": reason})


@login_required
@require_GET
def push_log(request):
    from .models import PushMessage

    rows = [{"title": m.title, "sent": m.created_at.isoformat(), "accepted": m.accepted_count,
             "codes": [r.get("ma") for r in m.service_results],
             "received": m.received_at.isoformat() if m.received_at else None,
             "opened": m.opened_at.isoformat() if m.opened_at else None}
            for m in PushMessage.objects.filter(user=request.user)[:5]]
    return JsonResponse({"messages": rows})
