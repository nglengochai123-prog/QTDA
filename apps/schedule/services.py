"""Đăng ký ca, gợi ý số người cần, gợi ý xếp lịch, thiếu dư và công bố (FR-38, FR-39, BRU-28 đến BRU-30).

Quy tắc:
- Nhân viên chỉ đăng ký vị trí mình đảm nhận được và trước hạn (mặc định 12 giờ trưa thứ Năm của tuần trước, AC-85).
  Sau hạn chỉ Chủ quán xếp, có nhật ký.
- Không xếp một người vào hai ca trùng giờ (AC-87).
- Thiếu, dư tính riêng từng vị trí của mỗi ca (AC-86): đủ tổng người vẫn có thể thiếu một vị trí.
- Gợi ý số người cần (BRU-28): tải dự kiến từng giờ = số ly dự báo của ngày × tỷ lệ bán theo giờ trong lịch sử ×
  hệ số tải bình quân mỗi ly; số người = làm tròn lên (tải ÷ năng suất), không thấp hơn mức tối thiểu; nhu cầu
  của ca là giờ cao nhất trong ca. Năng suất do Chủ quán đặt, để 0 thì lấy trung vị tải mỗi người của các giờ không
  bị đánh dấu quá tải trong 8 tuần gần nhất. Đây là gợi ý; Chủ quán sửa số áp dụng, khác gợi ý thì ghi lý do.
- Gợi ý xếp lịch: ô khan hiếm (ít người đăng ký so với nhu cầu) được xếp trước; trong ô, ưu tiên người có ít giờ
  đã xếp trong tuần, rồi người đăng ký sớm. Ô Chủ quán đã xếp tay được giữ nguyên.
"""

import math
from collections import defaultdict
from datetime import datetime, time, timedelta
from statistics import median

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.audit.models import Action
from apps.audit.services import record
from apps.core import params

from .models import Assignment, Registration, RoleNeed, WeekPublish, WorkShift

ROLES = [Role.PHA_CHE, Role.PHUC_VU, Role.THU_NGAN]
ROLE_LABEL = dict(Role.choices)


def week_start(day):
    return day - timedelta(days=day.weekday())


def next_week(today=None):
    return week_start(today or timezone.localdate()) + timedelta(days=7)


def deadline_for(week):
    """Hạn đăng ký cho tuần bắt đầu `week`: thứ và giờ theo tham số, trong tuần liền trước."""
    weekday = params.get("schedule_deadline_weekday") - 2  # 2 là thứ Hai → 0
    day = week - timedelta(days=7) + timedelta(days=max(0, min(weekday, 6)))
    return timezone.make_aware(datetime.combine(day, time(params.get("schedule_deadline_hour"))))


def week_shifts(week):
    return (WorkShift.objects.filter(date__gte=week, date__lt=week + timedelta(days=7))
            .prefetch_related("needs", "registrations", "assignments").order_by("date", "start"))


def user_roles(user):
    from apps.staff.models import Employee

    emp = Employee.objects.filter(user=user).first()
    roles = set(emp.roles if emp and emp.is_working else [])
    if not emp and user.role in ROLES:
        roles.add(user.role)
    return [r for r in ROLES if r in roles]


# ---------------- đăng ký (FR-38) ----------------

