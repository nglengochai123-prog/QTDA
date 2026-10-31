"""Bảng điều khiển và báo cáo theo kỳ (FR-50, FR-52, FR-53, FR-54).

Tiền theo giao dịch thu/hoàn; phân bổ món giữ tại lúc thu trong nhật ký bất biến.
"""

from collections import OrderedDict
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.db.models import Count, Sum
from django.utils import timezone

from apps.core import numbers

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

    # Dòng món hiện tại dùng để ước tính giá vốn. Tiền thu đọc từ receipts, không từ các dòng này.
    return (OrderLine.objects.filter(order__payment__isnull=False, order__payment__created_at__gte=start,
                                     order__payment__created_at__lt=end)
            .select_related("order", "order__payment", "order__shift", "order__created_by", "item__group"))


def paid_lines(start_day, end_day):
    """Dòng món đã thu tiền của kỳ, nạp một lần để báo cáo và phân tích dùng chung."""
    return list(_paid_lines(*period_bounds(start_day, end_day)))


def _paid_total(start, end):
    """Tiền đã thu trong kỳ, gồm thu thêm; không loại khoản đã thu rồi hoàn."""
    from apps.orders.models import Payment

    return Payment.objects.filter(created_at__gte=start, created_at__lt=end).aggregate(s=Sum("amount"))["s"] or 0


def revenue_link(start_day, end_day, row_filter):
    """Chuỗi tham số cho Tra cứu đơn cùng phạm vi báo cáo: đơn đã thu tiền, theo ngày thanh toán."""
    from urllib.parse import urlencode

    if row_filter is None:
        return ""
    params = {"da_thu": "1", "theo": "thanh_toan", "tu": start_day.isoformat(), "den": end_day.isoformat()}
    name, value = row_filter
    if name == "ngay":
        params["tu"] = params["den"] = value
    else:
        params[name] = value
    return urlencode(params)


def revenue(start_day, end_day, dim="ngay", lines=None):
    """Receipts by collection date/shift/method, with immutable item allocation and actual refunds."""
    from apps.shifts.models import Refund
    from . import receipts

    start, end = period_bounds(start_day, end_day)
    rows, total, orders, legacy = {}, 0, set(), 0
    for entry in receipts.entries(start, end):
        payment = entry["payment"]
        key = receipts.key(entry, dim)
        at = timezone.localtime(payment.created_at)
        sort = (at.date().toordinal() if dim == "ngay" else at.hour if dim == "khung_gio" else
                payment.shift.starts_at.timestamp() if dim == "ca" and payment.shift else 0)
        row = rows.setdefault(key, {"key": key, "revenue": 0, "cups": 0, "orders": set(),
                                    "filters": set(), "sort": (sort, key), "refunds": 0})
        row["filters"].add(receipts.row_filter(entry, dim))
        row["revenue"] += entry["amount"]
        row["cups"] += entry["cups"]
        row["orders"].update(entry["order_ids"])
        total += entry["amount"]
        orders.update(entry["order_ids"])
        if entry["legacy"]:
            legacy += entry["amount"]
    refund_rows = list(Refund.objects.filter(status=Refund.Status.PAID, paid_at__gte=start, paid_at__lt=end)
                       .select_related("shift"))
    refunds = sum(r.amount for r in refund_rows)
    money_dimension = dim in ("ngay", "khung_gio", "ca", "phuong_thuc")
    if money_dimension:
        for refund in refund_rows:
            at = timezone.localtime(refund.paid_at)
            key = {"ngay": at.strftime("%d/%m/%Y"), "khung_gio": f"{at:%H}–{at.hour + 1:02d} giờ",
                   "ca": str(refund.shift) if refund.shift else "Không gắn ca",
                   "phuong_thuc": refund.get_method_display()}[dim]
            sort = (at.date().toordinal() if dim == "ngay" else at.hour if dim == "khung_gio" else
                    refund.shift.starts_at.timestamp() if dim == "ca" and refund.shift else 0)
            row = rows.setdefault(key, {"key": key, "revenue": 0, "cups": 0, "orders": set(),
                                        "filters": set(), "sort": (sort, key), "refunds": 0})
            row["refunds"] += refund.amount
    result = sorted(rows.values(), key=lambda r: r["sort"])
    for row in result:
        row.pop("sort")
        row["orders"] = len(row["orders"])
        filters = row.pop("filters")
        row["link"] = revenue_link(start_day, end_day, next(iter(filters))) if len(filters) == 1 else ""
        row["net"] = row["revenue"] - row["refunds"]
    length = (end_day - start_day).days + 1
    previous_period = (start_day - timedelta(days=length), start_day - timedelta(days=1))
    return {"rows": result, "total": total, "orders": len(orders), "refunds": refunds, "net": total - refunds,
            "cups": sum(r["cups"] for r in result), "previous": _paid_total(*period_bounds(*previous_period)),
            "previous_period": previous_period, "dim": dim, "dim_label": DIMENSIONS[dim],
            "money_dimension": money_dimension, "legacy_amount": legacy}


