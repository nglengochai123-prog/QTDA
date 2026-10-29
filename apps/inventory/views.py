import uuid
from collections import OrderedDict
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db.models import Count, Sum
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.template.defaultfilters import floatformat
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.accounts.permissions import Cap, capability_required, user_can
from apps.core import errors, links
from apps.core.dates import parse_month
from apps.core.idempotency import OperationKeyError

from . import operations as ops
from .models import (ConsumptionCheck, Ingredient, IngredientKind, Payable, PurchaseOrder, ShortageCase, StockCount, StockMovement,
                     Supplier, SupplierPayment, Unit, Waste)
from .stock import ensure_stock_rows


RECEIPT_ROWS = 8  # số dòng tối đa của một phiếu nhập trên màn hình


def _run(request, fn, ok):
    try:
        result = fn()
    except (ValidationError, OperationKeyError, ValueError) as error:
        for message in errors.messages_of(error):
            messages.error(request, message)
        return None
    if ok:
        messages.success(request, ok)
    return result


def _ingredients():
    ensure_stock_rows()
    return Ingredient.objects.filter(is_active=True).select_related("stock").order_by("-is_critical", "name")


def _purchasable():
    """Nguyên liệu mua vào: bán thành phẩm do quán tự làm không có trên phiếu nhập và đơn đặt."""
    return _ingredients().exclude(kind=IngredientKind.SEMI)


@capability_required(Cap.STOCK_OPERATIONS)
def stock_list(request):
    from . import lots

    items = list(_ingredients())
    view = lots.overview(items)
    rows, totals = [], {"value": 0, "expired": 0, "expired_value": 0, "near": 0, "low": 0, "at_risk_value": 0}
    empty = [i.pk for i in items if i.stock.available <= 0]
    moved = set(StockMovement.objects.filter(ingredient_id__in=empty).values_list("ingredient_id", flat=True)
                .distinct()) if empty else set()
    for i in items:
        d = view[i.pk]
        # Hết sạch (kể cả nguyên liệu chưa ghi tồn đầu kỳ) cũng là dưới mức an toàn, dù chưa đặt mức an toàn.
        out = i.stock.available <= 0
        low = out or (i.stock.available <= i.safety_stock and i.safety_stock > 0)
        state = ("expired" if d["expired"] else "out" if out else "low" if low else "near" if d["near"] else
                 "risk" if d["at_risk"] > 0 else "ok")
        rows.append({"i": i, "d": d, "low": low, "state": state, "never": i.pk not in moved})
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
        "can_open": user_can(request.user, Cap.MASTER_INVENTORY),
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
    return render(request, "inventory/quick_report.html", {"ingredients": items,
                                                           "can_setup": user_can(request.user, Cap.MASTER_INVENTORY)})


@capability_required(Cap.VIEW_WORKLOAD)
@require_POST
def acknowledge(request, report_id):
    _run(request, lambda: ops.acknowledge(request.user, report_id, request.POST.get("note", "")), "Đã ghi xử lý.")
    return links.back(request, "inventory:stock")


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
                count = StockCount.objects.select_related("ingredient").get(pk=data["count"])
                unit = count.ingredient.get_unit_display()
                if not count.difference:
                    text = "khớp sổ, không cần điều chỉnh."
                else:
                    sign = "+" if count.difference > 0 else "−"
                    text = (f"lệch {sign}{floatformat(abs(count.difference), '-2g')} {unit} ({data['percent'].replace('.', ',')}%), "
                            + ("chờ Chủ quán xác nhận." if data["pending"] else "tồn đã điều chỉnh."))
                messages.success(request, f"Đã ghi kiểm kê {count.ingredient.name}: {text}")
        return redirect("inventory:count")
    from apps.core import params

    from .models import RecountRequest

    items = list(_ingredients())
    start = timezone.make_aware(datetime.combine(timezone.localdate(), time.min))
    last = {}
    for c in StockCount.objects.filter(created_at__gte=start - timedelta(days=30)).order_by("-created_at"):
        last.setdefault(c.ingredient_id, c)
    asked = set(RecountRequest.objects.filter(done_at__isnull=True).values_list("ingredient_id", flat=True))
    for i in items:
        i.op = uuid.uuid4().hex
        i.last = last.get(i.pk)
        i.today = bool(i.last and i.last.created_at >= start and i.last.status != StockCount.Status.REJECTED)
        i.asked = i.pk in asked
    critical = [i for i in items if i.is_critical]
    pending = list(StockCount.objects.filter(status=StockCount.Status.PENDING).select_related("ingredient", "counter"))
    for c in pending:
        c.later = ops.later_count(c)
    return render(request, "inventory/count.html", {
        "critical": critical, "others": [i for i in items if not i.is_critical],
        "critical_left": sum(1 for i in critical if not i.today), "done": sum(1 for i in items if i.today),
        "total": len(items), "threshold": params.get("count_threshold_percent"),
        "can_confirm": user_can(request.user, Cap.STOCK_CONFIRM_ORDERING),
        "can_open": user_can(request.user, Cap.MASTER_INVENTORY),
        "pending": pending,
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
        "can_report": user_can(request.user, Cap.VIEW_DASHBOARD),
        "ingredients": _ingredients(), "reasons": Waste.Reason.choices, "operation_key": uuid.uuid4().hex,
        "recent": Waste.objects.select_related("ingredient", "actor")[:10], "open_lots": open_lots,
        "today": timezone.localdate(), "can_setup": user_can(request.user, Cap.MASTER_INVENTORY),
    })


