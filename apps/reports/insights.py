"""Phân tích bán hàng cho bảng điều khiển và báo cáo doanh thu.

Chỉ số chính so với kỳ trước, xu hướng theo ngày, giờ đông khách (thứ × giờ), cơ cấu món, nhóm món, phương thức thanh
toán và ma trận thực đơn theo phương pháp Kasavana và Smith (1982): mỗi món xếp theo độ phổ biến (số ly) và lãi gộp
mỗi ly. Giá vốn lấy từ lượng nguyên liệu thực trừ kho của từng dòng món (gồm cả tùy chọn như trân châu, kem muối) nhân
giá nhập gần nhất tính tới ngày trừ kho.

Doanh thu cùng định nghĩa với báo cáo doanh thu (services.revenue): giá trị món tính tiền của đơn đã thu tiền, theo
thời điểm thanh toán. Hoàn tiền không trừ ở đây (báo cáo doanh thu có dòng doanh thu thuần).
"""

from collections import defaultdict
from datetime import timedelta

from django.utils import timezone

from . import charts
from .services import _paid_lines, period_bounds

WEEKDAYS = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"]
WEEKDAY_NAMES = ["Thứ hai", "Thứ ba", "Thứ tư", "Thứ năm", "Thứ sáu", "Thứ bảy", "Chủ nhật"]
POPULARITY_SHARE = 0.7  # Kasavana và Smith: món phổ biến khi số ly đạt 70% mức chia đều cho mọi món
QUADRANTS = {"tr": "Ngôi sao", "br": "Bán chạy, lãi mỏng", "tl": "Lãi cao, ít người gọi", "bl": "Cân nhắc bỏ"}
QUADRANT_ADVICE = {"tr": "Giữ chất lượng, đặt ở vị trí nổi bật trên thực đơn.",
                   "br": "Xem lại giá bán hoặc định mức để tăng lãi mỗi ly.",
                   "tl": "Giới thiệu thêm cho khách, đặt cạnh món bán chạy.",
                   "bl": "Cân nhắc bỏ hoặc thay món mới."}


def _money(v):
    return f"{int(round(v)):,} đ".replace(",", ".")


def _num(v, digits=0):
    text = f"{v:,.{digits}f}".replace(",", " ").replace(".", ",").replace(" ", ".")
    return text


def _pct(cur, prev):
    if not prev:
        return None
    return (cur - prev) / prev * 100


class _Period:
    """Gom dòng món đã thu tiền của một kỳ theo ngày, món, nhóm, phương thức và thứ × giờ."""

    def __init__(self, start_day, end_day, prices):
        from apps.inventory.models import StockMovement

        self.start_day, self.end_day = start_day, end_day
        start, end = period_bounds(start_day, end_day)
        lines = list(_paid_lines(start, end))
        # Giá vốn: lượng nguyên liệu thực trừ kho của từng dòng món (nguồn "dong_mon"); món pha trước lúc thu tiền
        # nên lấy rộng thêm hai ngày về trước.
        cost_of = defaultdict(float)
        if lines:
            ids = {str(l.pk) for l in lines}
            for sid, ing, at, q in (StockMovement.objects
                                    .filter(source_type="dong_mon", created_at__gte=start - timedelta(days=2),
                                            created_at__lt=end)
                                    .values_list("source_id", "ingredient_id", "created_at", "quantity")):
                if sid in ids:
                    cost_of[sid] += -float(q) * float(prices.at(ing, timezone.localdate(at)))
        self.revenue = self.cups = 0
        self.cost = 0.0
        self.order_ids = set()
        self.days = defaultdict(lambda: {"revenue": 0, "orders": set(), "cups": 0, "cost": 0.0})
        self.items = defaultdict(lambda: {"revenue": 0, "cups": 0, "cost": 0.0, "group": ""})
        self.groups, self.methods = defaultdict(int), defaultdict(int)
        self.slots = defaultdict(set)
        for line in lines:
            value = line.unit_price * line.billable_quantity
            cups = line.billable_quantity
            cost = cost_of.get(str(line.pk), 0.0)
            paid = timezone.localtime(line.order.payment.created_at)
            created = timezone.localtime(line.order.created_at)
            self.revenue += value
            self.cups += cups
            self.cost += cost
            self.order_ids.add(line.order_id)
            d = self.days[paid.date()]
            d["revenue"] += value
            d["orders"].add(line.order_id)
            d["cups"] += cups
            d["cost"] += cost
            it = self.items[line.item_name]
            it["revenue"] += value
            it["cups"] += cups
            it["cost"] += cost
            it["group"] = line.item.group.name
            self.groups[line.item.group.name] += value
            self.methods[line.order.payment.get_method_display()] += value
            self.slots[(created.weekday(), created.hour)].add(line.order_id)

    @property
    def orders(self):
        return len(self.order_ids)

    @property
    def margin(self):
        return self.revenue - self.cost

    def series(self, key):
        out = []
        d = self.start_day
        while d <= self.end_day:
            day = self.days.get(d)
            if day is None:
                out.append(0)
            elif key == "orders":
                out.append(len(day["orders"]))
            elif key == "aov":
                out.append(day["revenue"] / len(day["orders"]) if day["orders"] else None)
            elif key == "margin":
                out.append(day["revenue"] - day["cost"])
            else:
                out.append(day[key])
            d += timedelta(days=1)
        return out


