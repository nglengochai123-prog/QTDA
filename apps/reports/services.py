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
BO03_TARGET_PERCENT = 90  # BO-03: 90% đến 95% khung giờ đáp ứng (PRODUCT.md)


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


def _net_total(start, end):
    """Doanh thu thuần trong kỳ: tiền đã thu trừ hoàn tiền đã trả, cùng cách tính với `revenue()["net"]`."""
    from apps.shifts.models import Refund

    paid_back = Refund.objects.filter(status=Refund.Status.PAID, paid_at__gte=start, paid_at__lt=end).aggregate(
        s=Sum("amount"))["s"] or 0
    return _paid_total(start, end) - paid_back


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
    """Doanh thu theo chiều `dim`: tiền thu và tiền hoàn thực tế trong kỳ, phân bổ món theo sổ phân bổ (receipts).

    Mọi chiều xem cộng lại đều ra đúng tiền thu trừ hoàn: hoàn tiền trừ vào đúng món, nhóm, nhân viên đã nhận tiền."""
    from . import receipts

    start, end = period_bounds(start_day, end_day)
    items = receipts.entries(start, end)
    rows = receipts.grouped(items, dim)
    total = sum(e["amount"] for e in items if e["kind"] != receipts.HOAN)
    refunds = -sum(e["amount"] for e in items if e["kind"] == receipts.HOAN)
    orders = {oid for e in items if receipts.counts_order(e) for oid in e["order_ids"]}
    legacy = sum(abs(e["amount"]) for e in items if e["legacy"])
    result = sorted(rows, key=lambda r: r["sort"])
    for row in result:
        row.pop("sort")
        row["orders"] = len(row["orders"])
        filters = row.pop("filters")
        # Một dòng gộp từ nhiều giá trị lọc (ví dụ món đổi tên) thì không gắn liên kết để tránh lệch số đơn.
        row["link"] = revenue_link(start_day, end_day, next(iter(filters))) if len(filters) == 1 else ""
        row["net"] = row["revenue"] - row["refunds"]
    length = (end_day - start_day).days + 1
    previous_period = (start_day - timedelta(days=length), start_day - timedelta(days=1))
    return {"rows": result, "total": total, "orders": len(orders), "refunds": refunds, "net": total - refunds,
            "cups": sum(r["cups"] for r in result), "previous": _net_total(*period_bounds(*previous_period)),
            "previous_period": previous_period, "dim": dim, "dim_label": DIMENSIONS[dim],
            "money_dimension": True, "legacy_amount": legacy}


def revenue_xlsx(start_day, end_day):
    from apps.core import xlsx

    sheets, lines = [], paid_lines(start_day, end_day)
    for dim, label in DIMENSIONS.items():
        data = revenue(start_day, end_day, dim, lines)
        rows = [[label, "Số đơn có khoản thu", "Số ly ghi lúc thu đầu", "Tiền đã thu (đồng)", "Tiền đã hoàn", "Thu trừ hoàn"]]
        rows += [[r["key"], r["orders"], r["cups"], r["revenue"], r["refunds"], r["net"]] for r in data["rows"]]
        rows += [["Tổng", data["orders"], data["cups"], data["total"]], ["Hoàn tiền đã trả trong kỳ", "", "", data["refunds"]],
                 ["Doanh thu thuần", "", "", data["net"]]]
        rows.append(["Hoàn tiền trừ vào đúng món đã nhận tiền; đổi món chuyển tiền sang món mới tại lúc duyệt. "
                     "Dữ liệu cũ chưa có phân bổ: " + str(data["legacy_amount"]) + " đồng."])
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
    from apps.staff.timekeeping import WORK_ROLES, on_duty
    from apps.accounts.models import Role

    shift = overrun = Shift.objects.operating()
    # Ca quỹ tạo sẵn khi công bố lịch: chưa xác nhận tiền đầu ca và chưa có đơn thì chưa mở, không có ai "đang làm".
    if shift is not None and not shift.started:
        shift = None
    present = {Role(r).label: 0 for r in WORK_ROLES}
    if shift is not None:
        for att in on_duty():
            present[att.get_role_display()] = present.get(att.get_role_display(), 0) + 1
    fig = figures(shift) if shift else None
    return {
        "staffing": staffing_now(present) if shift else [], "today": today_vs_last_week(),
        "shift": shift, "figures": fig, "overrun_shift": overrun,
        "cash_out": fig["refunds_cash"] + fig["expenses"] + fig["handovers"] if fig else 0,
        "open_orders": Order.objects.exclude(status__in=["da_thanh_toan", "da_huy"]).count(),
        "approvals": len(pending_for(user)),
        # Ngoại lệ có dòng riêng ở Kiểm soát; không đếm chung để khớp số trên chuông.
        "my_alerts": visible_to(user).filter(status__in=["moi", "dang_xu_ly"]).exclude(kind="ngoai_le").count(),
        "quick_reports": QuickReport.objects.filter(acknowledged_at__isnull=True).count(),
        "present": present, "today_date": timezone.localdate(),
    }