@capability_required(Cap.STOCK_OPERATIONS)
@require_http_methods(["GET", "POST"])
def semi(request):
    """Làm bán thành phẩm: ghi mẻ đã làm, xem tồn và số mẻ nên làm."""
    from apps.forecast.planning import production_suggestions

    from .models import SemiBatch

    if request.method == "POST":
        p = request.POST
        result = _run(request, lambda: ops.produce_semi(request.user, p.get("operation_key", ""), p.get("product"),
                                                        p.get("batches", ""), p.get("actual") or None,
                                                        p.get("note", "")), "")
        if result:
            data, _ = result
            messages.success(request, "Đã ghi mẻ: nguyên liệu gốc đã trừ, bán thành phẩm đã vào kho"
                             + (f" (lô {data['lot']})." if data.get("lot") else "."))
        return redirect("inventory:semi")
    rows = production_suggestions()
    for r in rows:
        r["operation_key"] = uuid.uuid4().hex
    return render(request, "inventory/semi.html", {
        "rows": rows, "recent": SemiBatch.objects.select_related("product", "actor", "lot")[:12],
        "can_setup": user_can(request.user, Cap.MASTER_INVENTORY),
    })


@capability_required(Cap.STOCK_OPERATIONS)
@require_http_methods(["GET", "POST"])
def receipt(request):
    if request.method == "POST":
        p = request.POST
        lines = []
        for i in range(min(int(p.get("rows", 0) or 0), RECEIPT_ROWS)):
            filled = [k for k in ("ingredient", "quantity", "price", "expiry", "lot", "po") if p.get(f"{k}_{i}")]
            if filled and not (p.get(f"ingredient_{i}") and p.get(f"quantity_{i}")):
                messages.error(request, f"Dòng {i + 1} thiếu {'nguyên liệu' if not p.get(f'ingredient_{i}') else 'số lượng'}; "
                                        "điền đủ hoặc xóa dòng đó rồi lưu lại.")
                return redirect("inventory:receipt")
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
            total = f"{data['total']:,}".replace(",", ".")
            messages.success(request, f"Đã lưu phiếu nhập {data['code']}, giá trị {total} đ; tồn vật lý đã tăng. "
                                      f"Mã lô: {', '.join(data.get('lots') or [])}.")
            for warning in data.get("warnings") or []:
                messages.warning(request, warning)
        return redirect("inventory:receipt")
    from django.db.models import OuterRef, Subquery

    from .models import ReceiptLine

    last_price = Subquery(ReceiptLine.objects.filter(ingredient=OuterRef("pk")).order_by("-id").values("unit_price")[:1])
    return render(request, "inventory/receipt.html", {
        "suppliers": Supplier.objects.filter(is_active=True), "rows": range(RECEIPT_ROWS),
        "ingredients": _purchasable().annotate(last_price=last_price),
        "open_pos": PurchaseOrder.objects.exclude(status__in=[PurchaseOrder.Status.DELIVERED,
                                                              PurchaseOrder.Status.CANCELLED]).select_related("ingredient", "supplier"),
        "sources": SupplierPayment.Source.choices, "operation_key": uuid.uuid4().hex,
        "can_setup": user_can(request.user, Cap.MASTER_INVENTORY),
    })


