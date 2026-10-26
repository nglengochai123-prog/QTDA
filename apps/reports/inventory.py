"""Báo cáo kho: giá trị tồn, dòng chảy nhập và xuất, hao hụt, hạn dùng của lô, độ phủ so với thời gian giao hàng.

Định giá: tồn hiện tại theo giá thực tế đích danh của từng lô (inventory.lots). Chuỗi theo ngày trong quá khứ tính
bằng tồn vật lý của ngày đó nhân đơn giá nhập gần nhất tính tới ngày đó, vì lô chỉ được theo dõi từ khi có tính năng
lô; hai cách chênh nhau phần giá giữa các lô còn lại.
"""

import bisect
from collections import defaultdict
from datetime import timedelta

from django.db.models import Sum
from django.db.models.functions import TruncDate
from django.utils import timezone

from . import charts
from .services import period_bounds

WEEKS_AHEAD = 8
AGE_BUCKETS = [(0, 3, "0–3"), (4, 7, "4–7"), (8, 14, "8–14"), (15, 30, "15–30"), (31, 60, "31–60"),
               (61, 90, "61–90"), (91, 10**6, "trên 90")]


class Prices:
    """Đơn giá nhập gần nhất tính tới một ngày, theo nguyên liệu."""

    def __init__(self):
        from apps.inventory.models import ReceiptLine

        self.by_ing = defaultdict(lambda: ([], []))
        for ing, at, price in (ReceiptLine.objects.order_by("receipt__created_at", "pk")
                               .values_list("ingredient_id", "receipt__created_at", "unit_price")):
            days, prices = self.by_ing[ing]
            days.append(timezone.localdate(at))
            prices.append(price)

    def at(self, ing, day):
        days, prices = self.by_ing.get(ing, ([], []))
        if not days:
            return 0
        i = bisect.bisect_right(days, day) - 1
        return prices[max(i, 0)]


def _money(v):
    return f"{int(round(v)):,} đ".replace(",", ".")


