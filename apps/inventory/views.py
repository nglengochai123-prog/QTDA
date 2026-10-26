import uuid
from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db.models import Count, Sum
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.accounts.permissions import Cap, capability_required, user_can
from apps.core.idempotency import OperationKeyError

from . import operations as ops
from .models import (ConsumptionCheck, Ingredient, Payable, PurchaseOrder, QuickReport, ShortageCase, StockCount, Supplier,
                     SupplierPayment, Waste)
from .stock import ensure_stock_rows


def _run(request, fn, ok):
    try:
        result = fn()
    except (ValidationError, OperationKeyError, ValueError) as error:
        for message in (error.messages if isinstance(error, ValidationError) else [str(error)]):
            messages.error(request, message)
        return None
    if ok:
        messages.success(request, ok)
    return result


def _ingredients():
    ensure_stock_rows()
    return Ingredient.objects.filter(is_active=True).select_related("stock").order_by("-is_critical", "name")


@capability_required(Cap.STOCK_OPERATIONS)
def stock_list(request):
    from . import lots

    items = list(_ingredients())
    view = lots.overview(items)
    rows, totals = [], {"value": 0, "expired": 0, "expired_value": 0, "near": 0, "low": 0, "at_risk_value": 0}
    for i in items:
        d = view[i.pk]
        low = i.stock.available <= i.safety_stock and i.safety_stock > 0
        state = ("expired" if d["expired"] else "low" if low else "near" if d["near"] else
                 "risk" if d["at_risk"] > 0 else "ok")
        rows.append({"i": i, "d": d, "low": low, "state": state})
        totals["value"] += d["value"]
        totals["expired"] += len(d["expired"])
        totals["expired_value"] += d["expired_value"]
        totals["near"] += len(d["near"])
        totals["low"] += int(low)
        totals["at_risk_value"] += d["at_risk_value"]
    q = request.GET.get("loc", "")
    # Lọc theo từng điều kiện (một nguyên liệu vừa có lô quá hạn vừa dưới tồn an toàn hiện ở cả hai bộ lọc).
    tests = {"expired": lambda r: r["d"]["expired"], "low": lambda r: r["low"], "near": lambda r: r["d"]["near"],
             "risk": lambda r: r["d"]["at_risk"] > 0}
    if q in tests:
        rows = [r for r in rows if tests[q](r)]
    return render(request, "inventory/stock.html", {
        "rows": rows, "totals": totals, "loc": q, "quick_reports": ops.open_quick_reports(),
        "can_confirm": user_can(request.user, Cap.STOCK_CONFIRM_ORDERING),
        "can_ack": user_can(request.user, Cap.VIEW_WORKLOAD), "has_items": bool(items),
        "pending_counts": StockCount.objects.filter(status=StockCount.Status.PENDING).count(),
    })


@capability_required(Cap.STOCK_OPERATIONS)
@require_http_methods(["GET", "POST"])
def quick_report(request):
    if request.method == "POST":
        p = request.POST
        result = _run(request, lambda: ops.quick_report(request.user, p.get("operation_key", ""), p.get("ingredient"),
                                                        p.get("level"), p.get("left") or None), "")
        if result:
            data, _ = result
            messages.success(request, "Đã báo. Chủ quán nhận được ngay." +
                             (" Đã ghi một trường hợp thiếu nguyên liệu hôm nay." if data["shortage_recorded"] else ""))
        return redirect("inventory:quick_report")
    items = list(_ingredients())
    for i in items:
        i.op_low, i.op_out = uuid.uuid4().hex, uuid.uuid4().hex
    return render(request, "inventory/quick_report.html", {"ingredients": items})


@capability_required(Cap.VIEW_WORKLOAD)
@require_POST
def acknowledge(request, report_id):
    _run(request, lambda: ops.acknowledge(request.user, report_id, request.POST.get("note", "")), "Đã ghi xử lý.")
    return redirect(request.POST.get("next") or "inventory:stock")


@login_required
@require_GET
def quick_report_count(request):
    if not user_can(request.user, Cap.ORDER_ADJUST_APPROVE):
        return JsonResponse({"count": 0, "items": []})
    reports = ops.open_quick_reports()
    return JsonResponse({"count": reports.count(),
                         "items": [f"{r.ingredient.name}: {r.get_level_display()}" for r in reports[:3]]})


