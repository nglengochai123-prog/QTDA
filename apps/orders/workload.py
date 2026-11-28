"""Tải công việc và chất lượng phục vụ theo khung giờ một tiếng (FR-36, BRU-27, AC-79).

- Tải = tổng số ly × hệ số tải của nhóm món, theo giờ gửi pha chế (đơn nhập bù tính theo giờ bán trên phiếu).
- Thời gian chờ của một ly = từ lúc gửi pha chế đến lúc Đã phục vụ; khung lấy trung vị của các dòng món gửi trong khung.
  Đơn nhập bù không có giờ gửi pha chế thật nên không tính vào thời gian chờ.
- Món tồn tại quầy = số ly đã gửi trước cuối khung mà chưa pha xong tại thời điểm cuối khung.
- Quá tải khi thời gian chờ trung vị vượt chuẩn hoặc món tồn vượt mức cho phép.
"""

from datetime import datetime, time, timedelta
from decimal import Decimal
from statistics import median

from django.utils import timezone

from apps.core import params

from .models import OrderLine


def _order_time(line):
    slip = getattr(line.order, "backup_slip", None)
    return slip.sold_at if slip is not None and slip.sold_at else line.order.created_at


def _has_slip(line):
    """Đơn có phiếu dự phòng không, không gây truy vấn hay ngoại lệ khi đã select_related("order__backup_slip")."""
    cached = line.order._state.fields_cache
    if "backup_slip" in cached:
        return cached["backup_slip"] is not None
    return hasattr(line.order, "backup_slip")


def _pending_at(line, moment, slipped=None):
    """Số ly của dòng còn chờ pha tại `moment` (ước lượng: dòng chưa pha xong hết thì tính phần chưa pha hiện tại)."""
    if slipped is None:
        slipped = _has_slip(line)
    if slipped or line.order.created_at >= moment:
        return 0
    if line.done_at and line.done_at <= moment:
        return 0
    already = line.done_quantity if line.done_at is None else 0
    return max(line.quantity - line.cancelled_quantity - already, 0)


def day_frames(day, now=None):
    from apps.staff.models import Attendance
    from apps.staff.timekeeping import _forgotten_before, presence

    now = now or timezone.now()
    start = timezone.make_aware(datetime.combine(day, time.min))
    end = start + timedelta(days=1)
    lines = list(OrderLine.objects.filter(order__created_at__gte=start - timedelta(hours=12),
                                          order__created_at__lt=end + timedelta(hours=12))
                 .select_related("order", "order__backup_slip", "item__group"))
    standard = params.get("wait_standard_minutes", at=start)
    backlog_limit = params.get("bar_backlog_limit", at=start)
    open_hour, close_hour = params.get("open_hour", at=start), params.get("close_hour", at=start)
    # Chấm công của cả ngày đọc một lần, mỗi khung đếm trong bộ nhớ (trước đây mỗi khung một truy vấn).
    present_now = timezone.now()
    attendance = list(Attendance.objects.filter(clock_in__lt=end).exclude(clock_out__lte=start))
    forgotten = _forgotten_before(present_now)
    # Tính sẵn một lần cho mỗi dòng: có phiếu dự phòng không (hasattr trên quan hệ một-một rất chậm khi không có) và
    # giờ bán; bảng điều khiển gọi hàm này cho 28 ngày nên mỗi khung không duyệt lại các phép tính đó.
    info = []
    for l in lines:
        slip = getattr(l.order, "backup_slip", None) if _has_slip(l) else None
        info.append((l, slip.sold_at if slip is not None and slip.sold_at else l.order.created_at, slip is not None))
    unslipped = [l for l, _at, slipped in info if not slipped]
    frames = []
    for hour in range(24):
        f_start, f_end = start + timedelta(hours=hour), start + timedelta(hours=hour + 1)
        if f_start >= now:
            break  # khung chưa tới
        in_frame = [l for l, at, _slipped in info if f_start <= at < f_end]
        in_frame_slipped = {l.pk for l, at, slipped in info if slipped and f_start <= at < f_end}
        cups = sum(l.quantity - l.cancelled_quantity for l in in_frame)
        load = sum((l.quantity - l.cancelled_quantity) * l.item.group.load_factor for l in in_frame)
        waits = [(l.served_at - l.order.created_at).total_seconds() / 60 for l in in_frame
                 if l.served_at and l.pk not in in_frame_slipped]
        backlog = sum(_pending_at(l, f_end, slipped=False) for l in unslipped)
        med = Decimal(str(round(median(waits), 1))) if waits else None
        over = bool((med is not None and med > standard) or backlog > backlog_limit)
        if not in_frame and (not backlog or not open_hour <= hour < close_hour):
            continue  # ngoài giờ mở cửa, món tồn từ tối trước không phải tải của khung đó
        frames.append({"start": f_start, "end": f_end, "label": f"{hour:02d}–{hour + 1:02d} giờ", "orders": len({l.order_id for l in in_frame}), "cups": cups,
                       "load": Decimal(load).quantize(Decimal("0.1")), "median_wait": med, "backlog": backlog,
                       "overloaded": over, "presence": presence(f_start, f_end, present_now, attendance, forgotten)})
    return {"frames": frames, "standard": standard, "backlog_limit": backlog_limit}
