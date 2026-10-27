"""Dữ liệu cho màn Lịch làm tuần: lưới ca theo ngày, chi tiết từng ca, các bước lập lịch, góc nhìn theo nhân viên.

Chỉ đọc; mọi thay đổi đi qua services.py."""

from collections import defaultdict
from datetime import timedelta

from django.utils import timezone

from . import services as sv
from .models import Assignment, WeekPublish, WorkShift

DAY_NAMES = ["Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ nhật"]
DAY_SHORT = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"]


def short_name(user):
    """Tên gọi ngắn trên ô lịch: hai chữ cuối của họ tên (Lê Minh Tuấn → Minh Tuấn)."""
    parts = str(user).split()
    return " ".join(parts[-2:]) if len(parts) >= 3 else str(user)


def _state(needed, have):
    if not needed and not have:
        return "none"
    if have < needed:
        return "short"
    return "over" if have > needed else "ok"


def _card(row, today):
    s = row["shift"]
    roles, short = [], 0
    for c in row["cells"]:
        if not (c["needed"] or c["assigned"] or c["registered"]):
            continue
        state = _state(c["needed"], len(c["assigned"]))
        short += c["short"]
        roles.append({
            "role": c["role"], "label": c["label"], "needed": c["needed"], "have": len(c["assigned"]),
            "state": state, "short": c["short"], "surplus": c["surplus"], "need": c["need"],
            "suggested": c["need"].suggested if c["need"] else None,
            "reason": c["need"].reason if c["need"] else "",
            "assigned": [{"a": a, "name": short_name(a.user), "manual": a.source == Assignment.Source.OWNER}
                         for a in c["assigned"]],
            "waiting": c["unassigned_regs"], "registered": len(c["registered"]),
        })
    states = {r["state"] for r in roles}
    state = "empty" if not roles else "short" if "short" in states else "over" if "over" in states else "ok"
    return {"shift": s, "roles": roles, "short": short, "state": state, "past": s.date < today,
            "label": f"{DAY_NAMES[s.date.weekday()]} {s.date:%d/%m}"}


def _details(card, context):
    """Bổ sung cho hộp chi tiết ca: đủ ba vị trí để nhập số cần, người thay thế chưa đăng ký."""
    have = {r["role"]: r for r in card["roles"]}
    details = []
    for role in sv.ROLES:
        r = have.get(role) or {"role": role, "label": sv.ROLE_LABEL[role], "needed": 0, "have": 0, "state": "none",
                               "short": 0, "surplus": 0, "need": None, "suggested": None, "reason": "",
                               "assigned": [], "waiting": [], "registered": 0}
        waiting_ids = {reg.user_id for reg in r["waiting"]}
        r["others"] = [x for x in sv.replacements(card["shift"], role, context) if x["user"].pk not in waiting_ids]
        details.append(r)
    return details


def _steps(week, shifts, cards, published, changed, deadline, now, regs_people, staff_count):
    has_shifts = bool(shifts)
    needs_set = has_shifts and all(any(r["needed"] for r in c["roles"]) for c in cards)
    short = sum(c["short"] for c in cards)
    closed = now > deadline
    steps = [
        {"key": "ca", "title": "Tạo ca", "done": has_shifts,
         "note": f"{len(shifts)} ca trong tuần" if has_shifts else "Chưa có ca nào"},
        {"key": "can", "title": "Số người cần", "done": needs_set,
         "note": "Đã đặt cho mọi ca" if needs_set else "Còn ca chưa đặt số người"},
        {"key": "dang_ky", "title": "Nhân viên đăng ký", "done": closed,
         "note": f"{regs_people}/{staff_count} người đã đăng ký · hạn {timezone.localtime(deadline):%H:%M %d/%m}"},
        {"key": "xep", "title": "Xếp người", "done": has_shifts and short == 0,
         "note": "Đủ người mọi ca" if has_shifts and short == 0 else f"Còn thiếu {short} chỗ"},
        {"key": "cong_bo", "title": "Công bố", "done": bool(published) and not changed,
         "note": ("Có thay đổi sau lần công bố" if changed else
                  f"Đã công bố {timezone.localtime(published.created_at):%H:%M %d/%m}") if published else "Chưa công bố"},
    ]
    current = next((s["key"] for s in steps if not s["done"]), None)
    for n, s in enumerate(steps, start=1):
        s["n"], s["current"] = n, s["key"] == current
    return steps