@capability_required(Cap.STOCK_CONFIRM_ORDERING)
@require_http_methods(["GET", "POST"])
def purchase_orders(request):
    if request.method == "POST":
        p = request.POST
        if p.get("action") == "reschedule":
            _run(request, lambda: ops.reschedule(request.user, p.get("po"), ops.delivery_date(p.get("expected_date"))),
                 "Đã cập nhật ngày giao.")
        else:
            _run(request, lambda: ops.create_purchase_order(request.user, p.get("supplier"), p.get("ingredient"),
                                                            p.get("quantity", ""), ops.delivery_date(p.get("expected_date")),
                                                            p.get("note", ""), operation_key=p.get("operation_key", "")),
                 "Đã ghi lần đặt hàng.")
        return redirect("inventory:purchase_orders")
    today = timezone.localdate()
    S = PurchaseOrder.Status
    rows = PurchaseOrder.objects.select_related("supplier", "ingredient")
    waiting = list(rows.filter(status__in=[S.DRAFT, S.ORDERED, S.PARTIAL, S.LATE]).order_by("expected_date", "id"))
    for po in waiting:
        po.state = po.effective_status(today)
        po.state_label = "Nháp" if po.state == S.DRAFT else S(po.state).label
        po.tone = {S.LATE: "danger", S.PARTIAL: "info", S.DRAFT: "neutral"}.get(po.state, "neutral")
        if po.state == S.DRAFT and po.draft_expired(today):
            po.tone = "warn"
    show_all = request.GET.get("tat_ca") == "1"
    done = rows.filter(status__in=[S.DELIVERED, S.CANCELLED]).order_by("-expected_date", "-id")
    return render(request, "inventory/purchase_orders.html", {
        "waiting": waiting, "late": sum(1 for po in waiting if po.state == S.LATE),
        "done": done[:200 if show_all else 15], "done_total": done.count(), "show_all": show_all,
        "suppliers": Supplier.objects.filter(is_active=True), "ingredients": _purchasable(),
        "today": today, "operation_key": uuid.uuid4().hex, "can_setup": user_can(request.user, Cap.MASTER_INVENTORY),
    })


@capability_required(Cap.STOCK_CONFIRM_ORDERING)
@require_http_methods(["GET", "POST"])
def payables(request):
    if request.method == "POST":
        p = request.POST
        _run(request, lambda: ops.pay_supplier(request.user, p.get("payable"), p.get("amount", ""), p.get("source", ""),
                                               operation_key=p.get("operation_key", "")), "Đã ghi thanh toán.")
        return redirect("inventory:payables")
    from apps.shifts.models import Shift

    today = timezone.localdate()
    items = [x for x in Payable.objects.select_related("supplier", "receipt").prefetch_related("payments")
             .order_by("due_date", "id") if not x.is_paid]
    for item in items:
        item.op = uuid.uuid4().hex
        item.left = item.remaining()
        item.days = (item.due_date - today).days
        item.late_days = -item.days
    overdue = [x for x in items if x.days < 0]
    soon = [x for x in items if 0 <= x.days <= 7]
    # Đã trả: lọc theo tháng trả và nhà cung cấp để đối chiếu với sổ của nhà cung cấp.
    month = parse_month(request.GET.get("thang")) or today.replace(day=1)
    next_month = (month + timedelta(days=32)).replace(day=1)
    paid = (SupplierPayment.objects.filter(paid_on__gte=month, paid_on__lt=next_month)
            .select_related("payable__supplier", "payable__receipt", "actor").order_by("-paid_on", "-created_at"))
    supplier = request.GET.get("ncc", "")
    if supplier.isdigit():
        paid = paid.filter(payable__supplier_id=int(supplier))
    paid = list(paid)
    return render(request, "inventory/payables.html", {
        "items": items, "sources": SupplierPayment.Source.choices, "default_source": SupplierPayment.Source.TRANSFER,
        "shift_cash": SupplierPayment.Source.SHIFT_CASH, "shift_open": Shift.objects.operating() is not None,
        "today": today, "total": sum(x.left for x in items),
        "overdue": len(overdue), "overdue_sum": sum(x.left for x in overdue),
        "soon": len(soon), "soon_sum": sum(x.left for x in soon),
        "paid": paid, "paid_sum": sum(x.amount for x in paid), "month": month, "supplier": supplier,
        "suppliers": Supplier.objects.filter(pk__in=Payable.objects.values("supplier_id")).order_by("name"),
    })


