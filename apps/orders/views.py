import json
import uuid

from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from apps.accounts.permissions import Cap, capability_required
from decimal import Decimal

from django.shortcuts import get_object_or_404

from apps.catalog.models import MenuGroup, MenuItem, Table
from apps.inventory import stock
from apps.inventory.models import RecipeVersion
from apps.core.idempotency import OperationKeyError
from apps.inventory.stock import InsufficientStock

from . import services
from .models import AdjustmentRequest, Order, OrderLine


def _usage_map(version, size=None, option=None):
    if version is None:
        return {}
    usage = {}
    for line in version.lines.all():
        if (size is not None and line.size_id == size.pk) or (size is None and line.option_id == option.pk):
            usage[str(line.ingredient_id)] = float(Decimal(usage.get(str(line.ingredient_id), 0)) + line.quantity)
    return usage


def _available_map():
    return {str(k): float(v[2]) for k, v in stock.snapshot_for().items()}


def _menu_data():
    versions = RecipeVersion.objects.current_map()
    availability = services.availability(versions)
    by_group = {}
    for item in MenuItem.objects.sellable().prefetch_related("sizes", "option_groups__options"):
        by_group.setdefault(item.group_id, []).append(item)
    groups = []
    for group in MenuGroup.objects.filter(is_active=True):
        items = []
        for item in by_group.get(group.pk, []):
            if any(g.is_required and not any(o.is_active for o in g.options.all()) for g in item.option_groups.all()):
                continue  # nhóm tùy chọn bắt buộc không còn lựa chọn nào thì không gọi được món
            version = None if item.no_ingredients else versions.get(item.pk)
            items.append({
                "id": item.pk, "name": item.name,
                "sizes": [{"id": s.pk, "name": s.name, "price": s.price, "left": availability.get(s.pk),
                           "usage": _usage_map(version, size=s)}
                          for s in item.sizes.all() if s.is_active],
                "optionGroups": [{
                    "id": g.pk, "name": g.name, "multiple": g.selection == g.Selection.MULTIPLE,
                    "required": g.is_required,
                    "options": [{"id": o.pk, "name": o.name, "extra": o.extra_price,
                                 "usage": _usage_map(version, option=o)}
                                for o in g.options.all() if o.is_active],
                } for g in sorted(item.option_groups.all(), key=lambda g: (g.selection == g.Selection.MULTIPLE, g.name))],
            })
        if items:
            groups.append({"id": group.pk, "name": group.name, "items": items})
    return groups


@capability_required(Cap.ORDER_CREATE)
@require_GET
def create(request):
    tables = [{"id": t.pk, "code": t.code, "area": t.area} for t in Table.objects.filter(is_active=True)]
    return render(request, "orders/create.html", {
        "menu": _menu_data(), "tables": tables, "operation_key": uuid.uuid4().hex, "stock": _available_map(),
    })


@capability_required(Cap.ORDER_CREATE)
@require_GET
def availability(request):
    return JsonResponse({"left": {str(k): v for k, v in services.availability().items()},
                         "available": _available_map()})


