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


def _pending_at(line, moment):
    """Số ly của dòng còn chờ pha tại `moment` (ước lượng: dòng chưa pha xong hết thì tính phần chưa pha hiện tại)."""
    if hasattr(line.order, "backup_slip") or line.order.created_at >= moment:
        return 0
    if line.done_at and line.done_at <= moment:
        return 0
    already = line.done_quantity if line.done_at is None else 0
    return max(line.quantity - line.cancelled_quantity - already, 0)


def day_frames(day):
    from apps.staff.timekeeping import presence

    start = timezone.make_aware(datetime.combine(day, time.min))
    end = start + timedelta(days=1)
    lines = list(OrderLine.objects.filter(order__created_at__gte=start - timedelta(hours=12),
                                          order__created_at__lt=end + timedelta(hours=12))
                 .select_related("order", "order__backup_slip", "item__group"))
    standard = params.get("wait_standard_minutes", at=start)
    backlog_limit = params.get("bar_backlog_limit", at=start)
    frames = []
    for hour in range(24):
        f_start, f_end = start + timedelta(hours=hour), start + timedelta(hours=hour + 1)
        in_frame = [l for l in lines if f_start <= _order_time(l) < f_end]
        cups = sum(l.quantity - l.cancelled_quantity for l in in_frame)
        load = sum((l.quantity - l.cancelled_quantity) * l.item.group.load_factor for l in in_frame)
        waits = [(l.served_at - l.order.created_at).total_seconds() / 60 for l in in_frame
                 if l.served_at and not hasattr(l.order, "backup_slip")]
        backlog = sum(_pending_at(l, f_end) for l in lines)
        med = Decimal(str(round(median(waits), 1))) if waits else None
        over = bool((med is not None and med > standard) or backlog > backlog_limit)
        if not in_frame and not backlog:
            continue
        frames.append({"start": f_start, "end": f_end, "orders": len({l.order_id for l in in_frame}), "cups": cups,
                       "load": Decimal(load).quantize(Decimal("0.1")), "median_wait": med, "backlog": backlog,
                       "overloaded": over, "presence": presence(f_start, f_end)})
    return {"frames": frames, "standard": standard, "backlog_limit": backlog_limit}