def sales(start_day, end_day, prev=None, today=None, wide=False):
    """Phân tích bán hàng kỳ [start_day, end_day]; prev = (từ, đến) của kỳ so sánh, mặc định là kỳ liền trước cùng độ
    dài. wide: biểu đồ xu hướng chiếm cả hàng."""
    from .inventory import Prices

    today = today or timezone.localdate()
    end_day = min(end_day, today) if start_day <= today else end_day
    length = (end_day - start_day).days + 1
    if prev is None:
        prev = (start_day - timedelta(days=length), start_day - timedelta(days=1))
    prices = Prices()
    cur, old = _Period(start_day, end_day, prices), _Period(prev[0], prev[1], prices)
    has_cost = cur.cost > 0

    aov = cur.revenue / cur.orders if cur.orders else 0
    old_aov = old.revenue / old.orders if old.orders else 0
    kpis = [
        {"label": "Doanh thu", "value": cur.revenue, "unit": "đ", "delta": _pct(cur.revenue, old.revenue),
         "spark": charts.sparkline(cur.series("revenue")), "prev": old.revenue},
        {"label": "Số đơn", "value": cur.orders, "unit": "", "delta": _pct(cur.orders, old.orders),
         "spark": charts.sparkline(cur.series("orders")), "prev": old.orders},
        {"label": "Giá trị mỗi đơn", "value": round(aov), "unit": "đ", "delta": _pct(aov, old_aov),
         "spark": charts.sparkline(cur.series("aov")), "prev": round(old_aov)},
        {"label": "Số ly", "value": cur.cups, "unit": "", "delta": _pct(cur.cups, old.cups),
         "spark": charts.sparkline(cur.series("cups")), "prev": old.cups},
    ]
    if has_cost:
        kpis.append({"label": "Lãi gộp ước tính", "value": round(cur.margin), "unit": "đ",
                     "delta": _pct(cur.margin, old.margin) if old.cost else None,
                     "spark": charts.sparkline(cur.series("margin")), "prev": round(old.margin),
                     "note": f"Giá vốn nguyên liệu {cur.cost / cur.revenue * 100:.0f}% doanh thu".replace(".", ",")
                     if cur.revenue else ""})

    for k in kpis:
        k["delta_abs"] = abs(k["delta"]) if k["delta"] is not None else None

    days = [start_day + timedelta(days=k) for k in range(length)]
    cur_rev, old_rev = cur.series("revenue"), old.series("revenue")
    old_days = [prev[0] + timedelta(days=k) for k in range(len(old_rev))]
    series = [{"name": "Kỳ này", "values": cur_rev, "slot": 1, "area": True}]
    if any(old_rev):
        aligned = [old_rev[k] if k < len(old_rev) else None for k in range(length)]
        series.append({"name": f"Kỳ trước ({prev[0]:%d/%m}–{prev[1]:%d/%m})", "values": aligned, "slot": "muted",
                       "label_end": False})
    tips = [f"{d:%d/%m}" + (f" (kỳ trước {old_days[k]:%d/%m})" if k < len(old_days) and any(old_rev) else "")
            for k, d in enumerate(days)]
    trend_chart = charts.line([f"{d:%d/%m}" for d in days], series, value_fmt=charts.fmt, tip_labels=tips,
                              width=charts.WIDE if wide else charts.HALF, height=240) if cur.revenue else None

    # Thứ × giờ: số đơn trung bình mỗi ngày cùng thứ (đếm số ngày từng thứ trong kỳ)
    weekday_count = [0] * 7
    for d in days:
        weekday_count[d.weekday()] += 1
    hours = sorted({h for _, h in cur.slots}) or list(range(7, 22))
    hours = list(range(min(hours), max(hours) + 1))
    values = [[len(cur.slots.get((w, h), ())) / weekday_count[w] if weekday_count[w] else 0 for h in hours]
              for w in range(7)]
    heat_chart = charts.heatmap(
        WEEKDAYS, [f"{h}h" for h in hours], values, width=charts.HALF,
        tip=lambda r, c, v: f"{WEEKDAY_NAMES[r]}, {hours[c]}–{hours[c] + 1} giờ: trung bình {_num(v, 1)} đơn mỗi ngày",
        value_fmt=lambda v: _num(v, 1)) if cur.slots else None
    peak = max(((w, h, values[w][i]) for w in range(7) for i, h in enumerate(hours)), key=lambda x: x[2],
               default=None)

    # Món: doanh thu, số ly, lãi gộp mỗi ly
    items = sorted(cur.items.items(), key=lambda x: -x[1]["revenue"])
    top_chart = charts.hbars([{
        "label": name, "value": it["revenue"], "text": f"{charts.fmt(it['revenue'])} · {it['cups']} ly",
        "tip": f"{name}: {_money(it['revenue'])}, {it['cups']} ly, {it['revenue'] / cur.revenue * 100:.0f}% doanh thu"
    } for name, it in items[:10]], label_w=130, width=charts.HALF) if items else None

    matrix_chart, matrix_rows = None, []
    if has_cost and len(items) >= 2:
        x_mid = POPULARITY_SHARE * cur.cups / len(items)
        y_mid = cur.margin / cur.cups if cur.cups else 0
        points = []
        for name, it in items:
            if not it["cups"]:
                continue
            m = (it["revenue"] - it["cost"]) / it["cups"]
            quad = ("t" if m >= y_mid else "b") + ("r" if it["cups"] >= x_mid else "l")
            matrix_rows.append({"name": name, "group": it["group"], "cups": it["cups"], "revenue": it["revenue"],
                                "cost_per_cup": round(it["cost"] / it["cups"]), "margin_per_cup": round(m),
                                "margin_pct": m / (it["revenue"] / it["cups"]) * 100 if it["revenue"] else 0,
                                "quad": quad, "quad_label": QUADRANTS[quad], "advice": QUADRANT_ADVICE[quad]})
            points.append({"x": it["cups"], "y": m, "label": name,
                           "tip": f"{name}: {it['cups']} ly, lãi gộp {_money(m)}/ly (giá vốn {_money(it['cost'] / it['cups'])}"
                                  f"/ly) · {QUADRANTS[quad]}"})
        matrix_chart = charts.scatter(points, x_mid, y_mid, x_fmt=charts.fmt, y_fmt=charts.fmt, quadrants=QUADRANTS,
                                      width=charts.HALF, height=300, label_top=8)
        order = {"tr": 0, "br": 1, "tl": 2, "bl": 3}
        matrix_rows.sort(key=lambda r: (order[r["quad"]], -r["revenue"]))

    def share(parts_dict):
        parts = sorted(parts_dict.items(), key=lambda x: -x[1])
        head = [(name, v, slot) for (name, v), slot in zip(parts[:3], (1, 2, 3))]
        rest = sum(v for _, v in parts[3:])
        return charts.share_bar(head + ([("Khác", rest, "muted")] if rest else []), value_fmt=_money)

    group_chart = share(cur.groups) if cur.groups else None
    method_chart = share(cur.methods) if cur.methods else None

    # Nhận định tự động cho Chủ quán: chỉ nêu điều số liệu cho thấy rõ.
    notes = []
    d_rev, d_ord, d_aov = _pct(cur.revenue, old.revenue), _pct(cur.orders, old.orders), _pct(aov, old_aov)
    if d_rev is not None and d_ord is not None and d_aov is not None and cur.revenue:
        driver = "chủ yếu do số đơn" if abs(d_ord) >= abs(d_aov) else "chủ yếu do giá trị mỗi đơn"
        notes.append(f"Doanh thu {'tăng' if d_rev >= 0 else 'giảm'} {abs(d_rev):.0f}% so với kỳ trước, {driver} "
                     f"(số đơn {d_ord:+.0f}%, giá trị mỗi đơn {d_aov:+.0f}%).")
    if peak and peak[2] > 0:
        notes.append(f"Đông nhất vào {WEEKDAY_NAMES[peak[0]].lower()}, {peak[1]}–{peak[1] + 1} giờ: trung bình "
                     f"{_num(peak[2], 1)} đơn mỗi ngày. Xếp đủ pha chế cho khung này.")
    if items and cur.revenue:
        name, it = items[0]
        notes.append(f"{name} mang lại nhiều doanh thu nhất: {it['revenue'] / cur.revenue * 100:.0f}% doanh thu, "
                     f"{it['cups']} ly.")
    plow = [r for r in matrix_rows if r["quad"] == "br"]
    if plow:
        r = max(plow, key=lambda r: r["cups"])
        notes.append(f"{r['name']} bán chạy nhưng lãi mỏng ({_money(r['margin_per_cup'])}/ly, thấp hơn mức bình quân "
                     f"{_money(cur.margin / cur.cups)}/ly): xem lại giá bán hoặc định mức.")
    if has_cost and cur.revenue:
        notes.append(f"Giá vốn nguyên liệu bằng {cur.cost / cur.revenue * 100:.0f}% doanh thu"
                     + (f" (kỳ trước {old.cost / old.revenue * 100:.0f}%)." if old.cost and old.revenue else "."))

    return {
        "has_sales": bool(cur.revenue), "kpis": kpis, "prev_period": prev, "trend_chart": trend_chart,
        "trend_table": [(d, cur_rev[k], old_rev[k] if k < len(old_rev) else None) for k, d in enumerate(days)],
        "heat_chart": heat_chart, "top_chart": top_chart, "matrix_chart": matrix_chart, "matrix_rows": matrix_rows,
        "group_chart": group_chart, "method_chart": method_chart, "notes": notes, "has_cost": has_cost,
        "revenue": cur.revenue, "orders": cur.orders, "cost": cur.cost,
    }


