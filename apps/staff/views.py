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
                timekeeping.clock_out(request.user, p.get("operation_key", ""))
                messages.success(request, "Đã ra ca.")
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
    for frame in frames:
        frame["presence_cells"] = [{"label": label, "n": n} for label, n in zip(roles, frame["presence_list"])]
    labels = [f"{f['start']:%H}h" for f in frames]
    hours = [f"{f['start']:%H}–{f['end']:%H} giờ" for f in frames]
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
        "overloaded": [h for h, f in zip(hours, frames) if f["overloaded"]], **data})
