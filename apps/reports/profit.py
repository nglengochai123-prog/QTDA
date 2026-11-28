"""Lãi lỗ theo tháng (Hai, 28/11/2026): lợi nhuận = doanh thu thuần − chi phí, không đặt tỷ lệ cố định.

Nguồn từng khoản, đều lấy từ dữ liệu nghiệp vụ đã có:
- Doanh thu thuần: tiền thu trừ tiền hoàn đã trả trong tháng (giống báo cáo Doanh thu).
- Giá vốn nguyên liệu: nguyên liệu trừ kho khi pha chế và nguyên liệu gốc đem làm bán thành phẩm, tính theo đơn giá
  nhập gần nhất tới ngày dùng (giống báo cáo Kho).
- Hao hụt: hàng bỏ đi ghi ở Hao hụt (hỏng, quá hạn, đổ vỡ), cùng cách tính giá.
- Chênh lệch kiểm kê: thiếu khi kiểm kê là chi phí, thừa thì giảm chi phí.
- Lương theo giờ công: giờ chấm công hợp lệ (có giờ ra) × lương giờ trong hồ sơ nhân viên, theo ngày vào ca.
- Chi từ quỹ ca: các khoản chi tiền mặt trong két theo danh mục (nguyên vật liệu đã nằm ở giá vốn nên không có ở đây).
- Chi phí tháng: Chủ quán nhập (mặt bằng, điện nước...), không qua két.
Tiền trả nhà cung cấp không tính riêng: hàng nhập về chỉ thành chi phí khi được dùng (giá vốn) hoặc bỏ đi (hao hụt).
"""

from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone

from .services import month_bounds, period_bounds


def _stock_costs(start, end):
    from apps.inventory.models import StockMovement

    from .inventory import Prices

    prices = Prices()
    out = defaultdict(float)
    for ing, kind, at, q in (StockMovement.objects.filter(created_at__gte=start, created_at__lt=end)
                             .exclude(kind__in=[StockMovement.Kind.RECEIPT, StockMovement.Kind.OPENING])
                             .values_list("ingredient_id", "kind", "created_at", "quantity")):
        value = -float(q) * float(prices.at(ing, timezone.localdate(at)))
        if kind == StockMovement.Kind.CONSUME:
            out["cogs"] += value
        elif kind == StockMovement.Kind.PRODUCE and q < 0:
            out["cogs"] += value  # nguyên liệu gốc làm bán thành phẩm; bán thành phẩm không có giá nhập
        elif kind == StockMovement.Kind.WASTE:
            out["waste"] += value
        elif kind == StockMovement.Kind.COUNT:
            out["count"] += value
    return out


def _payroll(start, end):
    from apps.staff.models import Attendance
    from apps.staff.timekeeping import valid_hours

    total, hours, missing = Decimal(0), Decimal(0), set()
    for att in (Attendance.objects.filter(clock_in__gte=start, clock_in__lt=end)
                .select_related("user__employee")):
        h = valid_hours(att)
        employee = getattr(att.user, "employee", None)
        wage = employee.hourly_wage if employee is not None else 0
        if h and not wage:
            missing.add(str(att.user))
        hours += h
        total += h * wage
    return {"amount": int(round(total)), "hours": hours, "no_wage": sorted(missing)}


def _cash_expenses(start, end):
    from apps.shifts.models import CashEntry, ExpenseCategory

    labels = dict(ExpenseCategory.choices)
    rows = (CashEntry.objects.filter(kind=CashEntry.Kind.EXPENSE, created_at__gte=start, created_at__lt=end)
            .values("category").annotate(s=Sum("amount")).order_by("category"))
    return [{"label": f"Chi quỹ ca: {labels.get(r['category'], 'Khác').lower()}", "amount": int(r["s"])} for r in rows]


def month(first_day, today=None):
    """Bảng lãi lỗ của tháng bắt đầu `first_day`; tháng đang chạy tính tới hết hôm nay."""
    from .models import MonthlyExpense
    from .services import revenue

    today = today or timezone.localdate()
    first, last = month_bounds(first_day)
    upto = min(last, today)
    if first > today:
        upto = first - timedelta(days=1)  # tháng chưa tới: không có số liệu
    start, end = period_bounds(first, upto)
    rev = revenue(first, upto) if upto >= first else {"total": 0, "refunds": 0, "net": 0}
    stock = _stock_costs(start, end)
    pay = _payroll(start, end)
    fixed = list(MonthlyExpense.objects.filter(month=first).select_related("created_by"))
    by_cat = defaultdict(int)
    for e in fixed:
        by_cat[e.get_category_display()] += e.amount
    costs = [
        {"group": "Nguyên liệu", "label": "Giá vốn nguyên liệu đã dùng", "amount": round(stock["cogs"])},
        {"group": "Nguyên liệu", "label": "Hao hụt (hỏng, quá hạn, đổ vỡ)", "amount": round(stock["waste"])},
        {"group": "Nguyên liệu", "label": "Chênh lệch kiểm kê (thiếu là dương)", "amount": round(stock["count"])},
        {"group": "Nhân công", "label": f"Lương theo giờ công ({pay['hours']:.1f} giờ)".replace(".", ","),
         "amount": pay["amount"]},
    ]
    costs += [{"group": "Chi từ quỹ ca", **r} for r in _cash_expenses(start, end)]
    costs += [{"group": "Chi phí tháng", "label": k, "amount": v} for k, v in sorted(by_cat.items())]
    costs = [c for c in costs if c["amount"] or c["group"] in ("Nguyên liệu", "Nhân công")]
    total_cost = sum(c["amount"] for c in costs)
    net = rev["net"]
    gross = net - round(stock["cogs"])
    profit = net - total_cost
    for c in costs:
        c["pct"] = c["amount"] / net * 100 if net else None
    return {
        "first": first, "last": last, "upto": upto, "running": first <= today <= last,
        "receipts": rev["total"], "refunds": rev["refunds"], "net": net, "costs": costs, "total_cost": total_cost,
        "gross": gross, "gross_pct": gross / net * 100 if net else None,
        "profit": profit, "profit_pct": profit / net * 100 if net else None,
        "fixed": fixed, "fixed_total": sum(e.amount for e in fixed), "no_wage": pay["no_wage"],
    }