@capability_required(Cap.STOCK_OPERATIONS)
@require_http_methods(["GET", "POST"])
def count(request):
    if request.method == "POST":
        p = request.POST
        if p.get("action") in ("confirm", "reject"):
            _run(request, lambda: ops.confirm_count(request.user, p.get("count"), p.get("action") == "confirm"),
                 "Đã ghi xác nhận kiểm kê.")
        else:
            result = _run(request, lambda: ops.submit_count(request.user, p.get("operation_key", ""), p.get("ingredient"),
                                                            p.get("counted", ""), p.get("reason", "")), "")
            if result:
                data, _ = result
                messages.success(request, f"Đã ghi kiểm kê, chênh lệch {data['difference']} ({data['percent']}%)."
                                 + (" Chờ Chủ quán xác nhận." if data["pending"] else " Tồn đã điều chỉnh."))
        return redirect("inventory:count")
    items = list(_ingredients())
    for i in items:
        i.op = uuid.uuid4().hex
    return render(request, "inventory/count.html", {
        "ingredients": items, "can_confirm": user_can(request.user, Cap.STOCK_CONFIRM_ORDERING),
        "pending": StockCount.objects.filter(status=StockCount.Status.PENDING).select_related("ingredient", "counter"),
    })


@capability_required(Cap.STOCK_OPERATIONS)
@require_http_methods(["GET", "POST"])
def waste(request):
    if request.method == "POST":
        p = request.POST
        result = _run(request, lambda: ops.record_waste(
            request.user, p.get("operation_key", ""), p.get("ingredient"), p.get("quantity", ""), p.get("reason", ""),
            p.get("note", ""), is_one_off=bool(p.get("one_off")), lot_id=p.get("lot") or None), "")
        if result:
            data, _ = result
            messages.success(request, "Đã ghi hao hụt; tồn vật lý đã giảm"
                             + (f" (trừ lô {', '.join(data['lots'])})." if data.get("lots") else "."))
        return redirect("inventory:waste")
    from .models import StockLot

    open_lots = (StockLot.objects.filter(remaining__gt=0, ingredient__is_active=True).select_related("ingredient")
                 .order_by("ingredient__name", "expiry_date", "received_at"))
    return render(request, "inventory/waste.html", {"is_owner": request.user.is_owner,
        "ingredients": _ingredients(), "reasons": Waste.Reason.choices, "operation_key": uuid.uuid4().hex,
        "recent": Waste.objects.select_related("ingredient", "actor")[:10], "open_lots": open_lots,
        "today": timezone.localdate(),
    })


@capability_required(Cap.STOCK_OPERATIONS)
@require_http_methods(["GET", "POST"])
def receipt(request):
    if request.method == "POST":
        p = request.POST
        lines = []
        for i in range(int(p.get("rows", 0) or 0)):
            if p.get(f"ingredient_{i}") and p.get(f"quantity_{i}"):
                line = {"ingredient": int(p.get(f"ingredient_{i}")), "quantity": p.get(f"quantity_{i}"),
                        "unit_price": p.get(f"price_{i}") or 0, "purchase_order": p.get(f"po_{i}") or None}
                if p.get(f"expiry_{i}"):
                    line["expiry_date"] = p.get(f"expiry_{i}")
                if p.get(f"lot_{i}"):
                    line["supplier_lot"] = p.get(f"lot_{i}")
                lines.append(line)
        result = _run(request, lambda: ops.create_receipt(
            request.user, p.get("operation_key", ""), p.get("supplier"), lines, p.get("payment_type", ""),
            invoice_photo=request.FILES.get("invoice_photo"), due_days=p.get("due_days") or 7,
            paid_source=p.get("source") or SupplierPayment.Source.TRANSFER), "")
        if result:
            data, _ = result
            messages.success(request, f"Đã lưu phiếu nhập {data['code']}, giá trị {data['total']:,} đ; tồn vật lý đã tăng. "
                             .replace(",", ".") + f"Mã lô: {', '.join(data.get('lots') or [])}.")
            for warning in data.get("warnings") or []:
                messages.warning(request, warning)
        return redirect("inventory:receipt")
    return render(request, "inventory/receipt.html", {
        "suppliers": Supplier.objects.filter(is_active=True), "ingredients": _ingredients(), "rows": range(4),
        "open_pos": PurchaseOrder.objects.exclude(status__in=[PurchaseOrder.Status.DELIVERED,
                                                              PurchaseOrder.Status.CANCELLED]).select_related("ingredient", "supplier"),
        "sources": SupplierPayment.Source.choices, "operation_key": uuid.uuid4().hex,
    })