@transaction.atomic
def register(user, choices, now=None):
    """choices: {shift_id: role hoặc ''}. Thay toàn bộ đăng ký của người này trong tuần của các ca được gửi."""
    now = now or timezone.now()
    shifts = {s.pk: s for s in WorkShift.objects.filter(pk__in=choices)}
    if not shifts:
        raise ValidationError("Chưa chọn ca nào.")
    weeks = {week_start(s.date) for s in shifts.values()}
    for w in weeks:
        if now > deadline_for(w):
            raise ValidationError(f"Đã quá hạn đăng ký ({deadline_for(w):%H:%M %d/%m}). Liên hệ Chủ quán để được xếp ca.")
    allowed = set(user_roles(user))
    for shift_id, role in choices.items():
        if role and role not in allowed:
            raise ValidationError(f"Bạn không đảm nhận được vị trí {ROLE_LABEL.get(role, role)}.")
    changed = []
    for shift_id, role in choices.items():
        shift = shifts[shift_id]
        current = Registration.objects.filter(shift=shift, user=user, cancelled_at__isnull=True).first()
        if current and current.role == role:
            continue
        if current:
            current.cancelled_at = now
            current.save(update_fields=["cancelled_at", "updated_at"])
        if role:
            Registration.objects.create(shift=shift, user=user, role=role)
        changed.append((str(shift), ROLE_LABEL.get(role, "bỏ đăng ký")))
    if changed:
        record(Action.UPDATE, actor=user, object_type="schedule.Registration",
               after={"dang_ky": [f"{s}: {r}" for s, r in changed]}, reason="Nhân viên đăng ký ca")
    return changed


# ---------------- gợi ý số người cần (BRU-28) ----------------

def _hourly_profile(today, window=56):
    """Tỷ lệ số ly theo giờ trong ngày cho ngày thường và cuối tuần, và hệ số tải bình quân mỗi ly."""
    from apps.orders.models import OrderLine

    tz = timezone.get_current_timezone()
    lo = timezone.make_aware(datetime.combine(today - timedelta(days=window), time.min), tz)
    hi = timezone.make_aware(datetime.combine(today, time.min), tz)
    cups = {False: defaultdict(float), True: defaultdict(float)}
    load = cups_total = 0.0
    for line in OrderLine.objects.filter(order__created_at__gte=lo, order__created_at__lt=hi).select_related(
            "order", "item__group"):
        n = line.quantity - line.cancelled_quantity
        if n <= 0:
            continue
        t = timezone.localtime(line.order.created_at)
        cups[t.weekday() >= 5][t.hour] += n
        load += n * float(line.item.group.load_factor)
        cups_total += n
    profile = {}
    for weekend, by_hour in cups.items():
        total = sum(by_hour.values())
        profile[weekend] = {h: v / total for h, v in by_hour.items()} if total else {}
    return profile, (load / cups_total if cups_total else 1.0)


def productivity(today, window=56):
    """Năng suất mỗi vị trí (tải mỗi người mỗi giờ): tham số của Chủ quán, hoặc trung vị của các giờ không quá tải."""
    from apps.orders.workload import day_frames

    out, samples = {}, defaultdict(list)
    need_auto = [r for r in ROLES if not params.get(f"schedule_productivity_{r}")]
    if need_auto:
        for k in range(1, window + 1):
            for f in day_frames(today - timedelta(days=k))["frames"]:
                if f["overloaded"]:
                    continue  # BRU-28: không học năng suất từ giờ quá tải
                for r in need_auto:
                    present = f["presence"].get(r, 0)
                    if present:
                        samples[r].append(float(f["load"]) / present)
    for r in ROLES:
        set_value = params.get(f"schedule_productivity_{r}")
        if set_value:
            out[r] = {"value": float(set_value), "source": "Chủ quán đặt"}
        elif len(samples[r]) >= 5:
            out[r] = {"value": round(median(samples[r]), 1), "source": f"Trung vị {len(samples[r])} giờ không quá tải"}
        else:
            out[r] = None
    return out


def _daily_cups(day, today):
    """Số ly dự kiến của ngày: từ lần phát hành dự báo gần nhất; ngoài chân trời thì bình quân 4 ngày cùng thứ."""
    from apps.forecast.services import latest_release

    rel = latest_release()
    if rel:
        idx = (day - rel.first_day).days
        total, ok = 0.0, False
        for s in rel.series.all():
            if 0 <= idx < len(s.daily):
                total += s.daily[idx]["mean"]
                ok = True
        if ok:
            return total, "Dự báo phát hành " + timezone.localtime(rel.issued_at).strftime("%d/%m")
    from apps.forecast.services import cups_by_day

    days = [day - timedelta(days=7 * k) for k in range(1, 5) if day - timedelta(days=7 * k) < today]
    if not days:
        return None, ""
    by = cups_by_day(min(days), max(days))
    totals = [sum(series.get(d, 0) for series in by.values()) for d in days]
    return sum(totals) / len(totals), "Bình quân 4 ngày cùng thứ gần nhất"