def today_vs_last_week(now=None):
    """Doanh thu thuần hôm nay tới giờ, so với cùng thứ tuần trước tính tới cùng giờ."""
    from . import receipts

    now = timezone.localtime(now or timezone.now())
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    def net(lo, hi):
        return sum(e["amount"] for e in receipts.entries(lo, hi))

    cur, old = net(start, now), net(start - timedelta(days=7), now - timedelta(days=7))
    weekday = ["thứ Hai", "thứ Ba", "thứ Tư", "thứ Năm", "thứ Sáu", "thứ Bảy", "Chủ nhật"][now.weekday()]
    return {"net": cur, "last_week": old, "weekday": weekday,
            "delta": round((cur - old) / old * 100) if old else None}


def staffing_now(present, now=None):
    """Người có mặt so với số người cần của các ca trong lịch đang diễn ra (cộng các ca chồng giờ)."""
    from apps.accounts.models import Role
    from apps.schedule.models import RoleNeed
    from apps.schedule.services import ROLES

    now = timezone.localtime(now or timezone.now())
    needs = {r: 0 for r in ROLES}
    found = False
    for need in RoleNeed.objects.filter(shift__date=now.date()).select_related("shift"):
        a, b = need.shift._minutes()
        if a <= now.hour * 60 + now.minute < b:
            needs[need.role] = needs.get(need.role, 0) + need.needed
            found = True
    if not found:
        return []
    rows = []
    for r in ROLES:
        label = Role(r).label
        have = present.get(label, 0)
        rows.append({"label": label, "present": have, "needed": needs[r], "short": have < needs[r],
                     "gap": max(needs[r] - have, 0)})
    return rows


def service_level(first, end, today=None):
    """BO-03: tỷ lệ khung giờ mở cửa đạt chuẩn phục vụ (không quá tải: chờ món trung vị trong chuẩn, quầy không dồn
    quá giới hạn) từ ngày `first` tới `end`. Ngày đã qua giữ trong bộ nhớ đệm 6 giờ; hôm nay 2 phút."""
    from django.core.cache import cache

    from apps.orders.workload import day_frames

    today = today or timezone.localdate()
    total = ok = 0
    worst = []
    d = first
    while d <= min(end, today):
        key = f"bo03:{d}:{_payments_stamp() if d == today else ''}"
        day = cache.get(key)
        if day is None:
            frames = day_frames(d)["frames"]
            day = [(f["label"], f["overloaded"]) for f in frames if f["cups"] or f["backlog"]]
            try:
                cache.set(key, day, 120 if d == today else 6 * 3600)
            except Exception:  # noqa: BLE001
                pass
        total += len(day)
        ok += sum(1 for _label, over in day if not over)
        bad = sum(1 for _label, over in day if over)
        if bad:
            worst.append((d, bad))
        d += timedelta(days=1)
    worst.sort(key=lambda x: (-x[1], x[0]))
    return {"frames": total, "ok": ok, "percent": round(100 * ok / total) if total else None,
            "worst": worst[:3], "target": BO03_TARGET_PERCENT}


