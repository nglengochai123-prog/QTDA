"""Bảng điều khiển và báo cáo theo kỳ (FR-50, FR-52, FR-53, FR-54).

Mọi số liệu tính lại từ giao dịch và đính chính đang có hiệu lực (GD-10), không chụp cứng.
"""

from collections import OrderedDict
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.db.models import Count, Sum
from django.utils import timezone

BO02_MONTHLY_TARGET = 1  # BO-01, BO-02: chỉ tiêu dự án, không phải tham số cảnh báo


def period_bounds(start_day, end_day):
    start = timezone.make_aware(datetime.combine(start_day, time.min))
    end = timezone.make_aware(datetime.combine(end_day + timedelta(days=1), time.min))
    return start, end


def month_bounds(day):
    first = day.replace(day=1)
    nxt = (first + timedelta(days=32)).replace(day=1)
    return first, nxt - timedelta(days=1)


# ---------------- FR-53: doanh thu ----------------

DIMENSIONS = OrderedDict([
    ("ngay", "Ngày"), ("khung_gio", "Khung giờ"), ("ca", "Ca"), ("nhom_mon", "Nhóm món"), ("mon", "Món"),
    ("nhan_vien", "Nhân viên tạo đơn"), ("phuong_thuc", "Phương thức thanh toán"),
])


def _paid_lines(start, end):
    from apps.orders.models import OrderLine

    return (OrderLine.objects.filter(order__status="da_thanh_toan", order__payment__created_at__gte=start,
                                     order__payment__created_at__lt=end)
            .select_related("order", "order__payment", "order__shift", "order__created_by", "item__group"))


def _key(line, dim):
    order = line.order
    local = timezone.localtime(order.payment.created_at)
    created = timezone.localtime(order.created_at)
    return {
        "ngay": f"{local:%d/%m/%Y}", "khung_gio": f"{created:%H}–{(created + timedelta(hours=1)):%H} giờ",
        "ca": str(order.shift) if order.shift else "Không gắn ca", "nhom_mon": line.item.group.name,
        "mon": f"{line.item_name} {line.size_name}", "nhan_vien": str(order.created_by),
        "phuong_thuc": order.payment.get_method_display(),
    }[dim]


def revenue(start_day, end_day, dim="ngay"):
    """Doanh thu theo chiều `dim` = giá trị món tính tiền của các đơn đã thanh toán trong kỳ (AC-105)."""
    from apps.shifts.models import Refund

    start, end = period_bounds(start_day, end_day)
    rows, total, orders = {}, 0, set()
    for line in _paid_lines(start, end):
        value = line.unit_price * line.billable_quantity
        key = _key(line, dim)
        row = rows.setdefault(key, {"key": key, "revenue": 0, "cups": 0, "orders": set()})
        row["revenue"] += value
        row["cups"] += line.billable_quantity
        row["orders"].add(line.order_id)
        total += value
        orders.add(line.order_id)
    result = sorted(rows.values(), key=lambda r: r["key"])
    for r in result:
        r["orders"] = len(r["orders"])
    refunds = (Refund.objects.filter(status=Refund.Status.PAID, paid_at__gte=start, paid_at__lt=end)
               .aggregate(s=Sum("amount"))["s"] or 0)
    length = (end_day - start_day).days + 1
    prev_start, prev_end = start_day - timedelta(days=length), start_day - timedelta(days=1)
    p_start, p_end = period_bounds(prev_start, prev_end)
    previous = sum(l.unit_price * l.billable_quantity for l in _paid_lines(p_start, p_end))
    return {"rows": result, "total": total, "orders": len(orders), "refunds": refunds, "net": total - refunds,
            "previous": previous, "previous_period": (prev_start, prev_end), "dim": dim, "dim_label": DIMENSIONS[dim]}


def revenue_xlsx(start_day, end_day):
    from apps.core import xlsx

    sheets = []
    for dim, label in DIMENSIONS.items():
        data = revenue(start_day, end_day, dim)
        rows = [[label, "Số đơn", "Số ly", "Doanh thu (đồng)"]]
        rows += [[r["key"], r["orders"], r["cups"], r["revenue"]] for r in data["rows"]]
        rows += [["Tổng", data["orders"], "", data["total"]], ["Hoàn tiền đã trả trong kỳ", "", "", data["refunds"]],
                 ["Doanh thu thuần", "", "", data["net"]]]
        sheets.append((label, rows))
    return xlsx.build(sheets)


# ---------------- FR-52: kiểm soát doanh thu ----------------