def suggest_needs(shift, today=None, profile=None, prod=None):
    """{role: (số người gợi ý, căn cứ)} cho một ca."""
    today = today or timezone.localdate()
    if profile is None:
        profile = _hourly_profile(today)
    if prod is None:
        prod = productivity(today)
    shares, load_per_cup = profile
    cups, source = _daily_cups(shift.date, today)
    minimum = params.get("schedule_min_per_role")
    out = {}
    hours = list(range(shift.start.hour, shift.end.hour + (1 if shift.end.minute else 0)))
    share = shares.get(shift.date.weekday() >= 5, {})
    peak_load = max((cups or 0) * share.get(h, 0) * load_per_cup for h in hours) if hours and cups else 0
    for r in ROLES:
        p = prod.get(r)
        if cups is None or not share or p is None:
            out[r] = (None, {"missing": "Chưa đủ dữ liệu bán theo giờ hoặc năng suất; nhập số người cần."})
            continue
        n = max(minimum, math.ceil(peak_load / p["value"])) if p["value"] > 0 else minimum
        out[r] = (n, {"cups": round(cups, 1), "cups_source": source, "peak_load": round(peak_load, 1),
                      "productivity": p["value"], "productivity_source": p["source"], "minimum": minimum})
    return out


@transaction.atomic
def apply_suggested_needs(week, user):
    """Ghi số gợi ý cho mọi ô của tuần; ô Chủ quán đã đặt khác gợi ý (có lý do) giữ số của Chủ quán."""
    today = timezone.localdate()
    profile, prod = _hourly_profile(today), productivity(today)
    changed = 0
    for shift in week_shifts(week):
        for role, (n, basis) in suggest_needs(shift, today, profile, prod).items():
            need, _ = RoleNeed.objects.get_or_create(shift=shift, role=role, defaults={"needed": n or 0})
            need.suggested, need.basis = n, basis
            if n is not None and not need.reason:
                need.needed = n
            need.save()
            changed += 1
    record(Action.UPDATE, actor=user, object_type="schedule.RoleNeed", after={"tuan": str(week), "so_o": changed},
           reason="Áp dụng gợi ý số người cần")
    return changed


def set_need(user, shift, role, needed, reason=""):
    need, _ = RoleNeed.objects.get_or_create(shift=shift, role=role, defaults={"needed": needed})
    if need.suggested is not None and needed != need.suggested and not reason.strip():
        raise ValidationError(f"{ROLE_LABEL[role]} {shift}: khác số gợi ý {need.suggested}, ghi lý do (BRU-28).")
    before = need.needed
    need.needed, need.reason = needed, reason.strip()[:255]
    need.save()
    if before != needed:
        record(Action.UPDATE, actor=user, obj=need, object_type="schedule.RoleNeed", before={"can": before},
               after={"can": needed, "ca": str(shift), "vi_tri": ROLE_LABEL[role]}, reason=need.reason)
    return need


# ---------------- xếp lịch (FR-39) ----------------

def _active_assignments(week):
    return list(Assignment.objects.filter(shift__date__gte=week, shift__date__lt=week + timedelta(days=7),
                                          removed_at__isnull=True).select_related("shift", "user"))


def conflicts(user, shift, exclude_shift=None):
    """Ca khác trùng giờ mà người này đã được xếp (AC-87)."""
    return [a.shift for a in Assignment.objects.filter(user=user, removed_at__isnull=True, shift__date=shift.date)
            .exclude(shift=exclude_shift or shift).select_related("shift") if a.shift.overlaps(shift)]