def goals(control, shortages, service, open_reports):
    """Ba mục tiêu của dự án (PRODUCT.md): thất thoát, thiếu nguyên liệu, khung giờ đạt chuẩn phục vụ."""
    from apps.control.services import BO01_MONTHLY_TARGET

    loss = control["control_value"]
    pct = service["percent"]
    loss_note = f"Đã xác minh {numbers.fmt(control['verified'], 0)} đ · đang xử lý {numbers.fmt(control['in_process'], 0)} đ"
    if control.get("open_cases"):
        loss_note += f" · {control['open_cases']} vụ chưa kết luận"
    if open_reports:
        names = ", ".join(f"{r.ingredient.name} ({r.get_level_display().lower()})" for r in open_reports[:3])
        stock_note = f"Đang báo: {names}" + ("…" if len(open_reports) > 3 else "")
    else:
        stock_note = "Không có nguyên liệu đang báo thiếu"
    if service["frames"]:
        service_note = f"{service['ok']}/{service['frames']} khung giờ đạt chuẩn"
        if service["worst"]:
            service_note += " · quá tải nhiều nhất " + ", ".join(f"{d:%d/%m} ({n} khung)" for d, n in service["worst"])
    else:
        service_note = "Chưa có khung giờ nào có khách"
    return [
        {"key": "bo01", "label": "Thất thoát doanh thu", "value": f"{numbers.fmt(loss, 0)} đ",
         "target": f"dưới {numbers.fmt(BO01_MONTHLY_TARGET, 0)} đ", "met": loss < BO01_MONTHLY_TARGET,
         "fill": min(100, round(100 * loss / BO01_MONTHLY_TARGET)) if BO01_MONTHLY_TARGET else 0, "tick": None,
         "note": loss_note, "url": "reports:revenue_control"},
        {"key": "bo02", "label": "Thiếu nguyên liệu", "value": f"{shortages} lần",
         "target": f"không quá {BO02_MONTHLY_TARGET} lần", "met": shortages <= BO02_MONTHLY_TARGET,
         "fill": min(100, round(100 * shortages / max(BO02_MONTHLY_TARGET, 1))), "tick": None,
         "note": stock_note, "url": "inventory:report"},
        {"key": "bo03", "label": "Khung giờ đạt chuẩn phục vụ", "value": f"{pct}%" if pct is not None else "–",
         "target": f"từ {service['target']}%", "met": pct is not None and pct >= service["target"],
         "fill": pct or 0, "tick": service["target"], "note": service_note, "url": "staff:workload"},
    ]


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

    # Kỳ đang diễn ra so với cùng giờ kỳ trước: khóa đổi theo từng 10 phút để phần so sánh không đứng yên cả buổi.
    slot = timezone.localtime().strftime("%H%M")[:3] if end == today else ""
    key = f"bang-dieu-khien-v3:{first}:{end}:{today}:{slot}:{_payments_stamp()}"
    cached = cache.get(key)
    if cached is not None:
        return cached
    lines = paid_lines(first, end)
    by_day = revenue(first, end, "ngay", lines)
    found = {r["key"]: r for r in by_day["rows"]}
    days = []
    d = first
    while d <= end:
        r = found.get(f"{d:%d/%m/%Y}", {"revenue": 0, "refunds": 0, "net": 0, "orders": 0, "cups": 0})
        days.append({"day": d, "receipts": r["revenue"], "refunds": r["refunds"], "revenue": r["net"],
                     "orders": r["orders"]})
        d += timedelta(days=1)
    from . import insights

    # So với cùng các ngày của tháng trước (1–26/10 so với 1–26/09), không phải kỳ liền trước cùng độ dài.
    prev_first = (first - timedelta(days=1)).replace(day=1)
    prev_end = min(prev_first + (end - first), first - timedelta(days=1))
    sales = insights.sales(first, end, prev=(prev_first, prev_end), today=today, lines=lines, rolling_heat=True)
    result = (by_day, days, sales)
    try:
        cache.set(key, result, 600)
    except Exception:  # noqa: BLE001 - không lưu được bộ đệm thì vẫn trả số vừa tính
        pass
    return result


