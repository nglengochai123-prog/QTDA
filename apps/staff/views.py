"""Chấm công (FR-35) và tải theo khung giờ (FR-36)."""

import uuid
from datetime import date, datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods

from apps.accounts.models import Role
from apps.accounts.permissions import Cap, capability_required, user_can
from apps.core.idempotency import OperationKeyError

from . import timekeeping
from .models import Attendance


@login_required
@require_http_methods(["GET", "POST"])
def attendance(request):
    """Nhân viên tự chấm công; Quản lý ca và Chủ quán bổ sung giờ ra (Bảng 5.3)."""
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
    roles = [(r, Role(r).label) for r in timekeeping.WORK_ROLES if request.user.has_role(r)]
    context = {"current": timekeeping.open_attendance(request.user), "roles": roles, "op": uuid.uuid4().hex,
               "mine": Attendance.objects.filter(user=request.user)[:10]}
    if user_can(request.user, Cap.TIMEKEEPING_ADJUST):
        context["missing"] = timekeeping.missing_clock_out()
        context["today"] = Attendance.objects.filter(clock_in__date=timezone.localdate()).select_related("user")
    return render(request, "staff/attendance.html", context)


@capability_required(Cap.VIEW_WORKLOAD)
@require_GET
def workload(request):
    from apps.orders.workload import day_frames

    try:
        day = date.fromisoformat(request.GET.get("ngay", ""))
    except ValueError:
        day = timezone.localdate()
    data = day_frames(day)
    for frame in data["frames"]:
        frame["presence_list"] = [frame["presence"].get(r, 0) for r in timekeeping.WORK_ROLES]
    return render(request, "staff/workload.html", {"day": day, "role_headers": [Role(r).label for r in timekeeping.WORK_ROLES],
                                                   **data})