@transaction.atomic
def assign(owner, shift, user, role, source=Assignment.Source.OWNER):
    if role not in user_roles(user):
        raise ValidationError(f"{user} không đảm nhận được vị trí {ROLE_LABEL.get(role, role)}.")
    clash = conflicts(user, shift)
    if clash:
        raise ValidationError(f"{user} đã có {clash[0]} trùng giờ.")
    current = Assignment.objects.filter(shift=shift, user=user, removed_at__isnull=True).first()
    if current:
        if current.role == role:
            return current
        current.removed_at, current.remove_reason = timezone.now(), "Đổi vị trí"
        current.save(update_fields=["removed_at", "remove_reason", "updated_at"])
    a = Assignment.objects.create(shift=shift, user=user, role=role, source=source, assigned_by=owner)
    late = timezone.now() > deadline_for(week_start(shift.date))
    if source == Assignment.Source.OWNER:
        record(Action.CREATE, actor=owner, obj=a, object_type="schedule.Assignment",
               after={"ca": str(shift), "nhan_vien": str(user), "vi_tri": ROLE_LABEL[role]},
               reason="Chủ quán xếp sau hạn đăng ký" if late else "Chủ quán xếp")
    return a


@transaction.atomic
def unassign(owner, assignment, reason=""):
    assignment.removed_at, assignment.remove_reason = timezone.now(), reason.strip()[:255] or "Chủ quán bỏ ra"
    assignment.save(update_fields=["removed_at", "remove_reason", "updated_at"])
    record(Action.DELETE, actor=owner, obj=assignment, object_type="schedule.Assignment",
           before={"ca": str(assignment.shift), "nhan_vien": str(assignment.user)}, reason=assignment.remove_reason)


@transaction.atomic
def auto_assign(owner, week):
    """Gợi ý xếp lịch theo đăng ký; giữ nguyên các ô Chủ quán đã xếp tay."""
    Assignment.objects.filter(shift__date__gte=week, shift__date__lt=week + timedelta(days=7),
                              source=Assignment.Source.SUGGESTED, removed_at__isnull=True).update(
        removed_at=timezone.now(), remove_reason="Xếp lại theo gợi ý")
    shifts = list(week_shifts(week))  # đọc sau khi bỏ các lượt gợi ý cũ để đếm đúng số đã xếp
    taken = defaultdict(list)  # user_id -> [shift]
    hours = defaultdict(float)
    for a in _active_assignments(week):
        taken[a.user_id].append(a.shift)
        hours[a.user_id] += a.shift.hours
    cells = []
    for s in shifts:
        needs = {n.role: n.needed for n in s.needs.all()}
        regs = [r for r in s.registrations.all() if r.cancelled_at is None]
        for role, need in needs.items():
            have = sum(1 for a in s.assignments.all() if a.removed_at is None and a.role == role)
            pool = [r for r in regs if r.role == role]
            if need > have:
                cells.append((len(pool) / max(need - have, 1), s, role, need - have, pool))
    cells.sort(key=lambda c: (c[0], c[1].date, c[1].start))
    made = 0
    for _, s, role, missing, pool in cells:
        pool = sorted(pool, key=lambda r: (hours[r.user_id], r.created_at))
        for reg in pool:
            if missing <= 0:
                break
            if any(sh.pk == s.pk or sh.overlaps(s) for sh in taken[reg.user_id]):
                continue
            if role not in user_roles(reg.user):
                continue
            Assignment.objects.create(shift=s, user=reg.user, role=role, source=Assignment.Source.SUGGESTED,
                                      assigned_by=owner)
            taken[reg.user_id].append(s)
            hours[reg.user_id] += s.hours
            missing -= 1
            made += 1
    record(Action.UPDATE, actor=owner, object_type="schedule.Assignment", after={"tuan": str(week), "xep": made},
           reason="Gợi ý xếp lịch theo đăng ký")
    return made


