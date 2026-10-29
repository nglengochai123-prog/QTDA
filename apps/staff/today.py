"""Dữ liệu cho màn Chấm công: thẻ vào ra ca của nhân viên, bảng hôm nay và lượt thiếu giờ ra của Chủ quán.

Đối chiếu lịch đã xếp với giờ vào thật để thấy ai đi trễ, ai chưa vào. Chỉ đọc; ghi đi qua timekeeping.py."""

from datetime import datetime, time, timedelta

from django.utils import timezone

from apps.accounts.models import Role
from apps.core import params

from . import timekeeping
from .models import Attendance


def _span(delta):
    minutes = max(0, int(delta.total_seconds() // 60))
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours} giờ {minutes} phút" if minutes else f"{hours} giờ"
    return f"{minutes} phút"


def _bounds(shift):
    tz = timezone.get_current_timezone()
    return (timezone.make_aware(datetime.combine(shift.date, shift.start), tz),
            timezone.make_aware(shift.end_datetime, tz))


def _assignments(day, user=None):
    from apps.schedule.models import Assignment

    rows = Assignment.objects.filter(shift__date=day, removed_at__isnull=True).select_related("shift", "user")
    if user is not None:
        rows = rows.filter(user=user)
    return list(rows.order_by("shift__start", "user__username"))


EARLY = timedelta(hours=2)  # vào sớm hơn giờ bắt đầu ca quá mức này thì không coi là lượt của ca đó


def _match(att, start, end):
    """Lượt chấm công thuộc ca khi vào trong khoảng từ trước giờ bắt đầu hai tiếng đến trước giờ kết thúc ca."""
    return start - EARLY <= att.clock_in < end


def staff_card(user, now=None):
    now = now or timezone.now()
    today = timezone.localdate(now)
    current = timekeeping.open_attendance(user)
    roles = [(r, Role(r).label) for r in timekeeping.WORK_ROLES if user.has_role(r)]
    planned = []
    for a in _assignments(today, user):
        start, end = _bounds(a.shift)
        planned.append({"a": a, "shift": a.shift, "role": Role(a.role).label if a.role in Role.values else a.role,
                        "start": start, "end": end, "over": end <= now})
    upcoming = next((p for p in planned if not p["over"]), None)
    # Vai trò chọn sẵn khi vào ca: vai trò của ca sắp tới trong lịch nếu người này đảm nhận được, không thì vai trò
    # chính trong hồ sơ.
    values = [r for r, _ in roles]
    default_role = (upcoming["a"].role if upcoming and upcoming["a"].role in values else
                    user.role if user.role in values else values[0] if values else "")
    week = today - timedelta(days=today.weekday())
    lo = timezone.make_aware(datetime.combine(week, time.min))
    mine = list(Attendance.objects.filter(user=user, clock_in__gte=lo - timedelta(days=7)).order_by("-clock_in"))
    rows, week_hours, week_count, last_hours = [], 0, 0, 0
    for att in mine[:14]:
        rows.append({"att": att, "hours": timekeeping.valid_hours(att), "this_week": att.clock_in >= lo})
    for att in mine:
        if att.clock_in >= lo:
            week_count += 1
            week_hours += timekeeping.valid_hours(att)
        else:
            last_hours += timekeeping.valid_hours(att)
    return {
        "current": current, "roles": roles, "default_role": default_role, "planned": planned, "upcoming": upcoming,
        "worked": _span(now - current.clock_in) if current else "",
        "current_shift": next((p for p in planned if current and _match(current, p["start"], p["end"])), None),
        "rows": rows, "week_hours": week_hours, "week_count": week_count, "week": week, "last_hours": last_hours,
        # Lượt mở từ hôm trước: quên bấm Ra ca, Chủ quán bổ sung giờ ra đúng (AC-77, AC-78).
        "stale": bool(current and timekeeping.is_forgotten(current, now)),
    }


def owner_board(now=None):
    now = now or timezone.now()
    today = timezone.localdate(now)
    late_after = timedelta(minutes=params.get("late_minutes"))
    atts = list(Attendance.objects.filter(clock_in__date=today, clock_in__lte=now).select_related("user")
                .order_by("clock_in"))
    used, rows = set(), []
    for a in _assignments(today):
        start, end = _bounds(a.shift)
        att = next((x for x in atts if x.user_id == a.user_id and x.pk not in used and _match(x, start, end)), None)
        if att:
            used.add(att.pk)
            late = att.clock_in - start
            if late > late_after:
                state, tone, note = "late", "warn", f"Trễ {_span(late)}"
            else:
                state, tone, note = "ok", "ok", "Đúng giờ"
            if att.clock_out is None:
                note += " · đang làm"
        elif now < start:
            state, tone, note = "wait", "neutral", f"Vào lúc {a.shift.start:%H:%M}"
        elif now < end:
            state, tone, note = "missing", "danger", f"Chưa vào ca · trễ {_span(now - start)}"
        else:
            state, tone, note = "absent", "danger", "Không chấm công"
        rows.append({"a": a, "user": a.user, "shift": a.shift, "role": Role(a.role).label if a.role in Role.values else a.role,
                     "att": att, "state": state, "tone": tone, "note": note})
    extra = [{"att": x, "user": x.user, "role": x.get_role_display()} for x in atts if x.pk not in used]
    missing = []
    plans = {}
    for att in timekeeping.missing_clock_out(now):
        day = timezone.localdate(att.clock_in)
        if day not in plans:
            plans[day] = _assignments(day)
        shift = next((p.shift for p in plans[day] if p.user_id == att.user_id and _match(att, *_bounds(p.shift))), None)
        # Giờ ra gợi ý: giờ kết thúc ca trong lịch, nếu không có lịch thì sau giờ vào 8 tiếng; không quá hiện tại.
        guess = _bounds(shift)[1] if shift else att.clock_in + timedelta(hours=8)
        latest = min(att.clock_in + timedelta(hours=timekeeping.MAX_SHIFT_HOURS), now)
        guess = min(guess, latest)
        missing.append({"att": att, "shift": shift, "guess": timezone.localtime(guess),
                        "min": timezone.localtime(att.clock_in + timedelta(minutes=1)),
                        "max": timezone.localtime(latest)})
    working = [x for x in atts if x.clock_out is None]
    return {
        "rows": rows, "extra": extra, "missing": missing, "working": len(working),
        "planned": len(rows), "late": sum(1 for r in rows if r["state"] == "late"),
        "absent": sum(1 for r in rows if r["state"] in ("missing", "absent")),
        "today": today, "now": now,
    }
