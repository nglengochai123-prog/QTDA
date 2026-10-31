"""Tra cứu đơn có bộ lọc, phân trang và trang chi tiết đơn (truy vết từ báo cáo tới giao dịch gốc, NFR-19)."""

from datetime import datetime, time, timedelta

from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_GET

from apps.accounts.models import User
from apps.accounts.permissions import Cap, capability_required
from apps.catalog.models import ItemSize, MenuGroup, Table
from apps.core.dates import parse_day as _day
from apps.core.paging import paginate

from .models import Order, Payment


def _bounds(start, end):
    tz = timezone.get_current_timezone()
    lo = timezone.make_aware(datetime.combine(start, time.min), tz) if start else None
    hi = timezone.make_aware(datetime.combine(end + timedelta(days=1), time.min), tz) if end else None
    return lo, hi


ADVANCED_FILTERS = ("theo", "tu", "den", "trang_thai", "phuong_thuc", "ban", "nhan_vien", "mon")


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
    if params.get("theo") == "thanh_toan":
        from apps.reports import receipts

        lo, hi = _bounds(_day(params.get("tu")), _day(params.get("den")))
        lo = lo or timezone.make_aware(datetime(1970, 1, 1))
        hi = hi or timezone.now() + timedelta(days=1)
        selected = [e for e in receipts.entries(lo, hi) if receipts.matches(e, params)]
        ids = {oid for entry in selected for oid in entry["order_ids"]}
        qs = qs.filter(pk__in=ids)
        if (params.get("ban") or "").isdigit():
            qs = qs.filter(table_id=int(params["ban"]))
        allowed = set(qs.values_list("pk", flat=True))
        qs.receipt_entries = [e for e in selected if allowed.intersection(e["order_ids"])]
        return qs
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
    entries = getattr(qs, "receipt_entries", None)
    receipt_total = sum(e["amount"] for e in entries) if entries is not None else None
    page, qs_params = paginate(request, qs)
    page_ids = {o.pk for o in page.object_list}
    receipt_rows = {}
    for entry in entries or []:
        if not page_ids.intersection(entry["order_ids"]):
            continue
        payment = entry["payment"]
        row = receipt_rows.setdefault(payment.pk, {"payment": payment, "amount": 0, "legacy": entry["legacy"]})
        row["amount"] += entry["amount"]
    advanced = sum(1 for key in ADVANCED_FILTERS if request.GET.get(key))
    total = Order.objects.filter(pk__in=qs.values("pk")).aggregate(s=Sum("total"))["s"] or 0
    return render(request, "orders/lookup.html", {
        "page": page, "qs": qs_params, "f": request.GET, "statuses": Order.Status.choices,
        "advanced": advanced, "filtered": advanced or any(request.GET.get(k) for k in ("q", "ca", "nhom", "gio", "da_thu")),
        "count_total": total, "receipt_total": receipt_total, "receipt_rows": list(receipt_rows.values()),
        "methods": Payment.Method.choices, "tables": Table.objects.filter(is_active=True),
        "staff": User.objects.filter(is_active=True).order_by("first_name"),
        "sizes": ItemSize.objects.select_related("item").order_by("item__name", "price"),
        "groups": MenuGroup.objects.all(),
    })


@capability_required(Cap.VIEW_DASHBOARD)
@require_GET
def order_detail(request, order_id):
    from apps.audit.models import AuditLog
    from apps.shifts.models import Refund

    order = get_object_or_404(Order.objects.select_related("table", "created_by", "payment", "shift"), pk=order_id)
    requests = [str(pk) for pk in order.adjustment_requests.values_list("pk", flat=True)]
    trail = AuditLog.objects.filter(
        Q(object_type="orders.Order", object_id=str(order.pk)) | Q(reason__contains=order.code)
        | Q(after__icontains=order.code) | Q(object_repr__contains=order.code)
        | Q(object_type="orders.AdjustmentRequest", object_id__in=requests)).order_by("created_at")[:100]
    return render(request, "orders/detail.html", {
        "order": order, "lines": order.lines.prefetch_related("options").select_related("recipe_version"),
        "requests": order.adjustment_requests.select_related("reason", "requested_by", "decided_by"),
        "refunds": Refund.objects.filter(order_code=order.code), "slip": getattr(order, "backup_slip", None),
        "charges": order.prepaid_charges.select_related("payment", "collected_by"),
        "trail": trail,
    })
