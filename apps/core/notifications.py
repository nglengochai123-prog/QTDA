"""Thông báo trong ứng dụng: chuông trên thanh trên của mọi người dùng.

Hai phần hiện trong bảng của chuông:
1. Thông báo: sự việc đã xảy ra và gửi riêng cho người đó (món pha xong cho người nhận đơn, yêu cầu duyệt cho Chủ
   quán, báo hết nguyên liệu, cảnh báo, lịch làm thay đổi, tiền nộp chờ xác nhận...). Mỗi thông báo có trạng thái đã
   đọc; số trên chuông là số chưa đọc.
2. Việc đang chờ: tính tại lúc mở chuông theo quyền (cùng danh sách ở trang Việc và thông báo).

Thông báo đẩy lên điện thoại (core/push.py) đi cùng: mọi chỗ gọi `push.notify_later` hoặc `push.notify_alert` đều ghi
một thông báo ở đây, nên vẫn thấy được khi máy chủ chưa bật Web Push.
"""

from datetime import timedelta

from django.db import transaction
from django.urls import reverse
from django.utils import timezone

KEEP_DAYS = 60  # thông báo cũ hơn số ngày này được dọn trong tác vụ định kỳ

# Loại thông báo đoán từ màn hình mở khi nơi gửi không nói rõ.
_KIND_BY_URL = [("/duyet/", "phe_duyet"), ("/kho/", "kho"), ("/canh-bao/", "canh_bao"), ("/lich/", "lich"),
                ("/ca/", "ca"), ("/don/san-sang/", "mon_san_sang")]


def kind_for(url):
    for prefix, kind in _KIND_BY_URL:
        if (url or "").startswith(prefix):
            return kind
    return "khac"


def create(user_ids, title, body="", url="", kind=None, key=""):
    """Ghi ngay một thông báo cho mỗi người; cùng `key` cho cùng người thì bỏ qua (không ghi trùng)."""
    from .models import Notification

    kind = kind or kind_for(url)
    rows = [Notification(user_id=uid, kind=kind, title=title[:160], body=(body or "")[:300], url=(url or "")[:200],
                         key=key[:80]) for uid in dict.fromkeys(user_ids)]
    if rows:
        Notification.objects.bulk_create(rows, ignore_conflicts=bool(key))
    return len(rows)


def create_later(user_ids, title, body="", url="", kind=None, key=""):
    """Ghi sau khi giao dịch ghi xong; giao dịch bị hủy thì không có thông báo."""
    ids = list(user_ids)
    transaction.on_commit(lambda: create(ids, title, body, url, kind, key))


def unread(user):
    return user.notifications.filter(read_at__isnull=True)


def mark_read(user, ids=None):
    """Đánh dấu đã đọc các thông báo `ids` của chính người đó; ids None là tất cả. Trả số thông báo đổi trạng thái."""
    qs = unread(user)
    if ids is not None:
        qs = qs.filter(pk__in=[int(i) for i in ids])
    return qs.update(read_at=timezone.now())


def mark_key_read(prefix, at=None):
    """Mọi thông báo chưa đọc có khóa bắt đầu bằng `prefix` thành đã đọc (việc đã xong ở nơi khác)."""
    from .models import Notification

    return Notification.objects.filter(key__startswith=prefix, read_at__isnull=True).update(read_at=at or timezone.now())


def purge(now=None):
    """Dọn thông báo tạo quá KEEP_DAYS ngày, đọc hay chưa: việc cũ như vậy đã được xử lý ở màn hình của nó."""
    from .models import Notification

    now = now or timezone.now()
    return Notification.objects.filter(created_at__lt=now - timedelta(days=KEEP_DAYS)).delete()[0]


