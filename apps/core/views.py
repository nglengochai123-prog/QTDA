from django.contrib.auth.decorators import login_required
from django.db import connection
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST


@login_required
def home(request):
    """Tóm tắt của tôi: việc đang chờ mình xử lý (có số và lối vào) và lối tắt theo quyền."""
    from django.urls import reverse

    from apps.accounts.permissions import Cap, user_can

    user = request.user
    can = lambda cap: user_can(user, cap)  # noqa: E731
    tasks = []

    def task(label, count, url, urgent=False):
        tasks.append({"label": label, "count": count, "url": url, "urgent": urgent and count > 0})

    if can(Cap.ORDER_ADJUST_APPROVE):
        from apps.orders.adjustments import pending_for

        task("Yêu cầu điều chỉnh chờ tôi duyệt", len(pending_for(user)), reverse("orders:approvals"), urgent=True)
    if can(Cap.HANDLE_ALERTS):
        from apps.control.alerts import visible_to
        from apps.control.models import Alert

        task("Cảnh báo của tôi", visible_to(user).filter(status__in=Alert.OPEN).count(), reverse("control:alerts"),
             urgent=True)
    if can(Cap.EXCEPTION_REVIEW):
        from apps.control.models import ExceptionCase

        task("Ngoại lệ chờ xem xét", ExceptionCase.objects.filter(status=ExceptionCase.Status.OPEN).count(),
             reverse("control:exceptions"))
    if can(Cap.STOCK_CONFIRM_ORDERING):
        from apps.inventory.models import StockCount

        task("Kiểm kê chờ xác nhận", StockCount.objects.filter(status=StockCount.Status.PENDING).count(),
             reverse("inventory:count"))
    if can(Cap.BACKUP_TICKETS) and user.is_owner:
        from apps.orders.models import BackupSlip

        task("Phiếu dự phòng chờ xác nhận giá", BackupSlip.objects.filter(status=BackupSlip.Status.PENDING).count(),
             reverse("orders:backup_slips"))
    if can(Cap.VIEW_WORKLOAD):
        from apps.inventory.models import QuickReport

        task("Báo nhanh nguyên liệu chưa xử lý", QuickReport.objects.filter(acknowledged_at__isnull=True).count(),
             reverse("inventory:stock"))
    if can(Cap.PAYMENT):
        from apps.shifts.models import Refund

        task("Hoàn tiền chờ trả khách", Refund.objects.filter(status=Refund.Status.APPROVED).count(),
             reverse("orders:cashier"), urgent=True)
    if can(Cap.CASH_FUND):
        from apps.shifts.models import CashEntry

        handovers = CashEntry.objects.filter(kind=CashEntry.Kind.HANDOVER, receiver=user, confirmed_at__isnull=True).count()
        if handovers:  # hiếm khi có, nên chỉ hiện ô khi đang có khoản chờ
            task("Tiền nộp chờ tôi xác nhận", handovers, reverse("shifts:my_shift"), urgent=True)
    if can(Cap.ORDER_CREATE):
        from apps.orders.models import Order

        task("Đơn đang mở", Order.objects.exclude(status__in=["da_thanh_toan", "da_huy"]).count(),
             reverse("orders:open_orders"))

    # Việc đang chờ lên trước; trên điện thoại ô số 0 được ẩn (app.css) để màn hình ngắn lại.
    tasks.sort(key=lambda t: not t["count"])
    context = {"tasks": tasks, "tasks_waiting": sum(1 for t in tasks if t["count"])}
    if can(Cap.MASTER_DATA):
        from apps.catalog.models import MenuItem, Table
        from apps.inventory.models import Ingredient, RecipeVersion
        from apps.shifts.models import Shift
        from apps.staff.models import Employee

        md = lambda key: reverse("masterdata:list", args=[key])  # noqa: E731
        drafts = MenuItem.objects.filter(status=MenuItem.Status.DRAFT).count()
        staff = Employee.objects.filter(status="dang_lam").count()
        selling = MenuItem.objects.sellable().count()
        tables = Table.objects.filter(is_active=True).count()
        ingredients = Ingredient.objects.filter(is_active=True).count()
        # Số 0 ở nhân viên, món đang bán, bàn, nguyên vật liệu nghĩa là quán chưa bán được: tô màu để Chủ quán khai báo.
        context["master_data"] = [
            ("Ca làm việc", md("ca"), f"{Shift.objects.filter(status=Shift.Status.OPEN).count()} ca đang mở", False),
            ("Nhân viên", md("nhan-vien"), f"{staff} đang làm", not staff),
            ("Món và giá", md("mon"), f"{selling} đang bán" + (f", {drafts} đang soạn" if drafts else ""),
             bool(drafts) or not selling),
            ("Bàn", md("ban"), f"{tables} bàn", not tables),
            ("Nguyên vật liệu", md("nguyen-lieu"), f"{ingredients} loại", not ingredients),
            ("Định mức", md("dinh-muc"), f"{RecipeVersion.objects.filter(status='nhap').count()} bản nháp", False),
        ]
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
