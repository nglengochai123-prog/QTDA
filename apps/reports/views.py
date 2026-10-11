"""Bảng điều khiển và báo cáo theo kỳ (FR-50, FR-52, FR-53, FR-54)."""

from datetime import date

from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET

from apps.accounts.permissions import Cap, capability_required

from . import services


def _period(request):
    today = timezone.localdate()
    first, _ = services.month_bounds(today)
    try:
        start = date.fromisoformat(request.GET.get("tu", ""))
    except ValueError:
        start = first
    try:
        end = date.fromisoformat(request.GET.get("den", ""))
    except ValueError:
        end = today
    return (start, end) if start <= end else (end, start)


@capability_required(Cap.VIEW_DASHBOARD)
@require_GET
def dashboard(request):
    context = services.dashboard()
    context["ops"] = services.shift_panel(request.user)
    context["is_owner"] = request.user.is_owner
    return render(request, "reports/dashboard.html", context)


@capability_required(Cap.VIEW_DASHBOARD)
@require_GET
def revenue(request):
    start, end = _period(request)
    if request.GET.get("xuat") == "excel":
        response = HttpResponse(services.revenue_xlsx(start, end),
                                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        response["Content-Disposition"] = f'attachment; filename="doanh-thu-{start:%Y%m%d}-{end:%Y%m%d}.xlsx"'
        return response
    dim = request.GET.get("theo", "ngay")
    if dim not in services.DIMENSIONS:
        dim = "ngay"
    data = services.revenue(start, end, dim)
    return render(request, "reports/revenue.html", {"start": start, "end": end, "dims": services.DIMENSIONS.items(),
                                                    **data})


@capability_required(Cap.EXCEPTION_REVIEW)
@require_GET
def revenue_control(request):
    start, end = _period(request)
    return render(request, "reports/revenue_control.html", {"start": start, "end": end,
                                                            **services.revenue_control(start, end)})


@capability_required(Cap.VIEW_DASHBOARD)
@require_GET
def materials(request):
    start, end = _period(request)
    return render(request, "reports/materials.html", {"start": start, "end": end, **services.materials(start, end)})