@capability_required(Cap.ORDER_CREATE)
@require_POST
def submit(request):
    try:
        body = json.loads(request.body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({"ok": False, "error": "Dữ liệu gửi lên không đọc được."}, status=400)
    try:
        result, repeated = services.submit_order(request.user, body.get("operation_key", ""), body.get("order") or {})
    except InsufficientStock as error:
        return JsonResponse({"ok": False, "shortages": error.shortages, "lines": getattr(error, "lines", []),
                             "error": "Không đủ nguyên liệu cho cả đơn nên chưa nhận đơn."}, status=409)
    except (ValidationError, OperationKeyError) as error:
        message = " ".join(error.messages) if isinstance(error, ValidationError) else str(error)
        return JsonResponse({"ok": False, "error": message}, status=400)
    return JsonResponse({"ok": True, "repeated": repeated, **result})


def _bar_context():
    lines = list(services.waiting_lines())
    tickets = {}
    for line in lines:
        ticket = tickets.setdefault(line.order_id, {"order": line.order, "lines": []})
        line.op_one = uuid.uuid4().hex
        line.op_all = uuid.uuid4().hex
        ticket["lines"].append(line)
    pending = {r.order_id: r for r in AdjustmentRequest.objects.filter(
        order_id__in=tickets, status=AdjustmentRequest.Status.PENDING).select_related("line", "order__table", "target_table")}
    now = timezone.now()
    result = []
    for order_id, ticket in tickets.items():
        ticket["pending"] = pending.get(order_id)  # quầy biết món đang chờ duyệt đổi, hủy hay chuyển bàn
        age = now - ticket["order"].created_at
        ticket["minutes"] = int(age.total_seconds() // 60)
        ticket["is_new"] = age.total_seconds() < 60
        ticket["cups"] = sum(l.pending_quantity for l in ticket["lines"])
        result.append(ticket)
    return {"tickets": result, "cups_waiting": sum(t["cups"] for t in result), "now": now}


@capability_required(Cap.BAR_PREPARE)
@require_GET
def bar(request):
    return render(request, "orders/bar.html", _bar_context())


@capability_required(Cap.BAR_PREPARE)
@require_GET
def bar_queue(request):
    return render(request, "orders/_bar_queue.html", _bar_context())


@capability_required(Cap.BAR_PREPARE)
@require_POST
def bar_complete(request):
    try:
        body = json.loads(request.body.decode("utf-8"))
        result, repeated = services.complete_line(request.user, body.get("operation_key", ""), body["line"],
                                                  body["cups"], body["expected_done"])
    except (ValueError, KeyError, TypeError, UnicodeDecodeError):
        return JsonResponse({"ok": False, "error": "Dữ liệu gửi lên không đọc được."}, status=400)
    except OperationKeyError as error:
        return JsonResponse({"ok": False, "error": str(error)}, status=400)
    return JsonResponse({"ok": True, "repeated": repeated, **result})


@capability_required(Cap.BAR_PREPARE)
@require_GET
def print_ticket(request, order_id):
    """Phiếu pha chế in bằng máy in hiện có qua trình duyệt (FR-02, AC-05)."""
    order = get_object_or_404(Order.objects.select_related("table", "created_by"), pk=order_id)
    lines = list(order.lines.exclude(status=OrderLine.Status.CANCELLED).prefetch_related("options"))
    for line in lines:  # in lại sau khi hủy bớt ly thì phiếu ghi số ly còn phải pha
        line.to_make = line.quantity - line.cancelled_quantity
    return render(request, "orders/print_ticket.html", {"order": order, "lines": lines,
                                                        "cups": sum(line.to_make for line in lines),
                                                        "auto": request.GET.get("in") == "1"})


def _ready_context():
    tables = {}
    for line in services.ready_lines():
        line.op_serve = uuid.uuid4().hex
        tables.setdefault(line.order.table.code, []).append(line)
    return {"ready": sorted(tables.items(), key=lambda kv: min(l.done_at for l in kv[1])),
            "ready_count": sum(len(v) for v in tables.values())}


@capability_required(Cap.ORDER_CREATE)
@require_GET
def ready(request):
    return render(request, "orders/ready.html", _ready_context())


@capability_required(Cap.ORDER_CREATE)
@require_GET
def ready_queue(request):
    return render(request, "orders/_ready_queue.html", _ready_context())


@capability_required(Cap.ORDER_CREATE)
@require_GET
def ready_count(request):
    ctx = _ready_context()
    return JsonResponse({"count": ctx["ready_count"], "tables": [code for code, _ in ctx["ready"]]})


@capability_required(Cap.ORDER_CREATE)
@require_POST
def serve(request):
    try:
        body = json.loads(request.body.decode("utf-8"))
        result, repeated = services.serve_line(request.user, body.get("operation_key", ""), body["line"])
    except (ValueError, KeyError, TypeError, UnicodeDecodeError):
        return JsonResponse({"ok": False, "error": "Dữ liệu gửi lên không đọc được."}, status=400)
    except (ValidationError, OperationKeyError) as error:
        message = " ".join(error.messages) if isinstance(error, ValidationError) else str(error)
        return JsonResponse({"ok": False, "error": message}, status=400)
    return JsonResponse({"ok": True, "repeated": repeated, **result})


@capability_required(Cap.ORDER_CREATE)
@require_POST
def recount(request):
    """Đề nghị pha chế kiểm kê lại nguyên liệu vừa bị báo thiếu (AC-03)."""
    from apps.inventory.operations import request_recount

    try:
        body = json.loads(request.body.decode("utf-8"))
        result, _ = request_recount(request.user, body.get("operation_key", ""), body.get("ingredients") or [])
    except (ValueError, TypeError, UnicodeDecodeError):
        return JsonResponse({"ok": False, "error": "Dữ liệu gửi lên không đọc được."}, status=400)
    except OperationKeyError as error:
        return JsonResponse({"ok": False, "error": str(error)}, status=400)
    return JsonResponse({"ok": True, **result})


@capability_required(Cap.ORDER_CREATE)
@require_POST
def customer_switched(request):
    """Nhân viên xác nhận khách phải đổi món sau cảnh báo không đủ nguyên liệu (BRU-26, AC-63)."""
    from apps.core.idempotency import run_once
    from apps.inventory.models import Ingredient, ShortageCase
    from apps.inventory.operations import record_shortage

    try:
        body = json.loads(request.body.decode("utf-8"))
        ids = sorted({int(i) for i in body.get("ingredients") or []})
    except (ValueError, TypeError, UnicodeDecodeError):
        return JsonResponse({"ok": False, "error": "Dữ liệu gửi lên không đọc được."}, status=400)

    def action():
        recorded = []
        for ingredient in Ingredient.objects.filter(pk__in=ids):
            if record_shortage(ingredient, ShortageCase.Source.CUSTOMER_SWITCH, f"Tạo đơn bởi {request.user}"):
                recorded.append(ingredient.name)
        return {"recorded": recorded}

    try:
        result, _ = run_once(body.get("operation_key", ""), "customer_switch", {"ingredients": ids}, action,
                             actor=request.user)
    except OperationKeyError as error:
        return JsonResponse({"ok": False, "error": str(error)}, status=400)
    return JsonResponse({"ok": True, **result})
