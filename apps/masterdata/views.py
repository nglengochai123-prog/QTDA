"""Tra cứu nhật ký thao tác (FR-61): chỉ xem, lọc theo người, thao tác, loại dữ liệu và ngày."""

from datetime import date

from django.db.models import Q
from django.shortcuts import render
from django.views.decorators.http import require_GET

from apps.accounts.models import User
from apps.accounts.permissions import Cap, capability_required
from apps.audit.models import Action, AuditLog
from apps.core.paging import paginate


def _day(value):
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


@capability_required(Cap.AUDIT_LOG)
@require_GET
def audit_log(request):
    g = request.GET
    qs = AuditLog.objects.select_related("actor").order_by("-created_at")
    q = (g.get("q") or "").strip()
    if q:
        qs = qs.filter(Q(object_repr__icontains=q) | Q(reason__icontains=q) | Q(actor_label__icontains=q)
                       | Q(object_id=q))
    if g.get("thao_tac") in Action.values:
        qs = qs.filter(action=g["thao_tac"])
    if (g.get("nguoi") or "").isdigit():
        qs = qs.filter(actor_id=int(g["nguoi"]))
    if g.get("loai"):
        qs = qs.filter(object_type=g["loai"])
    if _day(g.get("tu")):
        qs = qs.filter(created_at__date__gte=_day(g["tu"]))
    if _day(g.get("den")):
        qs = qs.filter(created_at__date__lte=_day(g["den"]))
    page, qs_params = paginate(request, qs, per_page=50)
    return render(request, "masterdata/audit_log.html", {
        "page": page, "qs": qs_params, "f": g, "actions": Action.choices,
        "people": User.objects.order_by("first_name"),
        "types": AuditLog.objects.order_by().values_list("object_type", flat=True).distinct(),
    })
