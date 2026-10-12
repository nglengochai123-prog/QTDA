"""Lịch làm tuần cho Chủ quán; đăng ký ca và lịch của tôi cho nhân viên (FR-38, FR-39)."""

from datetime import date, datetime, timedelta

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from apps.accounts.models import User
from apps.accounts.permissions import Cap, capability_required
from apps.audit.models import Action
from apps.audit.services import record

from . import services as sv
from .models import Assignment, WeekPublish, WorkShift

DAY_NAMES = ["Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ nhật"]


def _week(request):
    try:
        value = request.POST.get("tuan") if request.method == "POST" else request.GET.get("tuan")
        return sv.week_start(date.fromisoformat(value or ""))
    except ValueError:
        return sv.next_week()


def _back(week):
    return redirect(f"{reverse('schedule:board')}?tuan={week.isoformat()}")


def _time(value):
    return datetime.strptime(value, "%H:%M").time()


@capability_required(Cap.SCHEDULE_MANAGE)
@require_http_methods(["GET", "POST"])
def board(request):
    week = _week(request)
    if request.method == "POST":
        p, user = request.POST, request.user
        action = p.get("action")
        try:
            if action == "add_shift":
                from apps.core.models import Store

                days = p.getlist("days") or [p.get("date")]
                start, end = _time(p.get("start")), _time(p.get("end"))
                if end <= start:
                    raise ValidationError("Giờ kết thúc phải sau giờ bắt đầu.")
                made = 0
                for d in days:
                    day = date.fromisoformat(d)
                    s, created = WorkShift.objects.get_or_create(
                        date=day, name=p.get("name", "").strip() or "Ca",
                        defaults={"start": start, "end": end, "store": user.store or Store.get_default()})
                    made += created
                    if created:
                        record(Action.CREATE, request=request, obj=s, object_type="schedule.WorkShift", after={"ca": str(s)})
                messages.success(request, f"Đã thêm {made} ca.")
            elif action == "delete_shift":
                s = get_object_or_404(WorkShift, pk=p.get("shift"))
                if s.assignments.filter(removed_at__isnull=True).exists():
                    raise ValidationError("Ca đã có người được xếp; bỏ người ra trước khi xóa ca.")
                record(Action.DELETE, request=request, obj=s, object_type="schedule.WorkShift", before={"ca": str(s)})
                s.delete()
                messages.success(request, "Đã xóa ca.")
            elif action == "set_needs":
                s = get_object_or_404(WorkShift, pk=p.get("shift"))
                for role in sv.ROLES:
                    raw = p.get(f"need_{role}", "").strip()
                    if raw.isdigit():
                        sv.set_need(user, s, role, int(raw), p.get(f"reason_{role}", ""))
                messages.success(request, f"Đã lưu số người cần {s}.")
            elif action == "suggest_needs":
                sv.apply_suggested_needs(week, user)
                messages.success(request, "Đã điền số người cần theo gợi ý; ô Chủ quán đã sửa có lý do được giữ.")
            elif action == "auto_assign":
                made = sv.auto_assign(user, week)
                messages.success(request, f"Đã gợi ý xếp {made} lượt theo đăng ký.")
            elif action == "assign":
                s = get_object_or_404(WorkShift, pk=p.get("shift"))
                person = get_object_or_404(User, pk=p.get("user"))
                sv.assign(user, s, person, p.get("role"))
                messages.success(request, f"Đã xếp {person} vào {s}.")
            elif action == "unassign":
                a = get_object_or_404(Assignment, pk=p.get("assignment"), removed_at__isnull=True)
                sv.unassign(user, a, p.get("reason", ""))
                messages.success(request, f"Đã bỏ {a.user} khỏi {a.shift}.")
            elif action == "copy_prev":
                made = sv.copy_week(user, week - timedelta(days=7), week)
                messages.success(request, f"Đã chép {made} ca từ tuần trước.")
            elif action == "publish":
                if not p.get("confirm"):
                    raise ValidationError("Đánh dấu xác nhận trước khi công bố.")
                sv.publish(user, week)
                messages.success(request, "Đã công bố lịch; mỗi nhân viên nhận lịch của mình trên điện thoại.")
        except (ValidationError, ValueError) as error:
            for m in getattr(error, "messages", [str(error)]):
                messages.error(request, m)
        return _back(week)
    rows, gaps = sv.coverage(week)
    for row in rows:
        row["day"] = DAY_NAMES[row["shift"].date.weekday()]
        for cell in row["cells"]:
            cell["candidates"] = sv.replacements(row["shift"], cell["role"])
    days = [week + timedelta(days=k) for k in range(7)]
    return render(request, "schedule/board.html", {
        "week": week, "week_end": week + timedelta(days=6), "prev": week - timedelta(days=7),
        "next": week + timedelta(days=7), "rows": rows, "gaps": gaps,
        "deadline": sv.deadline_for(week), "published": WeekPublish.objects.filter(week_start=week).first(),
        "days": [(d, DAY_NAMES[d.weekday()]) for d in days], "roles": [(r, sv.ROLE_LABEL[r]) for r in sv.ROLES],
        "total_short": sum(c["short"] for r in rows for c in r["cells"]),
        "total_surplus": sum(c["surplus"] for r in rows for c in r["cells"]),
    })


@capability_required(Cap.SHIFT_REGISTER)
@require_http_methods(["GET", "POST"])
def register(request):
    week = _week(request)
    if request.method == "POST":
        choices = {}
        for key, value in request.POST.items():
            if key.startswith("ca_") and key[3:].isdigit():
                choices[int(key[3:])] = value
        try:
            changed = sv.register(request.user, choices)
            messages.success(request, "Đã gửi đăng ký." if changed else "Không có thay đổi.")
        except ValidationError as error:
            for m in error.messages:
                messages.error(request, m)
        return redirect(f"{reverse('schedule:register')}?tuan={week.isoformat()}")
    roles = sv.user_roles(request.user)
    deadline = sv.deadline_for(week)
    open_ = timezone.now() <= deadline
    groups = []
    for s in sv.week_shifts(week):
        mine = next((r for r in s.registrations.all() if r.user_id == request.user.pk and r.cancelled_at is None), None)
        options = []
        for role in roles:
            need = next((n.needed for n in s.needs.all() if n.role == role), 0)
            count = sum(1 for r in s.registrations.all() if r.role == role and r.cancelled_at is None)
            options.append({"role": role, "label": sv.ROLE_LABEL[role], "need": need, "count": count,
                            "short": need > count})
        if not groups or groups[-1]["date"] != s.date:
            groups.append({"date": s.date, "day": DAY_NAMES[s.date.weekday()], "shifts": []})
        groups[-1]["shifts"].append({"shift": s, "mine": mine.role if mine else "", "options": options})
    return render(request, "schedule/register.html", {
        "week": week, "groups": groups, "deadline": deadline, "open": open_, "roles": roles,
        "prev": week - timedelta(days=7), "next": week + timedelta(days=7)})


@capability_required(Cap.SHIFT_REGISTER)
def mine(request):
    items = sv.my_schedule(request.user)
    for a in items:
        a.day = DAY_NAMES[a.shift.date.weekday()]
        a.role_label = sv.ROLE_LABEL.get(a.role, a.role)
    return render(request, "schedule/mine.html", {"items": items})
