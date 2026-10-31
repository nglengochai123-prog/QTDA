"""Sổ kho: tra cứu biến động tồn theo nguyên vật liệu, loại và khoảng ngày (truy vết từ báo cáo nguyên vật liệu)."""

from datetime import datetime, time, timedelta

from django.db.models import Q, Sum
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET

from apps.accounts.permissions import Cap, capability_required
from apps.core.dates import parse_day as _day
from apps.core.paging import paginate

from .models import Ingredient, StockMovement


def filter_movements(params):
    qs = StockMovement.objects.select_related("ingredient", "actor")
    if (params.get("nvl") or "").isdigit():
        qs = qs.filter(ingredient_id=int(params["nvl"]))
    if params.get("loai") == "nhap_va_lam":
        qs = qs.filter(Q(kind=StockMovement.Kind.RECEIPT) | Q(kind=StockMovement.Kind.PRODUCE, quantity__gt=0))
    elif params.get("loai") == "tieu_hao_va_lam":
        qs = qs.filter(Q(kind=StockMovement.Kind.CONSUME) | Q(kind=StockMovement.Kind.PRODUCE, quantity__lt=0))
    elif params.get("loai") in StockMovement.Kind.values:
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

    movements = filter_movements(request.GET)
    page, qs = paginate(request, movements, per_page=50)
    # Cộng biến động chỉ có nghĩa khi cùng một nguyên vật liệu (cùng đơn vị); dùng để khớp với số trên báo cáo.
    total = movements.aggregate(s=Sum("quantity"))["s"] if (request.GET.get("nvl") or "").isdigit() else None
    rows = list(page.object_list)
    # Dòng tiêu hao pha chế ghi mã dòng món; tra ra đơn để mở chi tiết.
    line_ids = [int(m.source_id) for m in rows if m.source_type == "dong_mon" and m.source_id.isdigit()]
    orders = dict(OrderLine.objects.filter(pk__in=line_ids).values_list("pk", "order_id"))
    for m in rows:
        m.order_id = orders.get(int(m.source_id)) if m.source_type == "dong_mon" and m.source_id.isdigit() else None
    return render(request, "inventory/ledger.html", {
        "page": page, "rows": rows, "qs": qs, "f": request.GET, "kinds": list(StockMovement.Kind.choices) + [("nhap_va_lam", "Nhập và làm ra"), ("tieu_hao_va_lam", "Tiêu hao món và làm mẻ")],
        "ingredients": Ingredient.objects.order_by("name"), "total": total,
        "unit": rows[0].ingredient.get_unit_display() if rows else "",
    })
