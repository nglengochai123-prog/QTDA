"""Tra cứu đơn có bộ lọc, phân trang và trang chi tiết đơn (truy vết từ báo cáo tới giao dịch gốc, NFR-19)."""

from datetime import date, datetime, time, timedelta

from django.db.models import Q
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_GET

from apps.accounts.models import User
from apps.accounts.permissions import Cap, capability_required
from apps.catalog.models import ItemSize, MenuGroup, Table
from apps.core.paging import paginate

from .models import Order, Payment


def _day(value):
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _bounds(start, end):
    tz = timezone.get_current_timezone()
    lo = timezone.make_aware(datetime.combine(start, time.min), tz) if start else None
    hi = timezone.make_aware(datetime.combine(end + timedelta(days=1), time.min), tz) if end else None
    return lo, hi


def filter_orders(params):
    """Bộ lọc dùng chung cho trang tra cứu và cho liên kết từ báo cáo doanh thu (cùng cách tính)."""
    qs = Order.objects.select_related("table", "created_by", "payment", "shift").order_by("-created_at")
    q = (params.get("q") or "").strip()
    if q:
        qs = qs.filter(Q(code__icontains=q) | Q(table__code=q) | Q(note__icontains=q))
    if params.get("trang_thai") in Order.Status.values:
        qs = qs.filter(status=params["trang_thai"])
    if params.get("da_thu") == "1":  # cùng phạm vi với báo cáo doanh thu: đơn đã thu tiền (kể cả sau đó hủy hóa đơn)
        qs = qs.filter(payment__isnull=False)
    basis = "payment__created_at" if params.get("theo") == "thanh_toan" else "created_at"
    lo, hi = _bounds(_day(params.get("tu")), _day(params.get("den")))
    if lo:
        qs = qs.filter(**{f"{basis}__gte": lo})
    if hi:
        qs = qs.filter(**{f"{basis}__lt": hi})
    if params.get("gio", "").isdigit():
        qs = qs.filter(created_at__hour=int(params["gio"]))  # giờ theo múi UTC+7 hiện hành
    for key, field in (("ban", "table_id"), ("ca", "shift_id"), ("nhan_vien", "created_by_id")):
        if (params.get(key) or "").isdigit():
            qs = qs.filter(**{field: int(params[key])})
    if params.get("phuong_thuc") in Payment.Method.values:
        qs = qs.filter(payment__method=params["phuong_thuc"])
    if (params.get("mon") or "").isdigit():
        qs = qs.filter(lines__size_id=int(params["mon"])).distinct()
    if (params.get("nhom") or "").isdigit():
        qs = qs.filter(lines__item__group_id=int(params["nhom"])).distinct()
    return qs


@capability_required(Cap.VIEW_DASHBOARD)
@require_GET
def order_lookup(request):
    qs = filter_orders(request.GET)
    page, qs_params = paginate(request, qs)
    return render(request, "orders/lookup.html", {
        "page": page, "qs": qs_params, "f": request.GET, "statuses": Order.Status.choices,
        "methods": Payment.Method.choices, "tables": Table.objects.filter(is_active=True),
        "staff": User.objects.filter(is_active=True).order_by("first_name"),
        "sizes": ItemSize.objects.select_related("item").order_by("item__name", "price"),
        "groups": MenuGroup.objects.all(),
        "page_total": sum(o.total for o in page.object_list),
    })


@capability_required(Cap.VIEW_DASHBOARD)
@require_GET
def order_detail(request, order_id):
    from apps.audit.models import AuditLog
    from apps.shifts.models import Refund

    order = get_object_or_404(Order.objects.select_related("table", "created_by", "payment", "shift"), pk=order_id)
    trail = AuditLog.objects.filter(
        Q(object_type="orders.Order", object_id=str(order.pk)) | Q(reason__contains=order.code)
        | Q(after__icontains=order.code)).order_by("created_at")[:100]
    return render(request, "orders/detail.html", {
        "order": order, "lines": order.lines.prefetch_related("options").select_related("recipe_version"),
        "requests": order.adjustment_requests.select_related("reason", "requested_by", "decided_by"),
        "refunds": Refund.objects.filter(order_code=order.code), "slip": getattr(order, "backup_slip", None),
        "trail": trail,
    })