COVER_CAP_DAYS = 30  # thanh dài nhất của biểu đồ số ngày còn dùng; số trên nhãn vẫn là số thật


def _critical_stock(today):
    """Nguyên liệu trọng yếu quy ra số ngày còn dùng được theo tốc độ dùng 4 tuần gần nhất.

    Mỗi nguyên liệu một đơn vị (gram, ml, cái) nên không đặt chung một trục số lượng: 162 gram matcha nằm sát 0 cạnh
    11.070 gram cà phê dù matcha mới là thứ sắp hết. Quy ra ngày thì mọi dòng cùng thang và trả lời đúng câu Chủ quán
    cần: còn đủ dùng mấy ngày, đã chạm mức tồn an toàn chưa."""
    from apps.inventory import lots
    from apps.inventory.lots import daily_usage
    from apps.inventory.models import Ingredient

    from . import charts

    ingredients = list(Ingredient.objects.filter(is_critical=True, is_active=True).select_related("stock"))
    usage = daily_usage([i.pk for i in ingredients], today)
    # Lô quá hạn phải để riêng và hủy: không tính vào số ngày còn đủ dùng, cùng cách với trang Tồn kho.
    expired = {pk: v["expired_qty"] for pk, v in lots.overview(ingredients, today).items()} if ingredients else {}
    critical, rows = [], []
    for ing in ingredients:
        stock = getattr(ing, "stock", None)
        available = stock.available if stock else Decimal(0)
        per_day = usage.get(ing.pk) or 0
        out_of_date = expired.get(ing.pk, 0)
        days = max(float(available) - out_of_date, 0) / per_day if per_day > 0 else None
        unit = ing.get_unit_display()
        c = {"ingredient": ing, "physical": stock.physical if stock else Decimal(0), "available": available,
             # cùng điều kiện với ô Dưới tồn an toàn và trang Tồn kho
             "below": ing.safety_stock > 0 and available <= ing.safety_stock, "per_day": per_day, "days": days,
             "unit": unit}
        critical.append(c)
        if days is None:
            continue
        safety_days = float(ing.safety_stock) / per_day
        rows.append({"label": ing.name, "value": min(max(days, 0), COVER_CAP_DAYS),
                     "marker": min(safety_days, COVER_CAP_DAYS) or None, "below": c["below"],
                     "status": "warn" if c["below"] or days <= 0 else None,  # 0 ngày: chỉ còn lô quá hạn hoặc hết
                     "text": f"{numbers.fmt(max(days, 0), 1)} ngày",
                     "tip": f"{ing.name}: có thể dùng {numbers.fmt(available, 0)} {unit}"
                            + (f" (không tính {numbers.fmt(out_of_date, 0)} {unit} ở lô quá hạn)" if out_of_date else "")
                            + f", dùng bình quân "
                            f"{numbers.fmt(per_day, 0)} {unit}/ngày, đủ khoảng {numbers.fmt(max(days, 0), 1)} ngày; tồn an "
                            f"toàn {numbers.fmt(ing.safety_stock, 0)} {unit} (khoảng {numbers.fmt(safety_days, 1)} ngày)"})
    rows.sort(key=lambda r: r["value"])
    return critical, charts.hbars(rows, "marker", label_w=130, width=charts.HALF)