@capability_required(Cap.VIEW_DASHBOARD)
@require_GET
def report(request):
    """Báo cáo nguyên vật liệu: hao hụt theo lý do, hủy sau pha chế, kiểm kê, trường hợp thiếu (FR-26, FR-27)."""
    from apps.orders.models import PostPrepCancellation
    from apps.reports.services import BO02_MONTHLY_TARGET

    # ?thang=YYYY-MM để khớp tháng đang xem ở bảng điều khiển
    now = parse_month(request.GET.get("thang")) or timezone.localdate()
    month = {"created_at__year": now.year, "created_at__month": now.month}
    units = dict(Unit.choices)
    waste = list(Waste.objects.filter(**month).values("ingredient__name", "ingredient__unit", "reason")
                 .annotate(total=Sum("quantity")).order_by("ingredient__name"))
    reason_labels = dict(Waste.Reason.choices)
    for w in waste:
        w["reason_label"] = reason_labels[w["reason"]]
        w["unit"] = units.get(w["ingredient__unit"], w["ingredient__unit"])
    post_prep = {}
    names = {i.pk: i for i in Ingredient.objects.all()}
    for ppc in PostPrepCancellation.objects.filter(**month):
        for ing_id, qty in ppc.usage.items():
            post_prep[int(ing_id)] = post_prep.get(int(ing_id), 0) + float(qty)
    shortage_month = ShortageCase.objects.filter(day__year=now.year, day__month=now.month)
    counts = list(StockCount.objects.filter(**month).select_related("ingredient", "counter"))
    consumption = list(ConsumptionCheck.objects.filter(**month).select_related("ingredient", "from_count", "to_count")
                       .order_by("-to_count__created_at", "ingredient__name"))
    first = now.replace(day=1)
    prev_month = (first - timedelta(days=1)).replace(day=1)
    next_month = (first + timedelta(days=32)).replace(day=1)
    return render(request, "inventory/report.html", {
        "month": f"{now:%m/%Y}", "month_value": f"{now:%Y-%m}", "waste": waste,
        "prev_month": prev_month, "next_month": next_month if next_month <= timezone.localdate() else None,
        "post_prep": [(names[k], v) for k, v in sorted(post_prep.items()) if k in names],
        "counts": counts, "count_summary": _count_summary(counts),
        "pending_counts": sum(1 for c in counts if c.status == StockCount.Status.PENDING),
        "shortage_total": shortage_month.count(), "shortage_target": BO02_MONTHLY_TARGET,
        "shortage_by_ingredient": shortage_month.values("ingredient__name").annotate(n=Count("id")).order_by("-n"),
        "shortages": shortage_month.select_related("ingredient").order_by("-day"),
        "consumption": consumption, "consumption_summary": _consumption_summary(consumption),
        "consumption_over": sum(1 for c in consumption if c.over),
    })


def _count_summary(counts):
    """Mỗi nguyên liệu một dòng: số lần kiểm, tổng chênh lệch, lần lệch nhiều nhất, số lần chờ xác nhận."""
    rows = OrderedDict()
    for c in sorted(counts, key=lambda c: c.ingredient.name):
        r = rows.setdefault(c.ingredient_id, {"ingredient": c.ingredient, "n": 0, "total": Decimal(0), "worst": None,
                                               "pending": 0})
        r["n"] += 1
        r["total"] += c.difference
        if r["worst"] is None or abs(c.percent) > abs(r["worst"].percent):
            r["worst"] = c
        r["pending"] += c.status == StockCount.Status.PENDING
    return list(rows.values())


def _consumption_summary(checks):
    """Cộng các kỳ đối chiếu trong tháng theo nguyên liệu: thực tế, theo đơn, phần vượt và số kỳ vượt mức."""
    rows = OrderedDict()
    for c in sorted(checks, key=lambda c: c.ingredient.name):
        r = rows.setdefault(c.ingredient_id, {"ingredient": c.ingredient, "n": 0, "actual": Decimal(0),
                                               "by_orders": Decimal(0), "over": 0})
        r["n"] += 1
        r["actual"] += c.actual
        r["by_orders"] += c.by_orders
        r["over"] += c.over
    for r in rows.values():
        r["excess"] = r["actual"] - r["by_orders"]
        r["percent"] = r["excess"] / r["by_orders"] * 100 if r["by_orders"] else None
    return list(rows.values())