def dashboard(start_day, end_day, today=None):
    from apps.inventory import lots
    from apps.inventory.models import Ingredient, ReceiptLine, StockMovement, Waste

    today = today or timezone.localdate()
    end_day = min(end_day, today)
    start, end = period_bounds(start_day, end_day)
    prices = Prices()
    ingredients = list(Ingredient.objects.filter(is_active=True).select_related("stock", "main_supplier"))
    names = {i.pk: i for i in ingredients}
    days = [start_day + timedelta(days=k) for k in range((end_day - start_day).days + 1)]

    # Biến động gộp theo nguyên liệu, ngày, loại
    opening = defaultdict(float)
    for ing, q in (StockMovement.objects.filter(created_at__lt=start).values_list("ingredient_id")
                   .annotate(s=Sum("quantity"))):
        opening[ing] = float(q)
    daily = defaultdict(lambda: defaultdict(float))  # (ing) -> day -> delta
    flow = defaultdict(lambda: defaultdict(float))   # kind -> day -> value (đồng)
    used_qty = defaultdict(float)
    for row in (StockMovement.objects.filter(created_at__gte=start, created_at__lt=end)
                .annotate(day=TruncDate("created_at", tzinfo=timezone.get_current_timezone()))
                .values("ingredient_id", "day", "kind").annotate(q=Sum("quantity"))):
        ing, day, kind, q = row["ingredient_id"], row["day"], row["kind"], float(row["q"])
        daily[ing][day] += q
        if kind in (StockMovement.Kind.CONSUME, StockMovement.Kind.WASTE):
            flow[kind][day] += -q * prices.at(ing, day)
        if kind == StockMovement.Kind.CONSUME:
            used_qty[ing] += -q

    # Giá trị tồn theo ngày
    value_series = []
    balance = dict(opening)
    for d in days:
        total = 0.0
        for ing in set(balance) | set(daily):
            balance[ing] = balance.get(ing, 0.0) + daily.get(ing, {}).get(d, 0.0)
            if balance[ing] > 0:
                total += balance[ing] * prices.at(ing, d)
        value_series.append(total)

    receipts = (ReceiptLine.objects.filter(receipt__created_at__gte=start, receipt__created_at__lt=end)
                .select_related("receipt__supplier"))
    receipt_value = sum(l.value for l in receipts)
    by_supplier = defaultdict(int)
    for l in receipts:
        by_supplier[l.receipt.supplier.name] += l.value
    consume_value = sum(flow[StockMovement.Kind.CONSUME].values())
    waste_value = sum(flow[StockMovement.Kind.WASTE].values())

    # Lô hiện tại: giá trị theo lô, hạn dùng, độ phủ
    view = lots.overview(ingredients, today)
    stock_value = sum(d["value"] for d in view.values())
    n_days = max(len(days), 1)
    avg_value = sum(value_series) / len(value_series) if value_series else 0
    dio = avg_value / (consume_value / n_days) if consume_value else None

    # Cột chồng theo tuần: tiêu hao và hao hụt (giá trị)
    weeks = []
    d = start_day - timedelta(days=start_day.weekday())
    while d <= end_day:
        weeks.append(d)
        d += timedelta(days=7)
    def week_sum(kind, w):
        return sum(v for day, v in flow[kind].items() if w <= day < w + timedelta(days=7))
    flow_chart = charts.stacked_columns(
        [f"{w:%d/%m}" for w in weeks],
        [{"name": "Tiêu hao theo món", "values": [week_sum(StockMovement.Kind.CONSUME, w) for w in weeks], "slot": 1},
         {"name": "Hao hụt", "values": [week_sum(StockMovement.Kind.WASTE, w) for w in weeks], "slot": 2}],
        width=charts.HALF, tips=[f"Tuần từ {w:%d/%m}: tiêu hao {_money(week_sum(StockMovement.Kind.CONSUME, w))} · hao hụt "
              f"{_money(week_sum(StockMovement.Kind.WASTE, w))}" for w in weeks])

    value_chart = charts.line([f"{d:%d/%m}" for d in days],
                              [{"name": "Giá trị tồn", "values": value_series, "slot": 1, "area": True}],
                              tip_labels=[f"{d:%d/%m/%Y}" for d in days], width=charts.HALF)

    # Hao hụt theo lý do (giá trị) và theo nguyên liệu
    reason_labels = dict(Waste.Reason.choices)
    by_reason, by_ing_waste, by_ing_reason = defaultdict(float), defaultdict(float), defaultdict(float)
    for w in Waste.objects.filter(created_at__gte=start, created_at__lt=end):
        v = float(w.quantity) * prices.at(w.ingredient_id, timezone.localdate(w.created_at))
        by_reason[w.reason] += v
        by_ing_waste[w.ingredient_id] += v
        by_ing_reason[(w.ingredient_id, w.reason)] += v
    slots = {Waste.Reason.EXPIRED: 2, Waste.Reason.DAMAGED: 1, Waste.Reason.BROKEN: 3}
    reason_chart = charts.share_bar(
        [(reason_labels[k], v, slots.get(k, "muted")) for k, v in sorted(by_reason.items(), key=lambda x: -x[1])],
        value_fmt=lambda v: _money(v))
    top_waste = sorted(by_ing_waste.items(), key=lambda x: -x[1])[:8]
    waste_chart = charts.hbars([{
        "label": names[i].name if i in names else str(i), "value": v, "text": _money(v),
        "tip": f"{names[i].name if i in names else i}: hao hụt {_money(v)}"
               + (f", bằng {v / (used_qty[i] * prices.at(i, end_day)) * 100:.1f}% giá trị đã dùng"
                  if used_qty.get(i) and prices.at(i, end_day) else "")} for i, v in top_waste],
        label_w=110, width=charts.THIRD)

    supplier_chart = charts.share_bar(
        [(name, v, slot) for (name, v), slot in zip(sorted(by_supplier.items(), key=lambda x: -x[1])[:3], (1, 2, 3))]
        + ([("Khác", sum(v for _, v in sorted(by_supplier.items(), key=lambda x: -x[1])[3:]), "muted")]
           if len(by_supplier) > 3 else []), value_fmt=lambda v: _money(v))

    # Lịch hết hạn: giá trị tồn theo tuần hết hạn (cột đầu là phần đã quá hạn)
    buckets = [0.0] * (WEEKS_AHEAD + 1)
    undated = 0.0
    for d in view.values():
        for v in d["lots"]:
            if v.expiry_date is None:
                undated += v.value
                continue
            k = 0 if v.expiry_date < today else 1 + min((v.expiry_date - today).days // 7, WEEKS_AHEAD - 1)
            buckets[k] += v.value
    labels = ["Quá hạn"] + [f"{today + timedelta(days=7 * k):%d/%m}" for k in range(WEEKS_AHEAD)]
    expiry_chart = charts.stacked_columns(labels, [
        {"name": "Đã quá hạn", "values": [buckets[0]] + [0] * WEEKS_AHEAD, "slot": "critical"},
        {"name": "Hết hạn trong tuần", "values": [0] + buckets[1:], "slot": 1}], width=charts.HALF,
        tips=[f"Đã quá hạn, còn trong kho: {_money(buckets[0])}"]
        + [f"Hết hạn trong 7 ngày từ {today + timedelta(days=7 * k):%d/%m}: {_money(buckets[k + 1])}"
           for k in range(WEEKS_AHEAD)])

    # Tuổi lô đang còn
    age = [0.0] * len(AGE_BUCKETS)
    for d in view.values():
        for v in d["lots"]:
            for k, (lo, hi, _) in enumerate(AGE_BUCKETS):
                if lo <= v.age_days <= hi:
                    age[k] += v.value
                    break
    age_chart = charts.columns([(label, age[k], f"Lô đã nhập {label} ngày: {_money(age[k])}")
                                for k, (_, _, label) in enumerate(AGE_BUCKETS)], height=200, width=charts.WIDE) if any(age) else None

    # Độ phủ so với thời gian giao hàng (nguyên liệu dùng nhiều nhất trước)
    cover_rows = []
    for ing in ingredients:
        d = view[ing.pk]
        if not d["rate"]:
            continue
        need = ing.lead_time_days + 1
        cover = d["cover_days"] or 0
        status = "critical" if cover < need else "warn" if cover < need + 2 else None
        cover_rows.append({"label": ing.name, "value": min(cover, 60), "marker": need, "status": status,
                           "text": f"{cover:.0f} ngày" if cover < 60 else "trên 60 ngày", "below": status == "critical",
                           "tip": f"{ing.name}: đủ dùng {cover:.1f} ngày".replace(".", ",")
                                  + f", giao hàng mất {ing.lead_time_days} ngày"})
    cover_rows.sort(key=lambda r: r["value"])
    cover_chart = charts.hbars(cover_rows[:12], "marker", label_w=130, width=charts.HALF)

    spark = charts.sparkline([flow[StockMovement.Kind.CONSUME].get(d, 0) for d in days])

    # Nhận định tự động: chỉ nêu điều số liệu cho thấy rõ, kèm việc nên làm.
    notes = []
    expired_lots = [(v, names.get(i)) for i, d in view.items() for v in d["expired"]]
    if expired_lots:
        notes.append(f"Còn {len(expired_lots)} lô quá hạn nằm trong kho, trị giá {_money(buckets[0])} "
                     f"({', '.join(sorted({n.name for _, n in expired_lots if n}))}): để riêng và hủy ở Phiếu lấy hàng.")
    short = [r for r in cover_rows if r["status"] == "critical"]
    for r in short[:2]:
        notes.append(f"{r['tip']}: có thể hết trước khi hàng mới về, nên đặt ngay.")
    if top_waste and waste_value:
        i, v = top_waste[0]
        reason = max(((k, x) for (ing, k), x in by_ing_reason.items() if ing == i), key=lambda t: t[1])[0]
        advice = {Waste.Reason.EXPIRED: "giảm lượng mỗi lần nhập hoặc nhập thưa hơn",
                  Waste.Reason.DAMAGED: "kiểm tra cách bảo quản và hàng lúc nhận",
                  Waste.Reason.BROKEN: "xem lại chỗ để và cách xếp hàng",
                  Waste.Reason.FAILED_PREP: "xem lại công thức hoặc kèm thêm cho người mới"}.get(reason, "tìm nguyên nhân")
        notes.append(f"{names[i].name if i in names else i} hao hụt nhiều nhất: {_money(v)}, bằng "
                     f"{v / waste_value * 100:.0f}% hao hụt cả kỳ, chủ yếu do {reason_labels[reason].lower()}: {advice}.")
    risk = sorted(((d["at_risk_value"], names[i]) for i, d in view.items() if d["at_risk_value"] and i in names),
                  key=lambda t: -t[0])
    if risk:
        notes.append(f"Theo tốc độ dùng 4 tuần qua, khoảng {_money(sum(v for v, _ in risk))} hàng sẽ hết hạn trước khi "
                     f"kịp dùng, nhiều nhất là {risk[0][1].name} ({_money(risk[0][0])}).")
    if dio:
        notes.append(f"Hàng nằm trong kho trung bình {dio:.1f} ngày trước khi được dùng.".replace(".", ",", 1))
    return {
        "notes": notes,
        "stock_value": stock_value, "receipt_value": receipt_value, "consume_value": consume_value,
        "waste_value": waste_value, "waste_share": waste_value / (consume_value + waste_value) * 100
        if consume_value + waste_value else None, "dio": dio, "spark": spark,
        "value_chart": value_chart, "flow_chart": flow_chart, "reason_chart": reason_chart, "waste_chart": waste_chart,
        "supplier_chart": supplier_chart, "expiry_chart": expiry_chart, "age_chart": age_chart,
        "cover_chart": cover_chart, "undated_value": round(undated),
        "expired_value": buckets[0], "near_value": sum(buckets[1:3]),
        "at_risk_value": sum(d["at_risk_value"] for d in view.values()),
        "value_table": list(zip(days, value_series)),
        "weeks": [(w, week_sum(StockMovement.Kind.CONSUME, w), week_sum(StockMovement.Kind.WASTE, w)) for w in weeks],
        "reasons": [(reason_labels[k], v) for k, v in sorted(by_reason.items(), key=lambda x: -x[1])],
        "expiry_table": list(zip(labels, buckets)),
    }