def dashboard(today=None, month=None):
    """Bảng điều khiển theo tháng (bộ lọc `month` = ngày bất kỳ trong tháng cần xem)."""
    from apps.control.models import Alert, ExceptionCase
    from apps.control.services import BO01_MONTHLY_TARGET, monthly_control
    from apps.core import params
    from apps.inventory.models import ShortageCase
    from apps.shifts.services import accumulated_report

    from . import charts

    today = today or timezone.localdate()
    month = month or today
    first, last = month_bounds(month)
    end = min(last, today) if first <= today else last
    control = monthly_control(month.year, month.month)
    shortages = ShortageCase.objects.filter(day__gte=first, day__lte=last).count()
    by_day, days, sales = _sales_block(first, end, today)
    revenue_chart = sales["trend_plain"]
    critical, stock_chart = _critical_stock(today)
    acc_rows = accumulated_report(month.year, month.month)
    limit = params.get("accumulated_manager_threshold")
    by_manager = {}
    for r in acc_rows:
        by_manager[r["manager"]] = by_manager.get(r["manager"], 0) + r["total"]
    acc_chart = charts.hbars([{"label": m, "value": v, "marker": limit, "below": v > limit,
                               "text": f"{numbers.fmt(v, 0)} đ",
                               "tip": f"{m}: thiếu chưa được chấp nhận {numbers.fmt(v, 0)} đ, ngưỡng {numbers.fmt(limit, 0)} đ"}
                              for m, v in sorted(by_manager.items())], "marker", label_w=130, width=charts.HALF)
    bo01_chart = charts.stacked([("Tổn thất đã xác minh", control["verified"], 1),
                                 ("Thiếu tiền đang xử lý", control["in_process"], 2)], BO01_MONTHLY_TARGET)
    open_alerts = Alert.objects.filter(status__in=Alert.OPEN)
    # Bảng 5.4: báo Sắp hết là thông tin, không chuyển cấp, hiển thị trên bảng điều khiển đến khi được xử lý.
    from apps.inventory.operations import open_reports_board

    open_reports = open_reports_board()
    service = service_level(first, end, today) if first <= today else {"frames": 0, "ok": 0, "percent": None,
                                                                        "worst": [], "target": BO03_TARGET_PERCENT}
    return {
        "running_low": open_reports, "goals": goals(control, shortages, service, open_reports),
        "today": today, "month": first, "first": first, "end": end, "control": control,
        "bo01_target": BO01_MONTHLY_TARGET, "bo01_met": control["control_value"] < BO01_MONTHLY_TARGET,
        "bo01_chart": bo01_chart,
        "shortages": shortages, "bo02_target": BO02_MONTHLY_TARGET, "bo02_met": shortages <= BO02_MONTHLY_TARGET,
        "by_day": by_day, "days": days, "revenue_chart": revenue_chart, "sales": sales,
        "stock_summary": _stock_summary(today),
        "accumulated": sum(r["total"] for r in acc_rows), "acc_chart": acc_chart, "acc_limit": limit,
        "accumulated_over": sorted(((m, v) for m, v in by_manager.items() if v > limit), key=lambda x: -x[1]),
        "critical": critical, "stock_chart": stock_chart,
        "alerts": {"khan": open_alerts.filter(severity="khan").count(),
                   "quan_trong": open_alerts.filter(severity="quan_trong").count(),
                   "overdue": open_alerts.filter(due_at__lt=timezone.now()).count()},
        "exceptions": [(value, label, ExceptionCase.objects.filter(status=ExceptionCase.Status.OPEN, severity=value).count())
                       for value, label in ExceptionCase.Severity.choices],
    }


# ---------------- Việc Chủ quán cần chú ý (bảng điều khiển) ----------------

LEVELS = {"khan": (0, "Khẩn"), "chu_y": (1, "Cần chú ý"), "theo_doi": (2, "Theo dõi")}