@capability_required(Cap.STOCK_CONFIRM_ORDERING)
@require_http_methods(["GET", "POST"])
def purchase_orders(request):
    if request.method == "POST":
        p = request.POST
        if p.get("action") == "reschedule":
            _run(request, lambda: ops.reschedule(request.user, p.get("po"), date.fromisoformat(p.get("expected_date"))),
                 "Đã cập nhật ngày giao.")
        else:
            _run(request, lambda: ops.create_purchase_order(request.user, p.get("supplier"), p.get("ingredient"),
                                                            p.get("quantity", ""), date.fromisoformat(p.get("expected_date")),
                                                            p.get("note", ""), operation_key=p.get("operation_key", "")),
                 "Đã ghi lần đặt hàng.")
        return redirect("inventory:purchase_orders")
    return render(request, "inventory/purchase_orders.html", {
        "orders": PurchaseOrder.objects.select_related("supplier", "ingredient").order_by("status", "expected_date"),
        "suppliers": Supplier.objects.filter(is_active=True), "ingredients": _ingredients(),
        "today": timezone.localdate(), "operation_key": uuid.uuid4().hex,
    })


@capability_required(Cap.STOCK_CONFIRM_ORDERING)
@require_http_methods(["GET", "POST"])
def payables(request):
    if request.method == "POST":
        p = request.POST
        _run(request, lambda: ops.pay_supplier(request.user, p.get("payable"), p.get("amount", ""), p.get("source", ""),
                                               operation_key=p.get("operation_key", "")), "Đã ghi thanh toán.")
        return redirect("inventory:payables")
    items = [x for x in Payable.objects.select_related("supplier", "receipt").prefetch_related("payments")
             if not x.is_paid]
    for item in items:
        item.op = uuid.uuid4().hex
    return render(request, "inventory/payables.html", {"items": items, "sources": SupplierPayment.Source.choices,
                                                       "today": timezone.localdate()})


@capability_required(Cap.VIEW_DASHBOARD)
@require_GET
def report(request):
    """Báo cáo nguyên vật liệu: hao hụt theo lý do, hủy sau pha chế, kiểm kê, trường hợp thiếu (FR-26, FR-27)."""
    from apps.orders.models import PostPrepCancellation

    now = timezone.localdate()
    try:  # ?thang=YYYY-MM để khớp tháng đang xem ở bảng điều khiển
        now = date.fromisoformat(request.GET.get("thang", "") + "-01")
    except ValueError:
        pass
    month = {"created_at__year": now.year, "created_at__month": now.month}
    waste = (Waste.objects.filter(**month).values("ingredient__name", "ingredient__unit", "reason")
             .annotate(total=Sum("quantity")).order_by("ingredient__name"))
    reason_labels = dict(Waste.Reason.choices)
    for w in waste:
        w["reason_label"] = reason_labels[w["reason"]]
    post_prep = {}
    names = {i.pk: i for i in Ingredient.objects.all()}
    for ppc in PostPrepCancellation.objects.filter(**month):
        for ing_id, qty in ppc.usage.items():
            post_prep[int(ing_id)] = post_prep.get(int(ing_id), 0) + float(qty)
    shortage_month = ShortageCase.objects.filter(day__year=now.year, day__month=now.month)
    return render(request, "inventory/report.html", {
        "month": f"{now:%m/%Y}", "month_value": f"{now:%Y-%m}", "waste": waste,
        "post_prep": [(names[k], v) for k, v in sorted(post_prep.items()) if k in names],
        "counts": StockCount.objects.filter(**month).select_related("ingredient", "counter")[:50],
        "shortage_total": shortage_month.count(),
        "shortage_by_day": shortage_month.values("day").annotate(n=Count("id")).order_by("-day"),
        "shortage_by_ingredient": shortage_month.values("ingredient__name").annotate(n=Count("id")).order_by("-n"),
        "shortages": shortage_month.select_related("ingredient"),
        "consumption": ConsumptionCheck.objects.filter(**month).select_related("ingredient", "from_count", "to_count"),
    })
