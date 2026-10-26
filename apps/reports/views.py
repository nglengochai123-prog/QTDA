"""Bảng điều khiển và báo cáo theo kỳ (FR-50, FR-52, FR-53, FR-54)."""

from datetime import date

from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET

from apps.accounts.permissions import Cap, capability_required, user_can

from . import services


def presets(today):
    """Các kỳ chọn nhanh ở hàng bộ lọc: (nhãn, từ, đến)."""
    from datetime import timedelta

    first, _ = services.month_bounds(today)
    prev_last = first - timedelta(days=1)
    return [("7 ngày", today - timedelta(days=6), today), ("30 ngày", today - timedelta(days=29), today),
            ("Tháng này", first, today), ("Tháng trước", prev_last.replace(day=1), prev_last),
            ("90 ngày", today - timedelta(days=89), today)]


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
    month = None
    try:
        month = date.fromisoformat(request.GET.get("thang", "") + "-01")
    except ValueError:
        pass
    fallback = None
    if month is None:
        # Tháng hiện tại chưa có đơn đã thanh toán thì mở tháng gần nhất có đơn (ví dụ dữ liệu lịch sử đã nhập).
        from apps.orders.models import Payment

        today = timezone.localdate()
        first = today.replace(day=1)
        valid = Payment.objects.filter(status=Payment.Status.VALID)
        if not valid.filter(created_at__date__gte=first).exists():
            last = valid.order_by("-created_at").values_list("created_at", flat=True).first()
            if last is not None:
                month = fallback = timezone.localtime(last).date()
    context = services.dashboard(month=month)
    context["fallback_month"] = fallback
    context["ops"] = services.shift_panel(request.user)
    context["is_owner"] = request.user.is_owner
    context["can_review"] = user_can(request.user, Cap.EXCEPTION_REVIEW)
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
    from . import insights

    data = services.revenue(start, end, dim)
    kind, chart = insights.dimension_chart(data)
    return render(request, "reports/revenue.html", {
        "start": start, "end": end, "dims": services.DIMENSIONS.items(), "presets": presets(timezone.localdate()),
        "extra": f"theo={dim}", "sales": insights.sales(start, end, wide=True), "dim_kind": kind, "dim_chart": chart,
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


@capability_required(Cap.VIEW_DASHBOARD)
@require_GET
def inventory(request):
    from . import inventory as inv

    start, end = _period(request)
    today = timezone.localdate()
    return render(request, "reports/inventory.html", {"start": start, "end": end, "presets": presets(today),
                                                      "show_value": True, **inv.dashboard(start, end, today)})
