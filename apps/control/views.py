"""Màn hình ngoại lệ, vụ việc tổn thất, báo cáo điều chỉnh và tham số (FR-14, FR-17, FR-18, NFR-14)."""

import uuid
from datetime import datetime

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods

from apps.accounts.permissions import Cap, capability_required
from apps.audit.models import AuditLog
from apps.core import numbers, params
from apps.core.paging import paginate
from apps.core.templatetags.loi_thuong import loi_thuong
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


def _subject(exc):
    """Ngoại lệ này nói về ai, cái gì: nguyên liệu, nhân viên, đơn, ca."""
    parts = []
    if exc.ingredient_id:
        parts.append(exc.ingredient.name)
    if exc.employee_id:
        parts.append(str(exc.employee))
    if exc.order_id:
        parts.append(f"Đơn {exc.order.code}")
    if exc.shift_id and not exc.order_id:
        parts.append(str(exc.shift))
    if exc.period and not parts:
        parts.append(f"Tháng {exc.period[5:]}/{exc.period[:4]}")
    return " · ".join(parts)


def _next_open(exc):
    """Ngoại lệ chờ xem xét kế tiếp theo thứ tự danh sách (mới trước), quay vòng về đầu danh sách."""
    pending = ExceptionCase.objects.filter(status=ExceptionCase.Status.OPEN).exclude(pk=exc.pk)
    return pending.filter(created_at__lt=exc.created_at).order_by("-created_at").first() or pending.order_by(
        "-created_at").first()


@capability_required(Cap.EXCEPTION_REVIEW)
@require_GET
def exception_list(request):
    from django.db.models import Count, Sum

    status = request.GET.get("trang-thai", "cho_xem_xet")
    items = ExceptionCase.objects.select_related("employee", "shift", "order", "ingredient", "loss_case")
    if status in ExceptionCase.Status.values:
        items = items.filter(status=status)
    g = request.GET
    if g.get("muc") in ExceptionCase.Severity.values:
        items = items.filter(severity=g["muc"])
    by_kind = items.order_by().values("kind").annotate(n=Count("id"))
    if g.get("loai") in ExceptionCase.Kind.values:
        items = items.filter(kind=g["loai"])
    filtered = False
    for key, field in (("nhan_vien", "employee_id"), ("ca", "shift_id")):
        if (g.get(key) or "").isdigit():
            items = items.filter(**{field: int(g[key])})
            filtered = filtered or key == "nhan_vien"
    for key, lookup in (("tu", "created_at__date__gte"), ("den", "created_at__date__lte")):
        try:
            items = items.filter(**{lookup: datetime.strptime(g.get(key, ""), "%Y-%m-%d").date()})
            filtered = True
        except ValueError:
            pass
    page, qs = paginate(request, items.prefetch_related("reviews"))
    due = set(services.reminders_due().values_list("pk", flat=True))
    labels = dict(ExceptionCase.Kind.choices)
    for e in page.object_list:
        e.subject = _subject(e)
        e.result = next((r for r in sorted(e.reviews.all(), key=lambda r: r.created_at, reverse=True)
                         if r.superseded_by_id is None), None)
    pending = ExceptionCase.objects.filter(status=ExceptionCase.Status.OPEN)
    month_ago = timezone.now() - timezone.timedelta(days=30)
    reviewed = ExceptionReview.objects.filter(created_at__gte=month_ago, superseded_by__isnull=True)
    keep = g.copy()
    for key in ("loai", "trang"):
        keep.pop(key, None)
    from apps.accounts.models import User
    return render(request, "control/exceptions.html", {
        "items": page.object_list, "page": page, "qs": qs, "f": g, "status": status, "due": due,
        "kinds": sorted(({"value": k["kind"], "label": labels.get(k["kind"], k["kind"]), "n": k["n"]} for k in by_kind),
                        key=lambda k: -k["n"]),
        "kind_qs": keep.urlencode(), "filtered": filtered,
        "pending": pending.count(), "overdue": len(due), "pending_sum": pending.aggregate(s=Sum("amount"))["s"] or 0,
        "first_open": pending.order_by("-created_at").values_list("pk", flat=True).first(),
        "reviewed": reviewed.count(), "violations": reviewed.filter(result=ExceptionReview.Result.VIOLATION).count(),
        "staff": User.objects.filter(is_active=True).order_by("first_name"),
        "shift": Shift.objects.filter(pk=g["ca"]).first() if (g.get("ca") or "").isdigit() else None})