def revenue_control(start_day, end_day):
    from apps.control.models import ExceptionCase, LossCase
    from apps.control.services import BO01_MONTHLY_TARGET, monthly_control
    from apps.orders.models import AdjustmentRequest
    from apps.shifts.models import Discrepancy
    from apps.shifts.services import accumulated_report

    start, end = period_bounds(start_day, end_day)
    requests = AdjustmentRequest.objects.filter(created_at__gte=start, created_at__lt=end)
    by_reason = (requests.values("reason__name", "status").annotate(n=Count("id")).order_by("reason__name", "status"))
    status_labels = dict(AdjustmentRequest.Status.choices)
    for r in by_reason:
        r["status_label"] = status_labels.get(r["status"], r["status"])
    exceptions = ExceptionCase.objects.filter(created_at__gte=start, created_at__lt=end).prefetch_related("reviews")
    exc_rows = {}
    for exc in exceptions:
        review = exc.effective_review()
        key = (exc.get_kind_display(), review.get_result_display() if review else "Chưa xem xét")
        exc_rows[key] = exc_rows.get(key, 0) + 1
    discrepancies = (Discrepancy.objects.current().filter(shift__starts_at__gte=start, shift__starts_at__lt=end)
                     .select_related("shift", "manager").order_by("shift__starts_at"))
    control = monthly_control(start_day.year, start_day.month)
    return {
        "requests_total": requests.count(), "by_reason": by_reason,
        "exceptions": [{"kind": k[0], "result": k[1], "n": n} for k, n in sorted(exc_rows.items())],
        "discrepancies": discrepancies, "accumulated": accumulated_report(start_day.year, start_day.month),
        "cases": LossCase.objects.filter(created_at__gte=start, created_at__lt=end)
        .prefetch_related("verifications", "recoveries"),
        "control": control, "target": BO01_MONTHLY_TARGET, "met": control["control_value"] < BO01_MONTHLY_TARGET,
    }


# ---------------- FR-54: nguyên vật liệu ----------------

def materials(start_day, end_day):
    """Mỗi nguyên liệu: tồn đầu + nhập − tiêu hao theo món − hao hụt ± kiểm kê = tồn cuối (AC-106)."""
    from apps.inventory.models import Ingredient, ShortageCase, StockMovement
    from apps.orders.models import PostPrepCancellation

    start, end = period_bounds(start_day, end_day)
    post_prep = {}
    for ppc in PostPrepCancellation.objects.filter(created_at__gte=start, created_at__lt=end):
        for ing, qty in ppc.usage.items():
            post_prep[int(ing)] = post_prep.get(int(ing), Decimal(0)) + Decimal(str(qty))
    shortages = dict(ShortageCase.objects.filter(day__gte=start_day, day__lte=end_day)
                     .values_list("ingredient").annotate(n=Count("id")))
    rows = []
    for ing in Ingredient.objects.order_by("name"):
        moves = StockMovement.objects.filter(ingredient=ing)
        opening = moves.filter(created_at__lt=start).aggregate(s=Sum("quantity"))["s"] or Decimal(0)
        period = moves.filter(created_at__gte=start, created_at__lt=end)
        sums = {k: Decimal(0) for k in StockMovement.Kind.values}
        for kind, total in period.values_list("kind").annotate(s=Sum("quantity")):
            sums[kind] = total
        closing = opening + sum(sums.values())
        rows.append({
            # Tồn đầu kỳ khai báo lần đầu trong kỳ (lúc bắt đầu dùng hệ thống) cộng vào tồn đầu.
            "ingredient": ing, "opening": opening + sums[StockMovement.Kind.OPENING], "receipts": sums[StockMovement.Kind.RECEIPT],
            "consumed": -sums[StockMovement.Kind.CONSUME], "post_prep": post_prep.get(ing.pk, Decimal(0)),
            "waste": -sums[StockMovement.Kind.WASTE], "count_adjust": sums[StockMovement.Kind.COUNT],
            "closing": closing, "shortages": shortages.get(ing.pk, 0),
        })
    total_shortages = sum(shortages.values())
    return {"rows": rows, "shortages": total_shortages, "bo02_target": BO02_MONTHLY_TARGET}


# ---------------- FR-50: bảng điều khiển ----------------

def dashboard(today=None):
    from apps.control.models import Alert, ExceptionCase
    from apps.control.services import BO01_MONTHLY_TARGET, monthly_control
    from apps.inventory.models import Ingredient, ShortageCase
    from apps.shifts.services import accumulated_report

    today = today or timezone.localdate()
    first, last = month_bounds(today)
    control = monthly_control(today.year, today.month)
    shortages = ShortageCase.objects.filter(day__gte=first, day__lte=last).count()
    by_day = revenue(first, min(last, today), "ngay")
    peak = max([r["revenue"] for r in by_day["rows"]] or [0])
    for r in by_day["rows"]:
        r["width"] = round(r["revenue"] * 100 / peak) if peak else 0
    critical = []
    for ing in Ingredient.objects.filter(is_critical=True, is_active=True).select_related("stock"):
        stock = getattr(ing, "stock", None)
        available = stock.available if stock else Decimal(0)
        critical.append({"ingredient": ing, "physical": stock.physical if stock else Decimal(0), "available": available,
                         "below": available < ing.safety_stock})
    open_alerts = Alert.objects.filter(status__in=Alert.OPEN)
    return {
        "today": today, "control": control, "bo01_target": BO01_MONTHLY_TARGET,
        "bo01_met": control["control_value"] < BO01_MONTHLY_TARGET,
        "shortages": shortages, "bo02_target": BO02_MONTHLY_TARGET, "bo02_met": shortages <= BO02_MONTHLY_TARGET,
        "by_day": by_day, "accumulated": sum(r["total"] for r in accumulated_report(today.year, today.month)),
        "critical": critical,
        "alerts": {"khan": open_alerts.filter(severity="khan").count(),
                   "quan_trong": open_alerts.filter(severity="quan_trong").count(),
                   "overdue": open_alerts.filter(due_at__lt=timezone.now()).count()},
        "exceptions": {label: ExceptionCase.objects.filter(status=ExceptionCase.Status.OPEN, severity=value).count()
                       for value, label in ExceptionCase.Severity.choices},
    }
