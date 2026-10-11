"""Màn hình đơn đang mở, yêu cầu điều chỉnh, duyệt và thu ngân (FR-04, FR-10, FR-11)."""

import uuid

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.accounts.permissions import Cap, capability_required, user_can
from apps.catalog.models import MenuItem, Table
from apps.core.idempotency import OperationKeyError

from . import adjustments, payments
from .models import AdjustmentReason, AdjustmentRequest, Order


def _errors(error):
    return error.messages if isinstance(error, ValidationError) else [str(error)]


@capability_required(Cap.ORDER_CREATE)
@require_GET
def open_orders(request):
    orders = (Order.objects.exclude(status__in=[Order.Status.PAID, Order.Status.CANCELLED])
              .select_related("table").prefetch_related("lines__options", "adjustment_requests")
              .order_by("table__sort_order", "table__code", "created_at"))
    return render(request, "orders/open_orders.html", {"orders": orders})


@capability_required(Cap.ORDER_CREATE)
@require_http_methods(["GET", "POST"])
def request_adjustment(request, order_id):
    order = get_object_or_404(Order.objects.select_related("table"), pk=order_id)
    kinds = [k for k in AdjustmentRequest.Kind.choices
             if (k[0] == AdjustmentRequest.Kind.CANCEL_PAID) == (order.status == Order.Status.PAID)]
    form = {"kind": kinds[0][0] if kinds else "", "cups": "1"}
    if request.method == "POST":
        form = request.POST.dict()
        new_line = None
        if form.get("new_size"):
            new_line = {"item": form.get("new_item"), "size": form.get("new_size"), "quantity": form.get("new_quantity") or 1,
                        "options": [], "note": ""}
        payload = {"order": order.pk, "kind": form.get("kind"), "line": form.get("line"), "cups": form.get("cups"),
                   "target_table": form.get("target_table"), "new_line": new_line, "reason": form.get("reason"),
                   "note": form.get("note")}
        try:
            result, _ = adjustments.create_request(request.user, form.get("operation_key", ""), payload)
        except (ValidationError, OperationKeyError) as error:
            for message in _errors(error):
                messages.error(request, message)
        else:
            messages.success(request, f"Đã gửi yêu cầu: {result['summary']}. Đang chờ {result['level']} duyệt.")
            return redirect("orders:open_orders")
    sizes = []
    for item in MenuItem.objects.sellable().prefetch_related("sizes"):
        for size in item.active_sizes():
            sizes.append({"item": item.pk, "size": size.pk, "label": f"{item.name} {size.name} · {size.price:,} đ".replace(",", ".")})
    return render(request, "orders/adjust_form.html", {
        "order": order, "kinds": kinds, "form": form, "operation_key": uuid.uuid4().hex,
        "lines": [l for l in order.lines.all() if l.billable_quantity > 0],
        "reasons": AdjustmentReason.objects.filter(is_active=True),
        "tables": Table.objects.filter(is_active=True).exclude(pk=order.table_id), "sizes": sizes,
    })


@login_required
@require_GET
def approvals(request):
    pending = adjustments.pending_for(request.user)
    if not pending and not user_can(request.user, Cap.ORDER_ADJUST_APPROVE):
        raise PermissionDenied
    for req in pending:
        req.op_approve, req.op_reject = uuid.uuid4().hex, uuid.uuid4().hex
    from apps.core import params

    return render(request, "orders/approvals.html", {"pending": pending, "deadline": params.get("approval_level_minutes")})


@login_required
@require_GET
def approvals_count(request):
    pending = adjustments.pending_for(request.user)
    return JsonResponse({"count": len(pending)})


@login_required
@require_POST
def decide(request, request_id):
    approve = request.POST.get("decision") == "approve"
    req = get_object_or_404(AdjustmentRequest.objects.select_related("order"), pk=request_id)
    if req.status == AdjustmentRequest.Status.PENDING and not adjustments.can_decide(request.user, req):
        # Không thuộc người được duyệt ở cấp hiện tại: từ chối tại máy chủ và ghi nhật ký (AC-111, AC-22, AC-23).
        from apps.accounts.permissions import _deny

        _deny(request, Cap.PAID_INVOICE_CANCEL if req.kind == AdjustmentRequest.Kind.CANCEL_PAID
              else Cap.ORDER_ADJUST_APPROVE)
    try:
        result, _ = adjustments.decide(request.user, request.POST.get("operation_key", ""), request_id, approve,
                                       request.POST.get("note", ""))
    except (ValidationError, OperationKeyError, AdjustmentRequest.DoesNotExist) as error:
        for message in _errors(error):
            messages.error(request, message)
    else:
        messages.success(request, result["message"] or f"Đã ghi: {result['status']}.")
    return redirect("orders:approvals")


@capability_required(Cap.PAYMENT)
@require_GET
def cashier(request):
    bills = payments.tables_with_bills()
    for bill in bills:
        bill["operation_key"] = uuid.uuid4().hex
        bill["can_received"] = bool(bill["exhausted"]) and all(
            payments.can_pay_received_items(request.user, r) for r in bill["exhausted"])
    return render(request, "orders/cashier.html", {"bills": bills})


@capability_required(Cap.PAYMENT)
@require_POST
def pay(request, table_id):
    method = request.POST.get("method", "")
    confirmed = request.POST.get("transfer_confirmed") == "1"
    received = request.POST.get("mode") == "received"
    try:
        func = payments.pay_received_items if received else payments.pay_table
        result, repeated = func(request.user, request.POST.get("operation_key", ""), table_id, method, confirmed)
    except (ValidationError, OperationKeyError) as error:
        for message in _errors(error):
            messages.error(request, message)
    else:
        amount = f"{result['amount']:,}".replace(",", ".")
        messages.success(request, f"Đã thu {amount} đ bằng {result['method'].lower()} cho các đơn "
                                  f"{', '.join(result['orders'])}." + (" (Gửi lại: đã ghi từ trước.)" if repeated else ""))
    return redirect("orders:cashier")