def pending_tasks(user, live=True):
    """Việc đang chờ người dùng theo quyền: [{label, count, url, urgent}]. Trang chủ và chuông dùng chung.

    live: thêm các việc đổi từng phút ở quầy (món pha xong chờ mang ra, món chờ pha) mà Trang chủ không hiện."""
    from apps.accounts.permissions import Cap, user_can

    can = lambda cap: user_can(user, cap)  # noqa: E731
    tasks = []

    def task(label, count, url, urgent=False, badge=True):
        tasks.append({"label": label, "count": count, "url": url, "urgent": urgent and count > 0, "badge": badge})

    if live and can(Cap.ORDER_CREATE):
        from django.db.models import F, Sum

        from apps.orders.services import ready_lines

        # Đếm theo ly, cùng đơn vị với Tổng quan ca ("Chờ mang ra 2 ly").
        cups = ready_lines().aggregate(n=Sum(F("quantity") - F("cancelled_quantity")))["n"] or 0
        task("Ly pha xong chờ mang ra", cups, reverse("orders:ready"), urgent=True)
    if live and can(Cap.BAR_PREPARE):
        from apps.orders.services import waiting_lines

        task("Món chờ pha", waiting_lines().count(), reverse("orders:bar"))
    if can(Cap.ORDER_ADJUST_APPROVE):
        from apps.orders.adjustments import pending_for

        task("Yêu cầu điều chỉnh chờ tôi duyệt", len(pending_for(user)), reverse("orders:approvals"), urgent=True)
    if can(Cap.HANDLE_ALERTS):
        from apps.control.alerts import visible_to
        from apps.control.models import Alert

        alerts = visible_to(user).filter(status__in=Alert.OPEN)
        if can(Cap.EXCEPTION_REVIEW):  # ngoại lệ có dòng riêng ngay dưới; không đếm cùng một việc hai lần
            alerts = alerts.exclude(kind=Alert.Kind.EXCEPTION)
        task("Cảnh báo của tôi", alerts.count(), reverse("control:alerts"), urgent=True)
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
        from apps.shifts import services as shift_services
        from apps.shifts.models import CashEntry, Shift

        handovers = CashEntry.objects.filter(kind=CashEntry.Kind.HANDOVER, receiver=user, confirmed_at__isnull=True).count()
        if handovers:  # hiếm khi có, nên chỉ hiện ô khi đang có khoản chờ
            task("Tiền nộp chờ tôi xác nhận", handovers, reverse("shifts:my_shift"), urgent=True)
        # Cùng ca mà màn Ca của tôi mở: ca đang giữ quỹ, nếu không có thì ca đã kết nhưng chưa có báo cáo cuối ca.
        shift = (Shift.objects.operating() or Shift.objects.stale().first()
                 or Shift.objects.filter(status=Shift.Status.CLOSED, report__isnull=True).first())
        status = shift_services.data_status(shift) if shift is not None else None
        if status and status["issues"]:  # chưa kết ca khi đã quá giờ, thiếu báo cáo, phiếu dự phòng, kiểm kê
            day = timezone.localtime(shift.starts_at)
            word = "quá hạn" if status["past_deadline"] else "còn thiếu"
            task(f"Việc {word} của {shift.name.lower()} {day:%d/%m}", len(status["issues"]),
                 reverse("shifts:my_shift"), urgent=True)
    if can(Cap.FORECASTS):
        stale = forecast_stale()
        if stale:
            task(stale, 1, reverse("forecast:overview"), urgent=True, badge=False)
    if can(Cap.ORDER_CREATE):
        from apps.orders.models import Order

        task("Đơn đang mở", Order.objects.exclude(status__in=["da_thanh_toan", "da_huy"]).count(),
             reverse("orders:open_orders"))
    return tasks


STALE_HOURS = 30  # tác vụ hằng đêm chạy sau giờ đóng cửa; quá ngần này giờ chưa có bản mới là đã lỡ ít nhất một đêm


def forecast_stale(now=None):
    """Câu báo khi dự báo, kế hoạch mua và cảnh báo đã cũ vì tác vụ hằng đêm (`manage.py chay_dinh_ky`) không chạy;
    rỗng khi còn mới hoặc quán chưa có bản dự báo nào."""
    from apps.forecast.services import latest_release

    rel = latest_release()
    now = now or timezone.now()
    if rel is None or now - rel.issued_at < timedelta(hours=STALE_HOURS):
        return ""
    return (f"Dự báo, kế hoạch mua và cảnh báo chưa cập nhật từ {timezone.localtime(rel.issued_at):%H:%M %d/%m}: "
            "tác vụ hằng đêm chưa chạy")


def summary(user, limit=8):
    """Dữ liệu cho bảng của chuông: việc đang chờ (chỉ việc có số), số chưa đọc và thông báo gần nhất.
    Không còn trang chủ riêng nên chuông là nơi duy nhất thấy việc chờ từ mọi màn hình."""
    items = [{"id": n.pk, "kind": n.kind, "kind_label": n.get_kind_display(), "title": n.title, "body": n.body,
              "url": reverse("core:notification_open", args=[n.pk]), "read": n.read_at is not None,
              "at": n.created_at.isoformat(), "ago": ago(n.created_at)}
             for n in user.notifications.all()[:limit]]
    waiting = [t for t in pending_tasks(user) if t["count"] and t["url"] != reverse("orders:open_orders")]
    waiting.sort(key=lambda t: not t["urgent"])
    return {"unread": unread(user).count(), "waiting": waiting, "items": items}


def ago(moment, now=None):
    """Khoảng thời gian ngắn gọn: vừa xong, 5 phút, 2 giờ, hôm qua 14:05, 12/11 09:30."""
    now = now or timezone.now()
    secs = (now - moment).total_seconds()
    if secs < 60:
        return "vừa xong"
    if secs < 3600:
        return f"{int(secs // 60)} phút trước"
    local, today = timezone.localtime(moment), timezone.localdate(now)
    if local.date() == today:
        return f"{int(secs // 3600)} giờ trước"
    if local.date() == today - timedelta(days=1):
        return f"hôm qua {local:%H:%M}"
    return f"{local:%d/%m %H:%M}"
