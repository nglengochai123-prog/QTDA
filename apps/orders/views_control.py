"""Màn hình đơn đang mở, yêu cầu điều chỉnh, duyệt và thu ngân (FR-04, FR-10, FR-11)."""

import uuid

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.accounts.permissions import Cap, capability_required, user_can
from apps.catalog.models import MenuItem, Table
from apps.core import numbers
from apps.core.idempotency import OperationKeyError

from . import adjustments, payments
from .models import AdjustmentReason, AdjustmentRequest, Order, OrderLine


def _errors(error):
    return error.messages if isinstance(error, ValidationError) else [str(error)]


@capability_required(Cap.ORDER_CREATE)
@require_GET
def overview(request):
    """Tổng quan ca hiện tại; ?phan=1 trả phần thân để trang tự làm mới."""
    from .overview import shift_overview

    context = shift_overview(request.user)
    template = "orders/_overview_body.html" if request.GET.get("phan") == "1" else "orders/overview.html"
    return render(request, template, context)


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
            sizes.append({"item": item.pk, "size": size.pk, "label": f"{item.name} {size.name} · {numbers.fmt(size.price, 0)} đ"})
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
        bill["can_approve"] = any(adjustments.can_decide(request.user, r) for r in bill["requests"])
    from apps.shifts.models import Shift
    from apps.shifts.services import refund_rows

    from .prepaid import cashier_cards, duty_problem

    operating = Shift.objects.operating()
    return render(request, "orders/cashier.html", {"bills": bills, "total": sum(b["amount"] for b in bills),
                                                   "prepaid": cashier_cards(),
                                                   "prepaid_problem": duty_problem(request.user),
                                                   "signature": payments.cashier_signature(bills),
                                                   "can_detail": user_can(request.user, Cap.VIEW_DASHBOARD),
                                                   "pending_refunds": refund_rows(operating),
                                                   "refund_shift_open": operating is not None,
                                                   "operating_shift": operating})


@capability_required(Cap.PAYMENT)
@require_GET
def cashier_changes(request):
    return JsonResponse({"sig": payments.cashier_signature()})


@capability_required(Cap.PAYMENT)
@require_POST
def pay(request, table_id):
    method = request.POST.get("method", "")
    confirmed = request.POST.get("transfer_confirmed") == "1"
    received = request.POST.get("mode") == "received"
    expected = request.POST.get("expected", "")
    try:
        if received:
            result, repeated = payments.pay_received_items(request.user, request.POST.get("operation_key", ""),
                                                           table_id, method, confirmed)
        else:
            result, repeated = payments.pay_table(request.user, request.POST.get("operation_key", ""), table_id,
                                                  method, confirmed, int(expected) if expected.isdigit() else None)
    except (ValidationError, OperationKeyError) as error:
        for message in _errors(error):
            messages.error(request, message)
    else:
        amount = f"{result['amount']:,}".replace(",", ".")
        orders = ("đơn " if len(result["orders"]) == 1 else "các đơn ") + ", ".join(result["orders"])
        messages.success(request, f"Đã thu {amount} đ bằng {result['method'].lower()} cho {orders}."
                                  + (" (Gửi lại: đã ghi từ trước.)" if repeated else ""))
    return redirect("orders:cashier")


def _int_or_none(value):
    value = (value or "").strip().replace(".", "").replace(",", "")
    return int(value) if value.isdigit() else None


def _prepaid_action(request, run, success):
    """Chạy một thao tác của đơn thu trước từ biểu mẫu màn Thu ngân rồi quay lại màn đó."""
    from .prepaid import PrepayDenied, log_denied

    try:
        result, repeated = run()
    except PrepayDenied as error:
        log_denied(request, error)
        messages.error(request, str(error))
    except (ValidationError, OperationKeyError) as error:
        for message in _errors(error):
            messages.error(request, message)
    except (ValueError, OrderLine.DoesNotExist, Order.DoesNotExist):
        messages.error(request, "Dữ liệu gửi lên không đọc được. Tải lại trang rồi thử lại.")
    else:
        text = success(result)
        if text:
            messages.success(request, text + (" (Gửi lại: đã ghi từ trước.)" if repeated else ""))
        elif result.get("message"):
            messages.info(request, result["message"])
    return redirect(reverse("orders:cashier") + "#thu-truoc")


@capability_required(Cap.PAYMENT)
@require_POST
def prepaid_done(request, line_id):
    """Thu ngân xác nhận pha xong một phần hoặc cả dòng của đơn đã thu trước."""
    from .prepaid import cashier_complete_line

    def run():
        return cashier_complete_line(request.user, request.POST.get("operation_key", ""), line_id,
                                     int(request.POST.get("cups", "0")), int(request.POST.get("expected_done", "")))

    return _prepaid_action(request, run, lambda r: (f"Đã ghi pha xong {r['applied']} ly." if r["applied"] else ""))


@capability_required(Cap.PAYMENT)
@require_POST
def prepaid_complete(request, order_id):
    """Giao nước và hoàn tất đơn đã thu trước."""
    from .prepaid import complete_order

    def run():
        return complete_order(request.user, request.POST.get("operation_key", ""), order_id)

    return _prepaid_action(request, run, lambda r: (f"Đơn {r['code']} đã giao nước và hoàn tất." if r["applied"]
                                                    else ""))


@capability_required(Cap.PAYMENT)
@require_POST
def prepaid_charge(request, charge_id):
    """Thu khoản thu thêm sau khi đơn thu trước được duyệt tăng tiền."""
    from .prepaid import collect_charge

    def run():
        return collect_charge(request.user, request.POST.get("operation_key", ""), charge_id,
                              request.POST.get("method", ""), request.POST.get("transfer_confirmed") == "1",
                              _int_or_none(request.POST.get("cash_received")))

    return _prepaid_action(request, run, lambda r: (
        f"Đã thu thêm {numbers.fmt(r['amount'], 0)} đ bằng {r['method'].lower()} cho đơn {r['order']}."
        if r["applied"] else ""))