def attention(dash, now=None):
    """Danh sách việc Chủ quán cần chú ý, gom từ các số bảng điều khiển đã tính (`dash` = kết quả dashboard()) và
    từ chính các màn nghiệp vụ, không tạo cảnh báo mới. Chỉ có mục khi thực sự có việc; mỗi mục dẫn tới màn xử lý.

    Mức: khẩn (quá hạn, khẩn, nguyên liệu đã hết), cần chú ý (việc chờ quyết định, vượt mục tiêu), theo dõi (chưa đạt
    mục tiêu nhưng chưa phải xử lý ngay). Cảnh báo loại Ngoại lệ không đếm thêm vì ngoại lệ có mục riêng."""
    from django.db.models import Min, Sum
    from django.urls import reverse

    from apps.control.models import Alert, ExceptionCase
    from apps.core import params
    from apps.core.notifications import forecast_stale
    from apps.shifts.models import Discrepancy

    now = now or timezone.now()
    items = []

    def add(level, title, value, url, when=None, note=""):
        items.append({"level": level, "level_label": LEVELS[level][1], "title": title, "value": value, "url": url,
                      "when": when, "note": note})

    alerts = Alert.objects.filter(status__in=Alert.OPEN).exclude(kind=Alert.Kind.EXCEPTION)
    overdue = alerts.filter(due_at__lt=now)
    if overdue.exists():
        add("khan", "Cảnh báo đã quá hạn xử lý", overdue.count(), reverse("control:alerts"),
            when=overdue.aggregate(t=Min("created_at"))["t"], note="mở từ")
    urgent = alerts.filter(severity=Alert.Severity.URGENT, due_at__gte=now)
    if urgent.exists():
        add("khan", "Cảnh báo khẩn đang chờ xử lý", urgent.count(), reverse("control:alerts"))
    important = alerts.filter(severity=Alert.Severity.IMPORTANT, due_at__gte=now)
    if important.exists():
        add("chu_y", "Cảnh báo quan trọng đang chờ xử lý", important.count(), reverse("control:alerts"))
    open_exc = ExceptionCase.objects.filter(status=ExceptionCase.Status.OPEN)
    for value, label in ExceptionCase.Severity.choices:
        rows = open_exc.filter(severity=value)
        if rows.exists():
            add("khan" if value == ExceptionCase.Severity.URGENT else "chu_y", f"Ngoại lệ {label.lower()} chưa xem xét",
                rows.count(), f"{reverse('control:exceptions')}?muc={value}",
                when=rows.aggregate(t=Min("created_at"))["t"], note="cũ nhất từ")
    pending = Discrepancy.objects.current().filter(decision="")
    if pending.exists():
        total = pending.aggregate(s=Sum("difference"))["s"] or 0
        add("chu_y", "Chênh lệch tiền ca chờ bạn quyết định", f"{pending.count()} khoản · {numbers.fmt(abs(total), 0)} đ",
            reverse("shifts:status"), when=pending.aggregate(t=Min("created_at"))["t"], note="cũ nhất từ")
    if dash.get("accumulated_over"):
        for manager, total in dash["accumulated_over"]:
            add("chu_y", f"Thiếu tiền tích lũy của {manager} vượt ngưỡng", f"{numbers.fmt(total, 0)} đ",
                reverse("shifts:status"), note=f"ngưỡng {numbers.fmt(params.get('accumulated_manager_threshold'), 0)} đ")
    out = [r for r in dash.get("running_low", []) if r.level == "da_het"]
    low = [r for r in dash.get("running_low", []) if r.level != "da_het"]
    if out:
        add("khan", "Nguyên liệu đã hết", ", ".join(r.ingredient.name for r in out[:3]) + ("…" if len(out) > 3 else ""),
            reverse("inventory:stock"), when=min(r.created_at for r in out), note="báo lúc")
    if low:
        add("chu_y", "Nguyên liệu nhân viên báo sắp hết", ", ".join(r.ingredient.name for r in low[:3])
            + ("…" if len(low) > 3 else ""), reverse("inventory:stock"))
    stale = forecast_stale(now)
    if stale:
        add("chu_y", "Dự báo và kế hoạch mua đã cũ", "", reverse("forecast:plans"), note=stale.split(": ")[0])
    # Mục tiêu tháng chỉ hiện khi chưa đạt (Hai, 21/11/2026: mục tiêu không đưa lên thành thẻ riêng).
    for g in dash.get("goals", []):
        if g["met"] or g["value"] == "–":
            continue
        level = "chu_y" if g["key"] in ("bo01", "bo02") else "theo_doi"
        add(level, f"{g['label']}: chưa đạt mục tiêu tháng", g["value"], reverse(g["url"]), note=g["target"])
    items.sort(key=lambda i: LEVELS[i["level"]][0])
    return items
