from django.contrib.auth.decorators import login_required
from django.db import connection
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST


# Trang chủ chỉ là danh sách việc đang chờ mình; mọi chức năng đã có ở thanh trên, thanh trái và thanh dưới điện thoại,
# nên không lặp lại lối tắt hay nút chức năng ở đây (Hai, 21/11/2026).
@login_required
def home(request):
    """Việc đang chờ tôi (chỉ việc có số) và ca làm sắp tới."""
    from django.urls import reverse

    from apps.accounts.permissions import Cap, user_can

    from .notifications import pending_tasks

    user = request.user
    can = lambda cap: user_can(user, cap)  # noqa: E731
    # Đơn đang mở là việc nền của cả ca, không phải việc chờ riêng mình; món pha xong thì cần mang ra ngay.
    tasks = [t for t in pending_tasks(user) if t["count"] and t["url"] != reverse("orders:open_orders")]
    tasks.sort(key=lambda t: not t["urgent"])
    context = {"tasks": tasks}
    if can(Cap.SHIFT_REGISTER):
        from apps.schedule.services import my_schedule

        from apps.accounts.models import Role

        from django.utils import timezone

        now = timezone.localtime()
        # Ca hôm nay đã qua giờ kết thúc thì không còn là "ca tới".
        upcoming = [a for a in my_schedule(user) if a.shift.date > now.date() or a.shift.end > now.time()]
        if upcoming:
            upcoming[0].role_label = dict(Role.choices).get(upcoming[0].role, upcoming[0].role)
            context["next_shift"] = upcoming[0]
    if can(Cap.MASTER_DATA):
        from apps.catalog.models import MenuItem, Table
        from apps.inventory.models import Ingredient
        from apps.staff.models import Employee

        md = lambda key: reverse("masterdata:list", args=[key])  # noqa: E731
        drafts = MenuItem.objects.filter(status=MenuItem.Status.DRAFT).count()
        staff = Employee.objects.filter(status="dang_lam").count()
        selling = MenuItem.objects.sellable().count()
        tables = Table.objects.filter(is_active=True).count()
        ingredients = Ingredient.objects.filter(is_active=True).count()
        # Chỉ hiện khi còn thiếu thứ phải khai báo thì mới bán được (quán mới cài, món còn đang soạn).
        setup = [
            ("Nhân viên", md("nhan-vien"), f"{staff} đang làm", not staff),
            ("Món và giá", md("mon"), f"{selling} đang bán" + (f", {drafts} đang soạn" if drafts else ""),
             bool(drafts) or not selling),
            ("Bàn", md("ban"), f"{tables} bàn", not tables),
            ("Nguyên vật liệu", md("nguyen-lieu"), f"{ingredients} loại", not ingredients),
        ]
        context["setup"] = [row for row in setup if row[3]]
    from .models import DATA_NOTICE_VERSION, DataNoticeAck

    context["notice_pending"] = not DataNoticeAck.objects.filter(user=user, version=DATA_NOTICE_VERSION).exists()
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
@require_POST
def push_unsubscribe(request):
    """Đăng xuất trên một thiết bị: thôi gửi thông báo của người này tới thiết bị đó (máy dùng chung ở quầy)."""
    from .models import PushSubscription

    PushSubscription.objects.filter(endpoint=request.POST.get("endpoint", ""), user=request.user).update(is_active=False)
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


@login_required
def data_notice(request):
    """Thông báo xử lý dữ liệu cá nhân cho nhân viên (NFR-13); bấm xác nhận một lần cho mỗi phiên bản."""
    from django.shortcuts import redirect

    from apps.audit.models import Action
    from apps.audit.services import record

    from .models import DATA_NOTICE_VERSION, DataNoticeAck

    ack = DataNoticeAck.objects.filter(user=request.user, version=DATA_NOTICE_VERSION).first()
    if request.method == "POST" and ack is None:
        ack = DataNoticeAck.objects.create(user=request.user, version=DATA_NOTICE_VERSION)
        record(Action.CREATE, request=request, obj=ack, object_type="core.DataNoticeAck",
               after={"phien_ban": DATA_NOTICE_VERSION})
        return redirect("core:home")
    return render(request, "core/data_notice.html", {"version": DATA_NOTICE_VERSION, "acknowledged": ack})


# ---------------- thông báo trong ứng dụng (chuông) ----------------


@login_required
@require_GET
@never_cache
def notification_summary(request):
    """Số chưa đọc, việc đang chờ và thông báo gần nhất cho bảng của chuông; trình duyệt hỏi lại mỗi 30 giây."""
    from . import notifications

    if request.GET.get("chi_so"):
        return JsonResponse({"unread": notifications.unread(request.user).count()})
    return JsonResponse(notifications.summary(request.user))


@login_required
@require_POST
def notification_read(request):
    """Đánh dấu đã đọc: `id` (lặp được) cho từng thông báo, không có `id` là tất cả."""
    from django.shortcuts import redirect

    from . import notifications

    ids = request.POST.getlist("id") or None
    try:
        changed = notifications.mark_read(request.user, ids)
    except ValueError:
        return JsonResponse({"ok": False, "error": "Mã thông báo không hợp lệ."}, status=400)
    if request.headers.get("Accept", "").startswith("application/json"):
        return JsonResponse({"ok": True, "changed": changed, "unread": notifications.unread(request.user).count()})
    return redirect(request.POST.get("next") if _safe_local(request.POST.get("next")) else "core:notifications")


def _safe_local(url):
    """Chỉ chấp nhận đường dẫn trong ứng dụng (bắt đầu bằng một dấu /), không mở sang trang khác."""
    return bool(url) and url.startswith("/") and not url.startswith("//") and "\\" not in url


@login_required
@require_GET
def notification_open(request, pk):
    """Mở một thông báo: đánh dấu đã đọc rồi chuyển tới màn hình liên quan."""
    from django.shortcuts import get_object_or_404, redirect
    from django.utils import timezone

    from .models import Notification

    n = get_object_or_404(Notification, pk=pk, user=request.user)
    if n.read_at is None:
        n.read_at = timezone.now()
        n.save(update_fields=["read_at"])
    return redirect(n.url if _safe_local(n.url) else "core:notifications")


@login_required
@require_GET
def notifications_page(request):
    """Tất cả thông báo của tôi, lọc chưa đọc hoặc theo loại; kèm thẻ bật thông báo trên điện thoại."""
    from . import notifications
    from .models import Notification
    from .paging import paginate

    qs = request.user.notifications.all()
    only_unread = request.GET.get("loc") == "chua-doc"
    kind = request.GET.get("loai", "")
    if only_unread:
        qs = qs.filter(read_at__isnull=True)
    if kind in Notification.Kind.values:
        qs = qs.filter(kind=kind)
    page, query = paginate(request, qs, 30)
    for n in page.object_list:
        n.ago = notifications.ago(n.created_at)
    return render(request, "core/notifications.html", {
        "page": page, "qs": query, "only_unread": only_unread, "kind": kind, "kinds": Notification.Kind.choices,
        "unread_count": notifications.unread(request.user).count()})
