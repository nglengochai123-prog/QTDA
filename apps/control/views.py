"""Màn hình ngoại lệ, vụ việc tổn thất, báo cáo điều chỉnh và tham số (FR-14, FR-17, FR-18, NFR-14)."""

import uuid
from datetime import datetime

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.accounts.permissions import Cap, capability_required
from apps.audit.models import Action, AuditLog
from apps.audit.services import record
from apps.core import params
from apps.shifts.models import Discrepancy, Shift

from . import reports, services
from .models import ExceptionCase, ExceptionReview, LossCase


def _run(request, fn, ok):
    try:
        result = fn()
    except ValidationError as error:
        for message in error.messages:
            messages.error(request, message)
        return None
    messages.success(request, ok)
    return result


@capability_required(Cap.EXCEPTION_REVIEW)
@require_GET
def exception_list(request):
    status = request.GET.get("trang-thai", "cho_xem_xet")
    items = ExceptionCase.objects.select_related("employee", "shift", "order", "loss_case")
    if status in ExceptionCase.Status.values:
        items = items.filter(status=status)
    due = set(services.reminders_due().values_list("pk", flat=True))
    return render(request, "control/exceptions.html", {"items": items, "status": status, "due": due})


@capability_required(Cap.EXCEPTION_REVIEW)
@require_http_methods(["GET", "POST"])
def exception_detail(request, pk):
    exc = get_object_or_404(ExceptionCase.objects.select_related("employee", "shift", "order", "loss_case"), pk=pk)
    if request.method == "POST":
        p = request.POST
        if p.get("action") == "attach":
            case_id = p.get("case")
            def attach():
                case = (services.open_case(request.user, p.get("title") or str(exc),
                                           operation_key=p.get("operation_key", "")) if case_id == "new"
                        else LossCase.objects.get(pk=case_id))
                return services.add_evidence(request.user, case, exception=exc)
            _run(request, attach, "Đã gắn ngoại lệ vào vụ việc tổn thất.")
        else:
            _run(request, lambda: services.review(request.user, exc.pk, p.get("result", ""),
                                                  money_loss=p.get("money_loss") == "1", measure=p.get("measure", ""),
                                                  correction_reason=p.get("correction_reason", "")),
                 "Đã ghi kết quả xem xét.")
        return redirect("control:exception_detail", pk=pk)
    trail = []
    if exc.order_id:
        from django.db.models import Q

        code = exc.order.code
        trail = AuditLog.objects.filter(
            Q(object_type="orders.Order", object_id=str(exc.order_id)) | Q(reason__contains=code)
            | Q(after__icontains=code)).order_by("created_at")[:60]
    history = ExceptionCase.objects.filter(employee=exc.employee).exclude(pk=exc.pk)[:20] if exc.employee_id else []
    return render(request, "control/exception_detail.html", {
        "exc": exc, "reviews": exc.reviews.select_related("reviewer"), "effective": exc.effective_review(),
        "results": ExceptionReview.Result.choices, "requests": exc.requests.select_related("reason", "requested_by", "decided_by"),
        "trail": trail, "history": history, "cases": LossCase.objects.filter(status=LossCase.Status.OPEN),
        "operation_key": uuid.uuid4().hex,
        "lines": exc.order.lines.prefetch_related("options") if exc.order_id else [],
    })


@capability_required(Cap.EXCEPTION_REVIEW)
@require_http_methods(["GET", "POST"])
def case_list(request):
    if request.method == "POST":
        case = _run(request, lambda: services.open_case(request.user, request.POST.get("title", "").strip() or "Vụ việc mới",
                                                        operation_key=request.POST.get("operation_key", "")),
                    "Đã lập vụ việc.")
        if case:
            return redirect("control:case_detail", pk=case.pk)
    cases = LossCase.objects.prefetch_related("evidence", "verifications", "recoveries")
    return render(request, "control/cases.html", {"cases": cases, "operation_key": uuid.uuid4().hex})


@capability_required(Cap.EXCEPTION_REVIEW)
@require_http_methods(["GET", "POST"])
def case_detail(request, pk):
    case = get_object_or_404(LossCase, pk=pk)
    if request.method == "POST":
        p = request.POST
        action = p.get("action")
        if action == "discrepancy":
            _run(request, lambda: services.add_evidence(request.user, case,
                                                        discrepancy=Discrepancy.objects.get(pk=p.get("discrepancy")),
                                                        transaction_ref=p.get("transaction_ref", "").strip()),
                 "Đã thêm khoản chênh lệch làm bằng chứng.")
        elif action == "verify":
            _run(request, lambda: services.verify(request.user, case, int(p.get("amount") or 0), p.get("reason", "")),
                 "Đã ghi tổn thất đã xác minh.")
        elif action == "recover":
            _run(request, lambda: services.recover(request.user, case, int(p.get("amount") or 0), p.get("note", ""),
                                                   operation_key=p.get("operation_key", "")), "Đã ghi thu hồi.")
        return redirect("control:case_detail", pk=pk)
    used = Discrepancy.objects.filter(evidence__isnull=False).values("pk")  # kể cả khoản đã hết hiệu lực
    return render(request, "control/case_detail.html", {
        "case": case, "evidence": case.evidence.select_related("exception", "discrepancy", "discrepancy__shift"),
        "verifications": case.verifications.select_related("actor"), "recoveries": case.recoveries.select_related("actor"),
        "free_discrepancies": Discrepancy.objects.current().filter(difference__lt=0).exclude(pk__in=used)
        .select_related("shift"),
        "operation_key": uuid.uuid4().hex,
    })


@capability_required(Cap.VIEW_DASHBOARD)
@require_GET
def adjustment_report(request, shift_id):
    shift = get_object_or_404(Shift, pk=shift_id)
    return render(request, "control/adjustment_report.html", {"shift": shift, "report": reports.adjustment_report(shift)})


@capability_required(Cap.MASTER_DATA)
@require_http_methods(["GET", "POST"])
def parameters(request):
    if request.method == "POST":
        p = request.POST
        key = p.get("key", "")
        try:
            when = None
            if p.get("effective_from"):
                when = timezone.make_aware(datetime.fromisoformat(p["effective_from"]))
            row = params.set_value(key, p.get("value", ""), request.user, when, p.get("reason", "").strip())
            label = params.DEFAULTS[key][2]
            if row.effective_from > timezone.now():
                messages.success(request, f"Đã lưu: {label}. Có hiệu lực từ "
                                          f"{timezone.localtime(row.effective_from):%H:%M %d/%m/%Y}.")
            else:
                messages.success(request, f"Đã lưu: {label}. Có hiệu lực ngay.")
        except (ValidationError, ValueError) as exc:
            messages.error(request, exc.messages[0] if hasattr(exc, "messages") else "Thời điểm hiệu lực không hợp lệ.")
        return redirect("control:parameters")
    now = timezone.now()
    rows = []
    for k, d in params.DEFAULTS.items():
        log = list(params.history(k)[:6])
        rows.append({"key": k, "value": params.get(k), "default": d[0], "unit": d[1], "label": d[2], "source": d[3],
                     "basis": params.BASIS[k][0], "basis_note": params.BASIS[k][1],
                     "assumption": params.BASIS[k][0] == params.ASSUMPTION,
                     "upcoming": [x for x in log if x.effective_from > now], "log": [x for x in log if x.effective_from <= now]})
    return render(request, "control/parameters.html", {"rows": rows})