def revenue_xlsx(start_day, end_day):
    from apps.core import xlsx

    sheets, lines = [], paid_lines(start_day, end_day)
    for dim, label in DIMENSIONS.items():
        data = revenue(start_day, end_day, dim, lines)
        rows = [[label, "Số đơn có khoản thu", "Số ly ghi lúc thu đầu", "Tiền đã thu (đồng)", "Tiền đã hoàn", "Thu trừ hoàn"]]
        rows += [[r["key"], r["orders"], r["cups"], r["revenue"], r["refunds"] if data["money_dimension"] else "Không phân bổ", r["net"] if data["money_dimension"] else "Không phân bổ"] for r in data["rows"]]
        rows += [["Tổng", data["orders"], data["cups"], data["total"]], ["Hoàn tiền đã trả trong kỳ", "", "", data["refunds"]],
                 ["Doanh thu thuần", "", "", data["net"]]]
        rows.append(["Phân bổ theo món tại lúc thu; thu thêm không đếm thêm ly. Dữ liệu cũ chưa có phân bổ: " + str(data["legacy_amount"]) + " đồng."])
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
        key = (exc.get_kind_display(), review.get_result_display() if review else "Chưa xem xét", exc.kind, review.result if review else "chua_xem")
        exc_rows[key] = exc_rows.get(key, 0) + 1
    discrepancies = (Discrepancy.objects.current().filter(shift__starts_at__gte=start, shift__starts_at__lt=end)
                     .select_related("shift", "manager").order_by("shift__starts_at"))
    months = []
    month = start_day.replace(day=1)
    while month <= end_day:
        control = monthly_control(month.year, month.month)
        months.append({"month": month, "control": control, "met": control["control_value"] < BO01_MONTHLY_TARGET,
                       "accumulated": accumulated_report(month.year, month.month)})
        month = (month + timedelta(days=32)).replace(day=1)
    control = months[0]["control"]
    return {
        "requests_total": requests.count(), "by_reason": by_reason,
        "exceptions": [{"kind": k[0], "result": k[1], "value": k[2], "result_value": k[3], "n": n} for k, n in sorted(exc_rows.items())],
        "discrepancies": discrepancies, "accumulated": accumulated_report(start_day.year, start_day.month),
        "cases": LossCase.objects.filter(created_at__gte=start, created_at__lt=end)
        .prefetch_related("verifications", "recoveries"),
        "months": months, "control": control, "target": BO01_MONTHLY_TARGET, "met": control["control_value"] < BO01_MONTHLY_TARGET,
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
        # Làm bán thành phẩm: phần làm ra cộng vào nhập của bán thành phẩm, nguyên liệu gốc đem làm tính vào tiêu hao.
        made = period.filter(kind=StockMovement.Kind.PRODUCE, quantity__gt=0).aggregate(s=Sum("quantity"))["s"] or 0
        used = sums[StockMovement.Kind.PRODUCE] - made
        rows.append({
            # Tồn đầu kỳ khai báo lần đầu trong kỳ (lúc bắt đầu dùng hệ thống) cộng vào tồn đầu.
            "ingredient": ing, "opening": opening + sums[StockMovement.Kind.OPENING],
            "receipts": sums[StockMovement.Kind.RECEIPT] + made,
            "consumed": -sums[StockMovement.Kind.CONSUME] - used, "post_prep": post_prep.get(ing.pk, Decimal(0)),
            "waste": -sums[StockMovement.Kind.WASTE], "count_adjust": sums[StockMovement.Kind.COUNT],
            "closing": closing, "shortages": shortages.get(ing.pk, 0),
        })
    total_shortages = sum(shortages.values())
    from .material_forecasts import attach

    attach(rows, start_day, end_day)
    return {"rows": rows, "shortages": total_shortages, "bo02_target": BO02_MONTHLY_TARGET}



# ---------------- FR-50: bảng điều khiển ----------------

def shift_panel(user):
    """Phần ca của bảng điều khiển (Chủ quán trực tiếp quản lý ca): tình hình ca đang mở và việc của mình."""
    from apps.control.alerts import visible_to
    from apps.inventory.models import QuickReport
    from apps.orders.adjustments import pending_for
    from apps.orders.models import Order
    from apps.shifts.models import Shift
    from apps.shifts.services import figures
    from apps.staff.models import Attendance
    from apps.staff.timekeeping import WORK_ROLES
    from apps.accounts.models import Role

    shift = Shift.objects.operating()
    present = {Role(r).label: 0 for r in WORK_ROLES}
    for att in Attendance.objects.filter(clock_out__isnull=True):
        present[att.get_role_display()] = present.get(att.get_role_display(), 0) + 1
    return {
        "shift": shift, "figures": figures(shift) if shift else None,
        "open_orders": Order.objects.exclude(status__in=["da_thanh_toan", "da_huy"]).count(),
        "approvals": len(pending_for(user)),
        "my_alerts": visible_to(user).filter(status__in=["moi", "dang_xu_ly"]).count(),
        "quick_reports": QuickReport.objects.filter(acknowledged_at__isnull=True).count(),
        "present": present,
    }


def _stock_summary(today):
    """Ô kho trên bảng điều khiển: lô quá hạn, lô sắp hết hạn, hàng dự kiến bỏ, nguyên liệu dưới tồn an toàn."""
    from apps.inventory import lots
    from apps.inventory.models import Ingredient

    ingredients = list(Ingredient.objects.filter(is_active=True).select_related("stock"))
    view = lots.overview(ingredients, today)
    below = [i for i in ingredients if getattr(i, "stock", None) and i.safety_stock > 0
             and i.stock.available <= i.safety_stock]  # cùng điều kiện với trang Tồn kho
    return {"expired_lots": sum(len(d["expired"]) for d in view.values()),
            "expired_value": sum(d["expired_value"] for d in view.values()),
            "near_lots": sum(len(d["near"]) for d in view.values()),
            "at_risk_value": sum(d["at_risk_value"] for d in view.values()),
            "below": below, "value": sum(d["value"] for d in view.values())}


def _payments_stamp():
    """Dấu phiên bản của số liệu đã thu tiền: đổi khi có lần thu, hủy thanh toán, hoàn tiền hay sửa đơn đã thu."""
    from django.db.models import Count, Max

    from apps.orders.models import Order, Payment
    from apps.shifts.models import Refund

    parts = [Payment.objects.aggregate(n=Count("id"), at=Max("updated_at")),
             Refund.objects.aggregate(n=Count("id"), at=Max("updated_at")),
             Order.objects.filter(payment__isnull=False).aggregate(n=Count("id"), at=Max("updated_at"))]
    return "-".join(f"{p['n']}.{p['at'].timestamp() if p['at'] else 0}" for p in parts)


def _sales_block(first, end, today):
    """Doanh thu theo ngày và phân tích bán hàng của tháng: phần nặng nhất của bảng điều khiển.

    Kết quả giữ trong bộ nhớ đệm tới khi có lần thu tiền mới (hoặc 10 phút), nên mở lại bảng điều khiển hay đổi qua lại
    giữa các trang không phải tính lại toàn bộ dòng món của hai tháng.
    """
    from django.core.cache import cache

    key = f"bang-dieu-khien-thu-thuc-v2:{first}:{end}:{today}:{_payments_stamp()}"
    cached = cache.get(key)
    if cached is not None:
        return cached
    lines = paid_lines(first, end)
    by_day = revenue(first, end, "ngay", lines)
    found = {r["key"]: r for r in by_day["rows"]}
    days = []
    d = first
    while d <= end:
        r = found.get(f"{d:%d/%m/%Y}", {"revenue": 0, "orders": 0, "cups": 0})
        days.append({"day": d, "revenue": r["revenue"], "orders": r["orders"]})
        d += timedelta(days=1)
    from . import insights

    # So với cùng các ngày của tháng trước (1–26/10 so với 1–26/09), không phải kỳ liền trước cùng độ dài.
    prev_first = (first - timedelta(days=1)).replace(day=1)
    prev_end = min(prev_first + (end - first), first - timedelta(days=1))
    sales = insights.sales(first, end, prev=(prev_first, prev_end), today=today, lines=lines)
    result = (by_day, days, sales)
    try:
        cache.set(key, result, 600)
    except Exception:  # noqa: BLE001 - không lưu được bộ đệm thì vẫn trả số vừa tính
        pass
    return result


def dashboard(today=None, month=None):
    """Bảng điều khiển theo tháng (bộ lọc `month` = ngày bất kỳ trong tháng cần xem)."""
    from apps.control.models import Alert, ExceptionCase
    from apps.control.services import BO01_MONTHLY_TARGET, monthly_control
    from apps.core import params
    from apps.inventory.models import Ingredient, ShortageCase
    from apps.shifts.services import accumulated_report

    from . import charts

    today = today or timezone.localdate()
    month = month or today
    first, last = month_bounds(month)
    end = min(last, today) if first <= today else last
    control = monthly_control(month.year, month.month)
    shortages = ShortageCase.objects.filter(day__gte=first, day__lte=last).count()
    by_day, days, sales = _sales_block(first, end, today)
    revenue_chart = sales["trend_chart"]
    critical = []
    for ing in Ingredient.objects.filter(is_critical=True, is_active=True).select_related("stock"):
        stock = getattr(ing, "stock", None)
        available = stock.available if stock else Decimal(0)
        critical.append({"ingredient": ing, "physical": stock.physical if stock else Decimal(0), "available": available,
                         "below": available < ing.safety_stock})
    stock_chart = charts.hbars([{"label": c["ingredient"].name, "value": float(c["available"]),
                                 "marker": float(c["ingredient"].safety_stock), "below": c["below"],
                                 "text": f"{numbers.fmt(c['available'], 0)} {c['ingredient'].get_unit_display()}",
                                 "tip": f"{c['ingredient'].name}: có thể dùng {numbers.fmt(c['available'], 0)}, tồn an toàn "
                                        f"{numbers.fmt(c['ingredient'].safety_stock, 0)} {c['ingredient'].get_unit_display()}"}
                                for c in critical], "marker", label_w=130, width=charts.HALF)
    acc_rows = accumulated_report(month.year, month.month)
    limit = params.get("accumulated_manager_threshold")
    by_manager = {}
    for r in acc_rows:
        by_manager[r["manager"]] = by_manager.get(r["manager"], 0) + r["total"]
    acc_chart = charts.hbars([{"label": m, "value": v, "marker": limit, "below": v > limit,
                               "text": f"{numbers.fmt(v, 0)} đ",
                               "tip": f"{m}: thiếu chưa giải thích {numbers.fmt(v, 0)} đ, ngưỡng {numbers.fmt(limit, 0)} đ"}
                              for m, v in sorted(by_manager.items())], "marker", label_w=130, width=charts.HALF)
    bo01_chart = charts.stacked([("Tổn thất đã xác minh", control["verified"], 1),
                                 ("Thiếu tiền đang xử lý", control["in_process"], 2)], BO01_MONTHLY_TARGET)
    open_alerts = Alert.objects.filter(status__in=Alert.OPEN)
    from apps.inventory.models import QuickReport
    # Bảng 5.4: báo Sắp hết là thông tin, không chuyển cấp, hiển thị trên bảng điều khiển đến khi được xử lý.
    running_low = (QuickReport.objects.filter(level=QuickReport.Level.LOW, acknowledged_at__isnull=True)
                   .select_related("ingredient", "reporter").order_by("-created_at"))
    return {
        "running_low": running_low,
        "today": today, "month": first, "first": first, "end": end, "control": control,
        "bo01_target": BO01_MONTHLY_TARGET, "bo01_met": control["control_value"] < BO01_MONTHLY_TARGET,
        "bo01_chart": bo01_chart,
        "shortages": shortages, "bo02_target": BO02_MONTHLY_TARGET, "bo02_met": shortages <= BO02_MONTHLY_TARGET,
        "by_day": by_day, "days": days, "revenue_chart": revenue_chart, "sales": sales,
        "stock_summary": _stock_summary(today),
        "accumulated": sum(r["total"] for r in acc_rows), "acc_chart": acc_chart, "acc_limit": limit,
        "critical": critical, "stock_chart": stock_chart,
        "alerts": {"khan": open_alerts.filter(severity="khan").count(),
                   "quan_trong": open_alerts.filter(severity="quan_trong").count(),
                   "overdue": open_alerts.filter(due_at__lt=timezone.now()).count()},
        "exceptions": [(value, label, ExceptionCase.objects.filter(status=ExceptionCase.Status.OPEN, severity=value).count())
                       for value, label in ExceptionCase.Severity.choices],
    }
