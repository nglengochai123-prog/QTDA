"""Chấm công (FR-35) và tải theo khung giờ (FR-36)."""

import uuid
from datetime import datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods

from apps.accounts.models import Role
from apps.accounts.permissions import Cap, capability_required, user_can
from apps.core.dates import parse_day
from apps.core.idempotency import OperationKeyError

from . import timekeeping


def _clock_out_text(result):
    """Câu báo sau khi ra ca: giờ ra và thời gian của lượt vừa xong, để nhân viên thấy ngay có đúng không."""
    from .models import Attendance

    att = Attendance.objects.filter(pk=(result or {}).get("attendance")).first()
    if att is None or att.clock_out is None:
        return "Đã ra ca."
    minutes = max(0, int((att.clock_out - att.clock_in).total_seconds() // 60))
    spent = f"{minutes // 60} giờ {minutes % 60:02d} phút" if minutes >= 60 else f"{minutes} phút"
    return f"Đã ra ca lúc {timezone.localtime(att.clock_out):%H:%M}, lượt này {spent}."


@login_required
@require_http_methods(["GET", "POST"])
def attendance(request):
    """Nhân viên tự chấm công; Chủ quán bổ sung giờ ra (Bảng 5.3)."""
    if not (user_can(request.user, Cap.TIMEKEEPING) or user_can(request.user, Cap.TIMEKEEPING_ADJUST)):
        from apps.accounts.permissions import _deny

        _deny(request, Cap.TIMEKEEPING)
    if request.method == "POST":
        p = request.POST
        try:
            if p.get("action") == "in":
                timekeeping.clock_in(request.user, p.get("operation_key", ""), p.get("role", ""))
                messages.success(request, "Đã vào ca.")
            elif p.get("action") == "out":
                result, _ = timekeeping.clock_out(request.user, p.get("operation_key", ""))
                messages.success(request, _clock_out_text(result))
            elif p.get("action") == "supplement":
                when = timezone.make_aware(datetime.fromisoformat(p.get("clock_out", "")))
                timekeeping.supplement_clock_out(request.user, p.get("attendance"), when, p.get("reason", ""))
                messages.success(request, "Đã bổ sung giờ ra ca.")
        except (ValidationError, OperationKeyError, ValueError) as error:
            for message in (error.messages if isinstance(error, ValidationError) else ["Dữ liệu không hợp lệ."]):
                messages.error(request, message)
        return redirect("staff:attendance")
    from . import today

    context = {"op": uuid.uuid4().hex, "me": None, "board": None}
    if user_can(request.user, Cap.TIMEKEEPING):
        context["me"] = today.staff_card(request.user)
    if user_can(request.user, Cap.TIMEKEEPING_ADJUST):
        context["board"] = today.owner_board()
    return render(request, "staff/attendance.html", context)


@capability_required(Cap.VIEW_WORKLOAD)
@require_GET
def workload(request):
    from apps.orders.workload import day_frames

    day = parse_day(request.GET.get("ngay")) or timezone.localdate()
    from datetime import timedelta

    from apps.core import numbers
    from apps.reports import charts

    data = day_frames(day)
    for frame in data["frames"]:
        frame["presence_list"] = [frame["presence"].get(r, 0) for r in timekeeping.WORK_ROLES]
    frames = data["frames"]
    roles = [Role(r).label for r in timekeeping.WORK_ROLES]
    planned = _planned_by_hour(day)
    short_hours, short_roles = [], []
    for frame in frames:
        hour = timezone.localtime(frame["start"]).hour
        frame["presence_cells"] = []
        for r, label, n in zip(timekeeping.WORK_ROLES, roles, frame["presence_list"]):
            need = planned.get(hour, {}).get(r)
            short = need is not None and n < need
            frame["presence_cells"].append({"label": label, "n": n, "need": need, "short": short,
                                            "gap": (need - n) if short else 0})
            if short and label not in short_roles:
                short_roles.append(label)
        if any(c["short"] for c in frame["presence_cells"]):
            short_hours.append(hour)
    labels = [f"{f['start']:%H}h" for f in frames]
    hours = [f["label"] for f in frames]  # khung cuối ghi 23–24 giờ, không phải 23–00
    cups_chart = charts.stacked_columns(labels, [
        {"name": "Khung đạt chuẩn", "values": [0 if f["overloaded"] else f["cups"] for f in frames], "slot": 1},
        {"name": "Khung quá tải", "values": [f["cups"] if f["overloaded"] else 0 for f in frames], "slot": "critical"}],
        tips=[f"{h}: {f['cups']} ly, {f['orders']} đơn, tải {numbers.fmt(f['load'], 1)}" + (" · quá tải" if f["overloaded"] else "")
              for h, f in zip(hours, frames)], width=charts.WIDE, height=210) if frames else None
    waits = [float(f["median_wait"]) if f["median_wait"] is not None else None for f in frames]
    wait_chart = charts.line(labels, [
        {"name": "Chờ món", "values": waits, "slot": 1},
        {"name": f"Chuẩn {data['standard']} phút", "values": [float(data["standard"])] * len(frames), "slot": "muted",
         "label_end": False}], tip_labels=hours, value_fmt=lambda v: f"{v:.0f} phút" if v is not None else "–",
        width=charts.HALF) if any(w is not None for w in waits) else None
    staff_chart = charts.stacked_columns(labels, [
        {"name": label, "values": [f["presence_list"][k] for f in frames], "slot": k + 1 if k < 3 else "muted"}
        for k, label in enumerate(roles)],
        tips=[f"{h}: " + ", ".join(f"{label} {f['presence_list'][k]}" for k, label in enumerate(roles))
              for h, f in zip(hours, frames)], width=charts.HALF) if frames else None
    return render(request, "staff/workload.html", {
        "day": day, "role_headers": roles, "prev_day": day - timedelta(days=1), "next_day": day + timedelta(days=1),
        "cups_chart": cups_chart, "wait_chart": wait_chart, "staff_chart": staff_chart,
        "overloaded": [h for h, f in zip(hours, frames) if f["overloaded"]], "has_plan": bool(planned),
        "short_frames": _hour_ranges(short_hours), "short_count": len(short_hours), "short_roles": short_roles, **data})


def _hour_ranges(hours):
    """[6, 7, 8, 13] → ["06–09 giờ", "13–14 giờ"]: gộp các khung liền nhau cho thông báo ngắn gọn."""
    out, run = [], []
    for h in sorted(hours):
        if run and h != run[-1] + 1:
            out.append(f"{run[0]:02d}–{run[-1] + 1:02d} giờ")
            run = []
        run.append(h)
    if run:
        out.append(f"{run[0]:02d}–{run[-1] + 1:02d} giờ")
    return out


def _planned_by_hour(day):
    """{giờ: {vị trí: số người cần theo lịch}}: cộng số người cần của các ca trong lịch có mặt ở giờ đó."""
    from apps.schedule import staffing
    from apps.schedule.models import RoleNeed
    from apps.schedule.services import _span

    out = {}
    for need in RoleNeed.objects.filter(shift__date=day).select_related("shift"):
        span = _span(need.shift)
        for hour in range(24):
            if staffing.covers(span, hour):
                cell = out.setdefault(hour, {})
                cell[need.role] = cell.get(need.role, 0) + need.needed
    return out
