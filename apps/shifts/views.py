"""Màn hình ca của tôi (Quản lý ca, thu ngân) và tình trạng ca (Chủ quán, Quản lý ca)."""

import uuid

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from apps.accounts.models import User
from apps.accounts.permissions import Cap, capability_required, user_can
from apps.core.idempotency import OperationKeyError

from . import services
from apps.core import params

from .models import CashEntry, Discrepancy, ExpenseCategory, Shift, ShiftReport, ShiftReportCorrection


def _errors(error):
    return error.messages if isinstance(error, ValidationError) else [str(error)]


def _flash(request, fn, ok_message):
    try:
        result = fn()
    except (ValidationError, OperationKeyError) as error:
        for message in _errors(error):
            messages.error(request, message)
        return None
    messages.success(request, ok_message)
    return result


@capability_required(Cap.CASH_FUND)
@require_GET
def my_shift(request, shift_id=None):
    shift = get_object_or_404(Shift, pk=shift_id) if shift_id else Shift.objects.current()
    if shift is None:
        shift = Shift.objects.filter(status=Shift.Status.CLOSED, report__isnull=True).first()
    context = {"shift": shift, "categories": [c for c in ExpenseCategory.choices if c[0] != ExpenseCategory.MATERIALS]}
    if shift is not None:
        from apps.orders.models import Order

        context.update(
            figures=services.figures(shift), entries=shift.cash_entries.select_related("receiver", "actor"),
            blockers=services.close_blockers(shift) if shift.status == Shift.Status.OPEN else [],
            open_orders=Order.objects.filter(shift=shift).exclude(status__in=["da_thanh_toan", "da_huy"])
            .select_related("table"),
            next_shifts=Shift.objects.filter(status=Shift.Status.OPEN, starts_at__gt=shift.starts_at).exclude(pk=shift.pk),
            receivers=User.objects.filter(is_active=True).exclude(pk=request.user.pk).order_by("first_name"),
            discrepancies=shift.discrepancies.current(), status=services.data_status(shift),
            history=shift.discrepancies.exclude(superseded_at=None), op_correction=uuid.uuid4().hex,
            op_open=uuid.uuid4().hex, op_expense=uuid.uuid4().hex, op_handover=uuid.uuid4().hex,
        )
        context["report"] = report = ShiftReport.objects.filter(shift=shift).first()
        if report is not None:
            context["effective"] = report.effective()
            context["corrections"] = report.corrections.select_related("requested_by", "decided_by")
    context["to_confirm"] = CashEntry.objects.filter(kind=CashEntry.Kind.HANDOVER, receiver=request.user,
                                                     confirmed_at__isnull=True).select_related("shift", "actor")
    context["pending_refunds"] = [(r, uuid.uuid4().hex) for r in services.pending_refunds()]
    return render(request, "shifts/my_shift.html", context)


@capability_required(Cap.PAYMENT)
@require_POST
def refund_paid(request, refund_id):
    p = request.POST
    _flash(request, lambda: services.confirm_refund(request.user, p.get("operation_key", ""), refund_id,
                                                    p.get("note", "")), "Đã ghi đã hoàn tiền vào ca hiện tại.")
    return redirect(p.get("next") or "shifts:my_shift")


@capability_required(Cap.SHIFT_CLOSE)
@require_POST
def correction(request, shift_id):
    p = request.POST
    _flash(request, lambda: services.request_correction(
        request.user, p.get("operation_key", ""), shift_id, p.get("counted_cash", ""), p.get("transfer_received", ""),
        p.get("transfer_refunded") or 0, p.get("reason", "")), "Đã gửi đề nghị đính chính báo cáo cuối ca.")
    return redirect("shifts:my_shift_detail", shift_id=shift_id)


