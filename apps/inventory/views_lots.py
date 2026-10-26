"""Kho theo lô: danh sách lô, chi tiết lô của một nguyên liệu, phiếu lấy hàng, hủy lô, sửa hạn."""

import uuid

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from apps.accounts.permissions import Cap, capability_required, user_can
from apps.reports import charts

from . import lots, operations as ops
from .models import Ingredient, LotDraw, StockLot
from .views import _ingredients, _run

FILTERS = [("", "Tất cả"), (lots.EXPIRED, "Quá hạn"), (lots.NEAR, "Sắp hết hạn"), ("nguy_co", "Dự kiến bỏ"),
           (lots.UNKNOWN, "Chưa rõ hạn")]


def _all_lot_views(items):
    view = lots.overview(items)
    names = {i.pk: i for i in items}
    rows = []
    for ing_id, data in view.items():
        for v in data["lots"]:
            v.ingredient_obj = names[ing_id]
            rows.append(v)
    return view, rows


@capability_required(Cap.STOCK_OPERATIONS)
@require_GET
def lot_list(request):
    items = list(_ingredients())
    view, rows = _all_lot_views(items)
    state = request.GET.get("trang-thai", "")
    ing = request.GET.get("nvl", "")
    counts = {key: 0 for key, _ in FILTERS}
    for v in rows:
        counts[""] += 1
        if v.state in counts:
            counts[v.state] += 1
        if v.waste > 0 and v.state != lots.EXPIRED:
            counts["nguy_co"] += 1
    if state == "nguy_co":
        rows = [v for v in rows if v.waste > 0 and v.state != lots.EXPIRED]
    elif state:
        rows = [v for v in rows if v.state == state]
    if ing.isdigit():
        rows = [v for v in rows if v.ingredient_id == int(ing)]
    order = {lots.EXPIRED: 0, lots.NEAR: 1, lots.UNKNOWN: 2, lots.OK: 3}
    rows.sort(key=lambda v: (order.get(v.state, 4), v.days_left if v.days_left is not None else 10**6,
                             v.ingredient_obj.name, v.rank))
    for v in rows:
        v.op = uuid.uuid4().hex
    return render(request, "inventory/lots.html", {
        "rows": rows, "filters": [(k, l, counts[k]) for k, l in FILTERS], "state": state, "ing": ing,
        "ingredients": items, "show_value": user_can(request.user, Cap.STOCK_CONFIRM_ORDERING),
        "totals": {"value": sum(d["value"] for d in view.values()),
                   "expired_value": sum(d["expired_value"] for d in view.values()),
                   "at_risk_value": sum(d["at_risk_value"] for d in view.values()),
                   "lots": sum(len(d["lots"]) for d in view.values())},
    })


@capability_required(Cap.STOCK_OPERATIONS)
@require_GET
def lot_detail(request, ingredient_id):
    ing = get_object_or_404(Ingredient.objects.select_related("stock"), pk=ingredient_id)
    data = lots.overview([ing])[ing.pk]
    for v in data["lots"]:
        v.op = uuid.uuid4().hex
    draws = (LotDraw.objects.filter(lot__ingredient=ing).select_related("lot", "movement", "movement__actor")
             .order_by("-created_at", "-id")[:60])
    used = (StockLot.objects.filter(ingredient=ing, remaining=0).select_related("supplier")
            .order_by("-received_at")[:10])
    return render(request, "inventory/lot_detail.html", {
        "ing": ing, "data": data, "draws": draws, "used": used, "today": timezone.localdate(),
        "timeline": charts.lot_timeline(data["lots"], ing.get_unit_display(), timezone.localdate()),
        "show_value": user_can(request.user, Cap.STOCK_CONFIRM_ORDERING), "rules": ing._meta.get_field("issue_rule"),
    })


@capability_required(Cap.STOCK_OPERATIONS)
@require_GET
def pick_list(request):
    """Phiếu lấy hàng cho quầy: mỗi nguyên liệu lấy lô nào trước, lô nào quá hạn phải để riêng và hủy."""
    items = [i for i in _ingredients() if i.stock.physical > 0]
    view = lots.overview(items)
    cards = []
    for i in items:
        d = view[i.pk]
        if not d["lots"]:
            continue
        nxt = [v for v in d["lots"] if v.state != lots.EXPIRED]
        for v in d["expired"]:
            v.op = uuid.uuid4().hex
        cards.append({"ingredient": i, "pick": d["pick"], "then": nxt[1] if len(nxt) > 1 else None,
                      "expired": d["expired"], "near": d["near"], "count": len(d["lots"])})
    urgent = lambda c: (0 if c["expired"] else 1 if c["pick"] and c["pick"].state == lots.NEAR else 2,
                        c["ingredient"].name)
    cards.sort(key=urgent)
    return render(request, "inventory/pick_list.html", {"cards": cards, "today": timezone.localdate()})


@capability_required(Cap.STOCK_OPERATIONS)
@require_POST
def dispose(request, lot_id):
    p = request.POST
    result = _run(request, lambda: ops.dispose_lot(request.user, p.get("operation_key", ""), lot_id, p.get("note", "")),
                  "")
    if result:
        lot = StockLot.objects.get(pk=lot_id)
        messages.success(request, f"Đã hủy lô {lot.code} và ghi hao hụt; tồn vật lý đã giảm.")
    return redirect(p.get("next") or "inventory:lots")


@capability_required(Cap.STOCK_OPERATIONS)
@require_POST
def update(request, lot_id):
    p = request.POST
    _run(request, lambda: ops.update_lot(request.user, lot_id, p.get("expiry_date") or None, p.get("supplier_lot")),
         "Đã lưu thông tin lô.")
    lot = get_object_or_404(StockLot, pk=lot_id)
    return redirect("inventory:lot_detail", lot.ingredient_id)
