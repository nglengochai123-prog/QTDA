"""Bảng điều khiển và báo cáo theo kỳ (FR-50, FR-52, FR-53, FR-54)."""

from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET

from apps.accounts.permissions import Cap, capability_required, user_can
from apps.core.dates import parse_day, parse_month

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
    start = parse_day(request.GET.get("tu")) or first
    end = parse_day(request.GET.get("den")) or today
    return (start, end) if start <= end else (end, start)


@capability_required(Cap.VIEW_DASHBOARD)
@require_GET
def dashboard(request):
    month = parse_month(request.GET.get("thang"))
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
    context["attention"] = services.attention(context)
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

    lines = services.paid_lines(start, end)
    data = services.revenue(start, end, dim, lines)
    kind, chart = insights.dimension_chart(data)
    return render(request, "reports/revenue.html", {
        "start": start, "end": end, "dims": services.DIMENSIONS.items(), "presets": presets(timezone.localdate()),
        "period_qs": f"theo={dim}", "sales": insights.sales(start, end, wide=True, lines=lines), "dim_kind": kind, "dim_chart": chart,
        **data})


@capability_required(Cap.EXCEPTION_REVIEW)
@require_GET
def revenue_control(request):
    start, end = _period(request)
    return render(request, "reports/revenue_control.html", {"start": start, "end": end,
                                                            "presets": presets(timezone.localdate()),
                                                            **services.revenue_control(start, end)})


@capability_required(Cap.VIEW_DASHBOARD)
@require_GET
def materials(request):
    start, end = _period(request)
    return render(request, "reports/materials.html", {"start": start, "end": end, "presets": presets(timezone.localdate()),
                                                      **services.materials(start, end)})


@capability_required(Cap.VIEW_DASHBOARD)
@require_GET
def inventory(request):
    from . import inventory as inv

    start, end = _period(request)
    today = timezone.localdate()
    return render(request, "reports/inventory.html", {"start": start, "end": end, "presets": presets(today),
                                                      "show_value": True, **inv.dashboard(start, end, today)})


@capability_required(Cap.VIEW_FINANCIALS)
def profit(request):
    """Lãi lỗ theo tháng và chi phí tháng do Chủ quán nhập (Hai, 28/11/2026)."""
    from datetime import timedelta

    from django.contrib import messages
    from django.db import transaction
    from django.shortcuts import redirect

    from apps.audit.models import Action
    from apps.audit.services import record
    from apps.core import numbers
    from apps.core.models import Store

    from . import profit as pl
    from .models import MonthlyExpense

    today = timezone.localdate()
    first = parse_month(request.GET.get("thang") or request.POST.get("thang")) or today.replace(day=1)
    back = f"{request.path}?thang={first:%Y-%m}"
    if request.method == "POST":
        action = request.POST.get("action")
        with transaction.atomic():
            if action == "add":
                try:
                    amount = numbers.whole(request.POST.get("amount", ""))
                except Exception:  # noqa: BLE001
                    amount = 0
                category = request.POST.get("category", "")
                if amount <= 0 or category not in MonthlyExpense.Category.values:
                    messages.error(request, "Chọn loại chi phí và nhập số tiền lớn hơn 0.")
                    return redirect(back)
                e = MonthlyExpense.objects.create(store=Store.get_default(), month=first, category=category,
                                                  amount=amount, note=request.POST.get("note", "")[:255],
                                                  created_by=request.user)
                record(Action.CREATE, request=request, obj=e, after={"thang": f"{first:%m/%Y}",
                                                                     "loai": e.get_category_display(), "so_tien": amount,
                                                                     "ghi_chu": e.note})
                messages.success(request, f"Đã ghi {e.get_category_display().lower()} {numbers.fmt(amount, 0)} đ.")
            elif action == "delete":
                e = MonthlyExpense.objects.filter(pk=request.POST.get("expense"), month=first).first()
                if e is not None:
                    record(Action.DELETE, request=request, obj=e, before={"loai": e.get_category_display(),
                                                                          "so_tien": e.amount, "ghi_chu": e.note})
                    e.delete()
                    messages.success(request, "Đã bỏ khoản chi phí.")
            elif action == "copy_prev":
                prev = (first - timedelta(days=1)).replace(day=1)
                rows = list(MonthlyExpense.objects.filter(month=prev))
                if MonthlyExpense.objects.filter(month=first).exists() or not rows:
                    messages.error(request, "Tháng này đã có chi phí, hoặc tháng trước chưa có khoản nào để chép.")
                else:
                    for r in rows:
                        MonthlyExpense.objects.create(store=r.store, month=first, category=r.category, amount=r.amount,
                                                      note=r.note, created_by=request.user)
                    record(Action.CREATE, request=request, object_type="reports.MonthlyExpense",
                           after={"thang": f"{first:%m/%Y}", "chep_tu": f"{prev:%m/%Y}", "so_khoan": len(rows)})
                    messages.success(request, f"Đã chép {len(rows)} khoản từ tháng {prev:%m/%Y}; sửa số nếu khác.")
        return redirect(back)
    data = pl.month(first, today)
    prev_first = (first - timedelta(days=1)).replace(day=1)
    prev = pl.month(prev_first, today)
    nxt = (first + timedelta(days=32)).replace(day=1)
    return render(request, "reports/profit.html", {
        **data, "prev": prev, "prev_month": prev_first, "next_month": nxt if nxt <= today else None,
        "categories": MonthlyExpense.Category.choices,
    })