@capability_required(Cap.EXCEPTION_REVIEW)
@require_POST
def decide_correction(request, correction_id):
    p = request.POST
    _flash(request, lambda: services.decide_correction(request.user, correction_id, p.get("decision") == "approve",
                                                       p.get("note", "")), "Đã ghi quyết định đính chính.")
    return redirect("shifts:status")


@capability_required(Cap.CASH_FUND)
@require_POST
def cash_entry(request, shift_id):
    p = request.POST
    _flash(request, lambda: services.add_cash_entry(
        request.user, p.get("operation_key", ""), shift_id, p.get("kind", ""), p.get("amount", ""),
        category=p.get("category", ""), note=p.get("note", ""), receipt=request.FILES.get("receipt"),
        receiver_id=p.get("receiver") or None), "Đã ghi vào quỹ ca.")
    return redirect("shifts:my_shift_detail", shift_id=shift_id)


@login_required
@require_POST
def confirm_handover(request, entry_id):
    _flash(request, lambda: services.confirm_handover(request.user, entry_id), "Đã xác nhận nhận tiền.")
    return redirect(request.POST.get("next") or "core:home")


@capability_required(Cap.SHIFT_CLOSE)
@require_POST
def close(request, shift_id):
    _flash(request, lambda: services.close_shift(request.user, shift_id),
           "Đã kết ca và chốt doanh thu theo từng phương thức. Lập báo cáo cuối ca bên dưới.")
    return redirect("shifts:my_shift_detail", shift_id=shift_id)


@capability_required(Cap.SHIFT_CLOSE)
@require_POST
def carry(request, shift_id):
    p = request.POST
    _flash(request, lambda: services.carry_over(request.user, p.get("order"), p.get("to_shift"), p.get("reason", "")),
           "Đã chuyển đơn sang ca sau.")
    return redirect("shifts:my_shift_detail", shift_id=shift_id)


@capability_required(Cap.SHIFT_CLOSE)
@require_POST
def report(request, shift_id):
    p = request.POST
    _flash(request, lambda: services.submit_report(request.user, shift_id, p.get("counted_cash", ""),
                                                   p.get("transfer_received", ""), p.get("transfer_refunded") or 0,
                                                   p.get("incidents", "")),
           "Đã gửi báo cáo cuối ca; hệ thống đã đối soát.")
    return redirect("shifts:my_shift_detail", shift_id=shift_id)


@capability_required(Cap.SHIFT_CLOSE)
@require_POST
def explain(request, discrepancy_id):
    _flash(request, lambda: services.explain(request.user, discrepancy_id, request.POST.get("text", "")),
               "Đã gửi giải trình.")
    return redirect(request.POST.get("next") or "shifts:status")


@capability_required(Cap.EXCEPTION_REVIEW)
@require_POST
def decide(request, discrepancy_id):
    accept = request.POST.get("decision") == "accept"
    _flash(request, lambda: services.decide(request.user, discrepancy_id, accept), "Đã ghi quyết định.")
    return redirect("shifts:status")


@capability_required(Cap.VIEW_DASHBOARD)
@require_GET
def status(request):
    from apps.control.services import monthly_control

    now = timezone.localtime()
    shifts = Shift.objects.select_related("approver").order_by("-starts_at")[:30]
    rows = [services.data_status(s) for s in shifts]
    for row in rows:
        row["figures"] = services.figures(row["shift"])
    context = {"rows": rows,
               "pending_decisions": Discrepancy.objects.current().filter(decision="").select_related("shift", "manager")
               .order_by("-created_at"),
               "pending_corrections": ShiftReportCorrection.objects.filter(status=ShiftReportCorrection.Status.PENDING)
               .select_related("report__shift", "requested_by"),
               "store_threshold": params.get("accumulated_store_threshold"),
               "accumulated": services.accumulated_report(now.year, now.month), "month": f"{now:%m/%Y}"}
    if user_can(request.user, Cap.VIEW_FINANCIALS):
        context["control"] = monthly_control(now.year, now.month)
    return render(request, "shifts/status.html", context)
