"""Tổng quan ca hiện tại cho phần Bán hàng: bàn, món đang pha, món chờ mang ra, yêu cầu chờ duyệt,
bàn chờ thanh toán, người trong ca và món sắp hết. Chỉ đọc, không ghi gì."""

from statistics import median

from django.utils import timezone

from apps.core import params

from .models import AdjustmentRequest, Order, OrderLine

LOW_CUPS = 10  # Món còn đáp ứng từ số ly này trở xuống thì hiện ở mục Món sắp hết.

# Tình trạng bàn theo thứ tự ưu tiên: bàn vừa có yêu cầu chờ duyệt vừa có món chờ pha thì hiện là chờ duyệt.
TABLE_STATES = {
    "duyet": ("Chờ duyệt", "warn"),
    "mang_ra": ("Có món chờ mang ra", "ok"),
    "pha": ("Đang pha", "info"),
    "thanh_toan": ("Chờ thanh toán", "neutral"),
}


def _minutes(since, now):
    return max(int((now - since).total_seconds() // 60), 0)


def _tables(now, wait_standard):
    from apps.catalog.models import Table

    orders = (Order.objects.filter(payment__isnull=True).exclude(status__in=[Order.Status.PAID, Order.Status.CANCELLED])
              .prefetch_related("lines", "adjustment_requests").order_by("created_at"))
    by_table = {}
    for order in orders:
        by_table.setdefault(order.table_id, []).append(order)
    rows = []
    for table in Table.objects.filter(is_active=True).order_by("sort_order", "code"):
        open_orders = by_table.get(table.pk, [])
        row = {"table": table, "orders": open_orders, "state": "", "label": "Trống", "tone": "",
               "waiting": 0, "ready": 0, "amount": 0, "minutes": None, "slow": False, "link_order": None}
        if open_orders:
            lines = [l for o in open_orders for l in o.lines.all()]
            row["waiting"] = sum(l.pending_quantity for l in lines if l.status == OrderLine.Status.WAITING)
            row["ready"] = sum(l.billable_quantity for l in lines if l.status == OrderLine.Status.DONE)
            row["amount"] = sum(o.total for o in open_orders)
            row["minutes"] = _minutes(open_orders[0].created_at, now)
            pending = any(r.status == AdjustmentRequest.Status.PENDING for o in open_orders
                          for r in o.adjustment_requests.all())
            state = ("duyet" if pending else "mang_ra" if row["ready"] else "pha" if row["waiting"]
                     else "thanh_toan")
            row["state"] = state
            row["label"], row["tone"] = TABLE_STATES[state]
            # Khách chờ lâu: còn món chưa mang ra và đơn cũ nhất chưa xong đã quá chuẩn thời gian chờ.
            unserved = [o for o in open_orders if any(l.status in (OrderLine.Status.WAITING, OrderLine.Status.DONE)
                                                      for l in o.lines.all())]
            row["slow"] = bool(unserved) and _minutes(unserved[0].created_at, now) > wait_standard
            row["link_order"] = open_orders[0].pk
        rows.append(row)
    return rows


def _areas(rows):
    areas = {}
    for row in rows:
        areas.setdefault(row["table"].area or "Chưa chia khu", []).append(row)
    return list(areas.items())


def _bar(now, backlog_limit):
    lines = list(OrderLine.objects.filter(status=OrderLine.Status.WAITING).select_related("order"))
    cups = sum(l.pending_quantity for l in lines)
    oldest = min((l.order.created_at for l in lines), default=None)
    return {"cups": cups, "tickets": len({l.order_id for l in lines}),
            "oldest": _minutes(oldest, now) if oldest else None, "over": cups > backlog_limit}


def _ready(now):
    lines = list(OrderLine.objects.filter(status=OrderLine.Status.DONE).select_related("order__table"))
    oldest = min((l.done_at for l in lines if l.done_at), default=None)
    return {"cups": sum(l.billable_quantity for l in lines),
            "tables": sorted({l.order.table.code for l in lines}),
            "oldest": _minutes(oldest, now) if oldest else None}


def _approvals(user, now):
    from .adjustments import approver_ids

    pending = (AdjustmentRequest.objects.filter(status=AdjustmentRequest.Status.PENDING)
               .select_related("order", "order__table", "line", "target_table", "requested_by").order_by("created_at"))
    rows = []
    for req in pending:
        level = req.effective_level(now)
        rows.append({"req": req, "summary": req.summary(), "minutes": _minutes(req.created_at, now),
                     "level": AdjustmentRequest.Level(level).label,
                     "exhausted": level == AdjustmentRequest.Level.EXHAUSTED,
                     "mine": user.pk in approver_ids(req, now)})
    return rows


def _shift_sales(shift, now):
    if shift is None:
        return None
    orders = Order.objects.filter(shift=shift).exclude(status=Order.Status.CANCELLED)
    lines = list(OrderLine.objects.filter(order__in=orders).select_related("order", "order__backup_slip"))
    cups = sum(l.billable_quantity for l in lines)
    waits = [(l.served_at - l.order.created_at).total_seconds() / 60 for l in lines
             if l.served_at and not hasattr(l.order, "backup_slip")]
    return {"orders": orders.count(), "cups": cups,
            "paid": orders.filter(status=Order.Status.PAID).count(),
            "median_wait": round(median(waits)) if waits else None}


def _people(now):
    """Người đang chấm công và người có lịch ca này nhưng chưa vào ca."""
    from apps.accounts.models import Role
    from apps.schedule.models import Assignment, WeekPublish
    from apps.schedule.services import week_start
    from apps.staff.models import Attendance

    local = timezone.localtime(now)
    rows = {}
    for att in Attendance.objects.filter(clock_out__isnull=True).select_related("user").order_by("clock_in"):
        rows[att.user_id] = {"user": att.user, "role": att.get_role_display(), "since": att.clock_in, "absent": False}
    if WeekPublish.objects.filter(week_start=week_start(local.date())).exists():
        planned = (Assignment.objects.filter(removed_at__isnull=True, shift__date=local.date(),
                                             shift__start__lte=local.time(), shift__end__gt=local.time())
                   .select_related("user", "shift"))
        for a in planned:
            if a.user_id not in rows:
                label = Role(a.role).label if a.role in Role.values else a.role
                rows[a.user_id] = {"user": a.user, "role": label, "since": None, "absent": True,
                                   "shift": a.shift}
    return sorted(rows.values(), key=lambda r: (r["absent"], r["role"], str(r["user"])))


def _low_items():
    from apps.catalog.models import ItemSize

    from .services import availability

    left = {k: v for k, v in availability().items() if v is not None and v <= LOW_CUPS}
    sizes = ItemSize.objects.filter(pk__in=left).select_related("item")
    return sorted(({"name": f"{s.item.name} {s.name}", "left": left[s.pk]} for s in sizes),
                  key=lambda r: (r["left"], r["name"]))


def shift_overview(user, now=None):
    from apps.accounts.permissions import Cap, user_can
    from apps.inventory.models import QuickReport
    from apps.shifts.models import Shift
    from apps.shifts.services import figures

    now = now or timezone.now()
    wait_standard = params.get("wait_standard_minutes")
    shift = Shift.objects.operating(now)
    tables = _tables(now, wait_standard)
    busy = [t for t in tables if t["state"]]
    to_pay = [t for t in busy if t["state"] == "thanh_toan"]
    approvals = _approvals(user, now)
    can_money = user_can(user, Cap.PAYMENT)
    return {
        "now": now, "shift": shift,
        "money": figures(shift) if shift and can_money else None,
        "sales": _shift_sales(shift, now),
        "tables": tables, "areas": _areas(tables),
        "tables_busy": len(busy), "tables_total": len(tables), "tables_free": len(tables) - len(busy),
        "states": [(label, tone, sum(1 for t in busy if t["state"] == key)) for key, (label, tone) in TABLE_STATES.items()],
        "slow_tables": [t for t in busy if t["slow"]],
        "to_pay": {"tables": len(to_pay), "amount": sum(t["amount"] for t in to_pay)},
        "open_amount": sum(t["amount"] for t in busy),
        "bar": _bar(now, params.get("bar_backlog_limit")), "ready": _ready(now),
        "approvals": approvals, "my_approvals": sum(1 for a in approvals if a["mine"]),
        "people": _people(now), "low_items": _low_items(),
        "quick_reports": QuickReport.objects.filter(acknowledged_at__isnull=True).select_related("ingredient"),
        "wait_standard": wait_standard, "can_money": can_money,
        "can_bar": user_can(user, Cap.BAR_PREPARE), "can_pay": can_money,
        "can_approve": user_can(user, Cap.ORDER_ADJUST_APPROVE),
    }