def dimension_chart(data):
    """Biểu đồ cho báo cáo doanh thu theo một chiều: ngày → đường (đã có ở sales), khung giờ → cột theo giờ,
    phương thức → thanh tỷ phần, chiều còn lại → thanh ngang xếp theo doanh thu."""
    rows, dim = data["rows"], data["dim"]
    if not rows or dim == "ngay":
        return None, None
    total = data["total"] or 1
    if dim == "khung_gio":
        return "columns", charts.columns(
            [(r["key"].split("–")[0].lstrip("0") + "h", r["revenue"],
              f"{r['key']}: {_money(r['revenue'])} · {r['orders']} đơn · {r['cups']} ly") for r in rows],
            width=charts.WIDE, height=220)
    if dim == "phuong_thuc":
        parts = sorted(rows, key=lambda r: -r["revenue"])
        return "share", charts.share_bar([(r["key"], r["revenue"], slot) for r, slot in zip(parts, (1, 2, 3, "muted"))],
                                         value_fmt=_money)
    top = sorted(rows, key=lambda r: -r["revenue"])[:15]
    return "hbars", charts.hbars([{
        "label": r["key"], "value": r["revenue"], "text": f"{charts.fmt(r['revenue'])} · {r['revenue'] / total * 100:.0f}%",
        "tip": f"{r['key']}: {_money(r['revenue'])}, {r['orders']} đơn, {r['cups']} ly"} for r in top],
        label_w=190, width=charts.WIDE)