def coverage(week):
    """Từng ô (ca, vị trí): cần, đã xếp, đã đăng ký, thiếu, dư (AC-86); kèm tổng hợp chỗ thiếu."""
    rows, gaps = [], []
    for s in week_shifts(week):
        needs = {n.role: n for n in s.needs.all()}
        active = [a for a in s.assignments.all() if a.removed_at is None]
        regs = [r for r in s.registrations.all() if r.cancelled_at is None]
        cells = []
        for role in ROLES:
            need = needs.get(role)
            n = need.needed if need else 0
            assigned = [a for a in active if a.role == role]
            registered = [r for r in regs if r.role == role]
            cell = {"role": role, "label": ROLE_LABEL[role], "need": need, "needed": n, "assigned": assigned,
                    "registered": registered, "unassigned_regs": [r for r in registered
                                                                   if r.user_id not in {a.user_id for a in active}],
                    "short": max(n - len(assigned), 0), "surplus": max(len(assigned) - n, 0),
                    "reg_short": max(n - len(registered), 0)}
            if cell["short"]:
                gaps.append(f"{s} thiếu {cell['short']} {ROLE_LABEL[role].lower()}")
            cells.append(cell)
        rows.append({"shift": s, "cells": cells})
    return rows, gaps


def replacements(shift, role):
    """Người thay thế: có kỹ năng vị trí, đang làm, chưa có ca trùng giờ; người đã đăng ký ca này trước (AC-87)."""
    from apps.staff.models import Employee

    registered = {r.user_id for r in shift.registrations.filter(cancelled_at__isnull=True)}
    assigned = set(shift.assignments.filter(removed_at__isnull=True).values_list("user_id", flat=True))
    week = week_start(shift.date)
    hours = defaultdict(float)
    for a in _active_assignments(week):
        hours[a.user_id] += a.shift.hours
    out = []
    for emp in Employee.objects.filter(status="dang_lam").select_related("user"):
        if role not in (emp.roles or []) or emp.user_id in assigned or conflicts(emp.user, shift):
            continue
        out.append({"user": emp.user, "registered": emp.user_id in registered, "hours": hours[emp.user_id]})
    out.sort(key=lambda x: (not x["registered"], x["hours"], str(x["user"])))
    return out


@transaction.atomic
def publish(owner, week):
    rows, gaps = coverage(week)
    pub = WeekPublish.objects.create(week_start=week, published_by=owner, gaps=gaps)
    record(Action.STATUS_CHANGE, actor=owner, obj=pub, object_type="schedule.WeekPublish",
           after={"tuan": str(week), "con_thieu": len(gaps)})
    from apps.core.push import notify_later

    per_user = defaultdict(list)
    for a in _active_assignments(week):
        per_user[a.user_id].append(a)
    for user_id, items in per_user.items():
        items.sort(key=lambda a: (a.shift.date, a.shift.start))
        body = "; ".join(f"{a.shift.date:%d/%m} {a.shift.start:%H:%M}–{a.shift.end:%H:%M} {ROLE_LABEL[a.role]}"
                         for a in items[:6]) + ("…" if len(items) > 6 else "")
        notify_later([user_id], f"Lịch làm tuần {week:%d/%m}", body, "/lich/cua-toi/")
    return pub


def is_published(week):
    return WeekPublish.objects.filter(week_start=week).exists()


@transaction.atomic
def copy_week(owner, source, target):
    """Chép các ca và số người cần của tuần nguồn sang tuần đích (ca đã có cùng tên trong ngày thì bỏ qua)."""
    from apps.core.models import Store

    made = 0
    for s in week_shifts(source):
        day = target + timedelta(days=(s.date - source).days)
        new, created = WorkShift.objects.get_or_create(
            date=day, name=s.name, defaults={"start": s.start, "end": s.end, "store": s.store or Store.get_default()})
        if created:
            for n in s.needs.all():
                RoleNeed.objects.create(shift=new, role=n.role, needed=n.needed)
            made += 1
    record(Action.CREATE, actor=owner, object_type="schedule.WorkShift", after={"chep_tu": str(source), "sang": str(target),
                                                                                  "so_ca": made})
    return made


def my_schedule(user, today=None):
    today = today or timezone.localdate()
    published = set(WeekPublish.objects.values_list("week_start", flat=True))
    return [a for a in Assignment.objects.filter(user=user, removed_at__isnull=True, shift__date__gte=today)
            .select_related("shift").order_by("shift__date", "shift__start") if week_start(a.shift.date) in published]