def _people(week, shifts):
    """Mỗi nhân viên đang làm: ca được xếp từng ngày, số giờ xếp, số ca đã đăng ký mà chưa được xếp."""
    from apps.staff.models import Employee

    days = [week + timedelta(days=k) for k in range(7)]
    assigned, regs = defaultdict(list), defaultdict(list)
    for s in shifts:
        for a in s.assignments.all():
            if a.removed_at is None:
                assigned[a.user_id].append(a)
        for r in s.registrations.all():
            if r.cancelled_at is None:
                regs[r.user_id].append(r)
    rows = []
    for emp in Employee.objects.filter(status="dang_lam").select_related("user").order_by("full_name"):
        mine = assigned.get(emp.user_id, [])
        placed = {a.shift_id for a in mine}
        cells = []
        for d in days:
            items = sorted((a for a in mine if a.shift.date == d), key=lambda a: a.shift.start)
            cells.append([{"name": a.shift.name, "time": f"{a.shift.start:%H:%M}–{a.shift.end:%H:%M}",
                           "role": sv.ROLE_LABEL.get(a.role, a.role)} for a in items])
        rows.append({"emp": emp, "roles": ", ".join(sv.ROLE_LABEL.get(r, r) for r in emp.roles or []),
                     "cells": cells, "hours": sum(a.shift.hours for a in mine),
                     "waiting": sum(1 for r in regs.get(emp.user_id, []) if r.shift_id not in placed),
                     "registered": len(regs.get(emp.user_id, []))})
    return rows


def build(week, now=None):
    from apps.staff.models import Employee

    now = now or timezone.now()
    today = timezone.localdate(now)
    rows, gaps = sv.coverage(week)
    shifts = [r["shift"] for r in rows]
    cards = [_card(r, today) for r in rows]
    context = sv.replacement_context(week)
    for card in cards:
        card["details"] = _details(card, context)
    days = [week + timedelta(days=k) for k in range(7)]
    templates = {}
    for card in cards:
        s = card["shift"]
        key = (s.start, s.end, s.name)
        templates.setdefault(key, {"name": s.name, "start": s.start, "end": s.end, "cells": [None] * 7})
        templates[key]["cells"][(s.date - week).days] = card
    grid = [templates[k] for k in sorted(templates)]
    published = WeekPublish.objects.filter(week_start=week).order_by("-created_at").first()
    changed = False
    if published:
        moved = Assignment.objects.filter(shift__date__gte=week, shift__date__lt=week + timedelta(days=7))
        changed = (moved.filter(created_at__gt=published.created_at).exists()
                   or moved.filter(removed_at__gt=published.created_at).exists())
    deadline = sv.deadline_for(week)
    regs_people = len({r.user_id for s in shifts for r in s.registrations.all() if r.cancelled_at is None})
    staff_count = Employee.objects.filter(status="dang_lam").count()
    totals = []
    for role in sv.ROLES:
        cells = [c for r in rows for c in r["cells"] if c["role"] == role]
        needed = sum(c["needed"] for c in cells)
        have = sum(min(len(c["assigned"]), c["needed"]) for c in cells)
        if needed or any(c["assigned"] for c in cells):
            totals.append({"label": sv.ROLE_LABEL[role], "needed": needed, "have": have,
                           "short": sum(c["short"] for c in cells)})
    gap_days = []
    for card in cards:
        missing = [f"{r['short']} {r['label'].lower()}" for r in card["roles"] if r["short"]]
        if missing:
            gap_days.append({"label": f"{card['label']} · {card['shift'].name}", "missing": ", ".join(missing)})
    basis_days = [d | {"day": DAY_NAMES[d["date"].weekday()]} for d in sv.basis_by_day(rows)]
    previous = sv.week_shifts(week - timedelta(days=7)).count() if not shifts else 0
    recent = (WorkShift.objects.filter(date__lt=week + timedelta(days=7), date__gte=week - timedelta(days=28))
              .values_list("name", "start", "end").distinct())
    presets = sorted({(n, a, b) for n, a, b in recent}, key=lambda p: (p[1], p[0]))[:6]
    return {
        "week": week, "week_end": week + timedelta(days=6), "prev": week - timedelta(days=7),
        "next": week + timedelta(days=7), "this_week": sv.week_start(today),
        "days": [{"date": d, "name": DAY_NAMES[d.weekday()], "short": DAY_SHORT[d.weekday()], "today": d == today,
                  "weekend": d.weekday() >= 5} for d in days],
        "grid": grid, "cards": cards,
        "by_day": [{"date": d, "name": DAY_NAMES[d.weekday()], "today": d == today,
                    "cards": [c for c in cards if c["shift"].date == d]} for d in days], "gaps": gaps, "gap_days": gap_days, "totals": totals,
        "needed": sum(t["needed"] for t in totals), "have": sum(t["have"] for t in totals),
        "short": sum(c["short"] for c in cards), "surplus": sum(r["surplus"] for c in cards for r in c["roles"]),
        "published": published, "changed": changed, "deadline": deadline, "deadline_passed": now > deadline,
        "regs_people": regs_people, "staff_count": staff_count,
        "steps": _steps(week, shifts, cards, published, changed, deadline, now, regs_people, staff_count),
        "people": _people(week, shifts), "previous_count": previous,
        "presets": [{"name": n, "start": a, "end": b} for n, a, b in presets],
        "has_suggestions": any(r["suggested"] is not None for c in cards for r in c["roles"]),
        "basis_days": basis_days, "uncovered": [d for d in basis_days if d["uncovered"]],
    }
