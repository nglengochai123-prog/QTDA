"""Dữ liệu cho màn của nhân viên: Đăng ký ca và Lịch của tôi. Chỉ đọc; ghi đi qua services.py."""

from datetime import datetime, timedelta

from django.utils import timezone

from . import services as sv
from .board import DAY_NAMES, DAY_SHORT
from .models import Assignment, Registration, WeekPublish, WorkShift


def _left(delta):
    """Thời gian còn lại dạng ngắn: 2 ngày 3 giờ, 5 giờ 10 phút, 25 phút."""
    minutes = max(0, int(delta.total_seconds() // 60))
    days, rest = divmod(minutes, 24 * 60)
    hours, minutes = divmod(rest, 60)
    if days:
        return f"{days} ngày {hours} giờ" if hours else f"{days} ngày"
    if hours:
        return f"{hours} giờ {minutes} phút" if minutes else f"{hours} giờ"
    return f"{minutes} phút"


def register_page(user, week, now=None):
    now = now or timezone.now()
    today = timezone.localdate(now)
    roles = sv.user_roles(user)
    deadline = sv.deadline_for(week)
    open_ = now <= deadline
    published = WeekPublish.objects.filter(week_start=week).exists()
    shifts = list(sv.week_shifts(week))
    days, names = [], {}
    for k in range(7):
        d = week + timedelta(days=k)
        days.append({"date": d, "name": DAY_NAMES[k], "short": DAY_SHORT[k], "today": d == today,
                     "weekend": k >= 5, "items": []})
    chosen = hours = 0
    for s in shifts:
        regs = [r for r in s.registrations.all() if r.cancelled_at is None]
        mine = next((r for r in regs if r.user_id == user.pk), None)
        placed = next((a for a in s.assignments.all() if a.user_id == user.pk and a.removed_at is None), None)
        needs = {n.role: n.needed for n in s.needs.all()}
        options, short = [], []
        for role in roles:
            need, count = needs.get(role, 0), sum(1 for r in regs if r.role == role)
            options.append({"role": role, "label": sv.ROLE_LABEL[role], "need": need, "count": count})
            if need > count:
                short.append({"label": sv.ROLE_LABEL[role].lower(), "n": need - count})
        # Vị trí nên chọn khi bấm chọn nhanh: vị trí đang thiếu nhiều nhất, nếu không thì vị trí đầu.
        best = max(options, key=lambda o: o["need"] - o["count"])["role"] if options else ""
        overlap = [o.name for o in shifts if o.pk != s.pk and s.overlaps(o)]
        item = {"shift": s, "mine": mine.role if mine else "", "mine_label": sv.ROLE_LABEL.get(mine.role, "") if mine else "",
                "options": options, "short": short, "best": best, "overlap": overlap,
                "placed": sv.ROLE_LABEL.get(placed.role, placed.role) if placed and published else "",
                "hours": s.hours}
        days[(s.date - week).days]["items"].append(item)
        names.setdefault(s.name, s.start)
        if mine:
            chosen += 1
            hours += s.hours
    return {
        "week": week, "week_end": week + timedelta(days=6), "prev": week - timedelta(days=7),
        "next": week + timedelta(days=7), "next_week": sv.next_week(today),
        "days": [d for d in days if d["items"]], "has_shifts": bool(shifts), "roles": roles,
        "deadline": deadline, "open": open_, "left": _left(deadline - now) if open_ else "",
        "soon": open_ and deadline - now < timedelta(hours=24), "published": published,
        "chosen": chosen, "hours": hours,
        "quick": [n for n, _ in sorted(names.items(), key=lambda x: x[1])],
    }


def my_page(user, now=None):
    now = now or timezone.now()
    today = timezone.localdate(now)
    this_week = sv.week_start(today)
    published = set(WeekPublish.objects.values_list("week_start", flat=True))
    rows = (Assignment.objects.filter(user=user, removed_at__isnull=True, shift__date__gte=this_week)
            .select_related("shift").order_by("shift__date", "shift__start"))
    weeks, upcoming = {}, None
    for a in rows:
        s = a.shift
        w = sv.week_start(s.date)
        if w not in published:
            continue
        tz = timezone.get_current_timezone()
        start = timezone.make_aware(datetime.combine(s.date, s.start), tz)
        end = timezone.make_aware(datetime.combine(s.date, s.end), tz)
        state = "done" if end <= now else "now" if start <= now else "next"
        item = {"a": a, "shift": s, "role": sv.ROLE_LABEL.get(a.role, a.role), "day": DAY_NAMES[s.date.weekday()],
                "short": DAY_SHORT[s.date.weekday()], "today": s.date == today, "state": state, "hours": s.hours,
                "start": start, "end": end}
        if state != "done" and upcoming is None:
            upcoming = item
            item["until"] = _left(start - now) if state == "next" else _left(end - now)
        weeks.setdefault(w, {"week": w, "week_end": w + timedelta(days=6), "items": [], "hours": 0,
                             "label": "Tuần này" if w == this_week else
                             "Tuần sau" if w == this_week + timedelta(days=7) else ""})
        weeks[w]["items"].append(item)
        weeks[w]["hours"] += s.hours
    next_week = this_week + timedelta(days=7)
    deadline = sv.deadline_for(next_week)
    regs_next = Registration.objects.filter(user=user, cancelled_at__isnull=True, shift__date__gte=next_week,
                                            shift__date__lt=next_week + timedelta(days=7)).count()
    # Chủ quán chưa tạo ca nào cho tuần sau thì không có gì để đăng ký: không nhắc.
    next_has_shifts = WorkShift.objects.filter(date__gte=next_week, date__lt=next_week + timedelta(days=7)).exists()
    return {
        "upcoming": upcoming, "weeks": list(weeks.values()), "next_week": next_week,
        "next_published": next_week in published, "regs_next": regs_next, "next_has_shifts": next_has_shifts,
        "register_open": now <= deadline, "deadline": deadline,
        "left": _left(deadline - now) if now <= deadline else "",
    }
