"""Sổ kho: tra cứu biến động tồn theo nguyên vật liệu, loại và khoảng ngày (truy vết từ báo cáo nguyên vật liệu)."""

from datetime import date, datetime, time, timedelta

from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET

from apps.accounts.permissions import Cap, capability_required
from apps.core.paging import paginate

from .models import Ingredient, StockMovement


def _day(value):
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def filter_movements(params):
    qs = StockMovement.objects.select_related("ingredient", "actor")
    if (params.get("nvl") or "").isdigit():
        qs = qs.filter(ingredient_id=int(params["nvl"]))
    if params.get("loai") in StockMovement.Kind.values:
        qs = qs.filter(kind=params["loai"])
    tz = timezone.get_current_timezone()
    start, end = _day(params.get("tu")), _day(params.get("den"))
    if start:
        qs = qs.filter(created_at__gte=timezone.make_aware(datetime.combine(start, time.min), tz))
    if end:
        qs = qs.filter(created_at__lt=timezone.make_aware(datetime.combine(end + timedelta(days=1), time.min), tz))
    return qs


@capability_required(Cap.VIEW_DASHBOARD)
@require_GET
def ledger(request):
    from apps.orders.models import OrderLine

    page, qs = paginate(request, filter_movements(request.GET), per_page=50)
    rows = list(page.object_list)
    # Dòng tiêu hao pha chế ghi mã dòng món; tra ra đơn để mở chi tiết.
    line_ids = [int(m.source_id) for m in rows if m.source_type == "dong_mon" and m.source_id.isdigit()]
    orders = dict(OrderLine.objects.filter(pk__in=line_ids).values_list("pk", "order_id"))
    for m in rows:
        m.order_id = orders.get(int(m.source_id)) if m.source_type == "dong_mon" and m.source_id.isdigit() else None
    return render(request, "inventory/ledger.html", {
        "page": page, "rows": rows, "qs": qs, "f": request.GET, "kinds": StockMovement.Kind.choices,
        "ingredients": Ingredient.objects.order_by("name"),
    })