@capability_required(Cap.EXCEPTION_REVIEW)
@require_http_methods(["GET", "POST"])
def exception_detail(request, pk):
    exc = get_object_or_404(ExceptionCase.objects.select_related("employee", "shift", "order", "ingredient",
                                                                 "loss_case"), pk=pk)
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
            done = _run(request, lambda: services.review(request.user, exc.pk, p.get("result", ""),
                                                         money_loss=p.get("money_loss") == "1",
                                                         measure=p.get("measure", "").strip(),
                                                         correction_reason=p.get("correction_reason", "")),
                        "Đã ghi kết quả xem xét.")
            nxt = _next_open(exc) if done is not None and p.get("sau") == "tiep" else None
            if nxt is not None:
                return redirect("control:exception_detail", pk=nxt.pk)
        return redirect("control:exception_detail", pk=pk)
    trail = []
    if exc.order_id:
        from django.db.models import Q

        code = exc.order.code
        trail = AuditLog.objects.filter(
            Q(object_type="orders.Order", object_id=str(exc.order_id)) | Q(reason__contains=code)
            | Q(after__icontains=code)).select_related("actor").order_by("created_at")[:60]
    history = (ExceptionCase.objects.filter(employee=exc.employee).exclude(pk=exc.pk)[:20]
               if exc.employee_id else [])
    nxt = _next_open(exc)
    rule = loi_thuong(exc.rule)
    return render(request, "control/exception_detail.html", {
        "exc": exc, "rule": "" if rule == exc.get_kind_display() else rule, "reviews": exc.reviews.select_related("reviewer"),
        "effective": exc.effective_review(), "next": nxt,
        "pending": ExceptionCase.objects.filter(status=ExceptionCase.Status.OPEN).count(),
        "overdue": exc.pk in set(services.reminders_due().values_list("pk", flat=True)),
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
    status = request.GET.get("trang-thai", "")
    if status in LossCase.Status.values:
        cases = cases.filter(status=status)
    page, qs = paginate(request, cases)
    return render(request, "control/cases.html", {"cases": page.object_list, "page": page, "qs": qs, "status": status,
                                                  "statuses": LossCase.Status.choices, "operation_key": uuid.uuid4().hex})


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
            _run(request, lambda: services.verify(
                request.user, case, numbers.vnd(p.get("amount"), "Giá trị tổn thất", allow_zero=True),
                p.get("reason", "").strip()), "Đã ghi tổn thất đã xác minh.")
        elif action == "recover":
            _run(request, lambda: services.recover(
                request.user, case, numbers.vnd(p.get("amount"), "Số tiền thu hồi"), p.get("note", "").strip(),
                operation_key=p.get("operation_key", "")), "Đã ghi thu hồi.")
        return redirect("control:case_detail", pk=pk)
    used = Discrepancy.objects.filter(evidence__isnull=False).values("pk")  # kể cả khoản đã hết hiệu lực
    return render(request, "control/case_detail.html", {
        "case": case, "evidence": case.evidence.select_related("exception", "discrepancy", "discrepancy__shift"),
        "verifications": case.verifications.select_related("actor").order_by("created_at", "id"),
        "recoveries": case.recoveries.select_related("actor").order_by("created_at", "id"),
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
    for k in params.business_keys():
        d = params.DEFAULTS[k]
        log = list(params.history(k)[:6])
        rows.append({"key": k, "value": params.get(k), "default": d[0], "unit": d[1], "label": d[2], "source": d[3],
                     "basis": params.BASIS[k][0], "basis_note": params.BASIS[k][1],
                     "assumption": params.BASIS[k][0] == params.ASSUMPTION,
                     "upcoming": [x for x in log if x.effective_from > now], "log": [x for x in log if x.effective_from <= now]})
    return render(request, "control/parameters.html", {"rows": rows})


@capability_required(Cap.HANDLE_ALERTS)
@require_http_methods(["GET", "POST"])
def alert_center(request):
    """Trung tâm cảnh báo: chỉ các mục người dùng là người xử lý chính hoặc đã được chuyển cấp (AC-103)."""
    from . import alerts

    if request.method == "POST":
        p = request.POST
        if p.get("action") == "take":
            _run(request, lambda: alerts.take(request.user, p.get("alert")), "Đã nhận xử lý.")
        else:
            _run(request, lambda: alerts.close(request.user, p.get("alert"), p.get("note", "")), "Đã đóng cảnh báo.")
        return redirect("control:alerts")
    from .models import Alert

    mine = alerts.visible_to(request.user).select_related("assignee", "taken_by", "closed_by")
    open_alerts = list(mine.filter(status__in=Alert.OPEN).order_by("due_at"))
    groups = {}
    for a in open_alerts:
        label = a.get_kind_display()
        a.short = loi_thuong(a.title.split(": ", 1)[1] if ": " in a.title else a.title)
        a.note = loi_thuong(a.detail)
        if a.note.rstrip(".") == a.short:
            a.note = ""
        groups.setdefault(a.kind, {"kind": a.kind, "label": label, "items": [], "overdue": 0})
        groups[a.kind]["items"].append(a)
        groups[a.kind]["overdue"] += a.is_overdue
    groups = sorted(groups.values(), key=lambda g: (-g["overdue"], g["label"]))
    for g in groups:
        g["first"], g["rest"] = g["items"][:5], g["items"][5:]
    context = {"groups": groups, "open_count": len(open_alerts),
               "overdue": sum(a.is_overdue for a in open_alerts),
               "urgent": sum(a.severity == Alert.Severity.URGENT for a in open_alerts),
               "closed": mine.filter(status=Alert.Status.CLOSED).order_by("-closed_at")[:10]}
    if request.user.is_owner:
        context["stats"] = alerts.weekly_stats()
    return render(request, "control/alerts.html", context)
