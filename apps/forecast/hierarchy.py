"""Dự báo phân cấp (PH): tổng số ly cả quán → số ly từng món → lượng nguyên liệu theo định mức (phân tích "Lựa chọn
mô hình dự báo và quản lý nguyên vật liệu cho LAM Coffee" ngày 27/10/2026, mục dự báo theo món nhân định mức).

1. Tổng số ly mỗi ngày của cả quán là chuỗi ổn định nhất: chọn cách tính cho chuỗi này trong bình quân theo loại ngày,
   bình quân có trọng số cùng thứ và Holt-Winters (methods.forecast_series), theo sai số cuốn chiếu.
2. Mỗi món-kích cỡ có một dự báo riêng từ chuỗi số ly của nó: bình quân có trọng số cùng thứ; món bán lác đác dùng
   TSB; món mới chưa đủ ngày bán dùng nhận định số ly của Chủ quán nếu có. Các dự báo riêng chỉ dùng làm tỷ trọng:
   số ly món i ngày t = tổng số ly dự báo ngày t × dự báo riêng món i / tổng các dự báo riêng (điều hòa từ trên xuống
   theo tỷ lệ, để tổng các món luôn bằng tổng cả quán).
3. Lượng nguyên liệu = tổng theo món của số ly × lượng mỗi ly. Lượng mỗi ly gồm phần tùy chọn theo tỷ lệ khách chọn
   trong 8 tuần gần nhất; bán thành phẩm (cà phê cốt, nước đường, foam) quy ra nguyên liệu gốc theo định mức bán thành
   phẩm khi tính nhu cầu mua.

Ngày một món bị chặn (thiếu nguyên liệu của chính món) không dùng để học món đó. Ngày tổng cả quán bị bỏ qua khi các món
bị chặn chiếm từ ngưỡng chặn gián tiếp trở lên số ly thường lệ.

Đánh giá: tại mỗi gốc của đánh giá cuốn chiếu, dự báo tổng chỉ dùng dữ liệu tới gốc (methods.rolling giữ dự báo từng
gốc), tỷ trọng món cũng chỉ dùng dữ liệu tới gốc; riêng tỷ lệ chọn tùy chọn lấy theo 8 tuần gần nhất. Kết quả đưa vào
methods.forecast_series dưới dạng dự báo ngoài (external) để so cùng một cách với các cách tính trực tiếp trên chuỗi
nguyên liệu.

Phần đầu là hàm thuần (dùng chung cho mô phỏng); `from_usage` đọc dữ liệu đã dựng ở usage.build.
"""

from collections import defaultdict
from datetime import timedelta

from . import methods

TOTAL_CANDIDATES = ("LN", "WMA", "HW")
TOTAL_DECISION_H = 7  # chọn cách tính cho tổng số ly theo sai số tổng 7 ngày: nhịp mua hàng tuần


class Item:
    """Một món-kích cỡ: chuỗi số ly [(ngày, số ly hoặc None, trạng thái)], lượng nguyên liệu mỗi ly, nhận định của
    Chủ quán {False: ngày thường, True: cuối tuần} nếu có, nhóm món."""

    def __init__(self, key, series, usage, judgement=None, group=None, label=""):
        self.key, self.series, self.usage, self.judgement, self.group = key, series, usage, judgement, group
        self.label = label
        self.first_sale = next((d for d, x, st in series if st == "ok" and x), None)


def _bottom(item, idx, cfg, owner_days, tsb, intermittent):
    """Hàm ngày → dự báo riêng của món tại gốc idx (chỉ dùng dữ liệu tới hết ngày idx)."""
    end = item.series[idx][0] if idx >= 0 else None
    new = item.first_sale is None or end is None or item.first_sale > end - timedelta(days=owner_days)
    if new and item.judgement:
        j = item.judgement
        return lambda t: j[methods.is_weekend(t)]
    if end is None or item.first_sale is None or item.first_sale > end:
        return lambda t: 0.0
    if intermittent:
        value = tsb.value if tsb is not None else 0.0
        return lambda t: value
    table = methods.wma_table(item.series[max(0, idx - 7 * cfg.wma_weeks):idx + 1], end, cfg)
    if table is None:
        return lambda t: 0.0
    return lambda t: table[t.weekday()]


def build(total, items, *, today, horizon, cfg=methods.DEFAULT, approved=None, owner_days=14, hw_params=None):
    """Dự báo tổng số ly, dự báo từng món đã điều hòa tại mỗi gốc đánh giá và từ hôm nay.

    total: chuỗi tổng số ly cả quán; items: [Item] cùng lịch ngày với total. Trả dict:
    - "total": kết quả methods.forecast_series của tổng số ly (cách tính, sai số, cảnh báo);
    - "origins": {ngày gốc ISO: {ngày ISO: {khóa món: số ly}}}; "today": {ngày ISO: {khóa món: số ly}};
    - "item_wape": sai số WAPE dự báo 1 ngày theo món trên các gốc (tổng sai số tuyệt đối / tổng thực tế)."""
    total_fc = methods.forecast_series(total, today=today, horizon=horizon, cfg=cfg, candidates=TOTAL_CANDIDATES,
                                       approved=approved, decision_h=TOTAL_DECISION_H, hw_params=hw_params)
    out = {"total": total_fc, "origins": {}, "today": {}, "item_wape": None, "items": {}}
    method = total_fc.get("method")
    if not method or not total or total_fc.get("requires_approval"):
        return out
    keep_days = horizon + 7
    res = methods.rolling(total, method, cfg, h_max=1, keep=True, keep_days=keep_days, hw_params=hw_params)
    preds = res["predictions"]
    classes = {it.key: methods.demand_class(it.series, it.series[-1][0], cfg) if it.series else None for it in items}
    intermittent = {k: bool(c and c["intermittent"]) for k, c in classes.items()}
    tsb = {it.key: None for it in items}
    seen = {it.key: [] for it in items}
    index = {d.isoformat(): i for i, (d, _, _) in enumerate(total)}
    abs_err = actual = 0.0
    by_item = defaultdict(lambda: [0.0, 0.0])
    for i, (d, _, _) in enumerate(total):
        for it in items:
            if not intermittent[it.key]:
                continue
            _, x, st = it.series[i]
            if st == "ok":
                seen[it.key].append((d, x))
                if tsb[it.key] is None:
                    tsb[it.key] = methods.tsb_build(seen[it.key], cfg)
                else:
                    tsb[it.key].update(x)
        iso = d.isoformat()
        if iso not in preds:
            continue
        bottoms = {it.key: _bottom(it, i, cfg, owner_days, tsb[it.key], intermittent[it.key]) for it in items}
        table = _reconcile(preds[iso], bottoms)
        out["origins"][iso] = table
        nxt = (d + timedelta(days=1)).isoformat()
        j = index.get(nxt)
        if j is not None and nxt in table:
            for it in items:
                _, x, st = it.series[j]
                if st == "ok":
                    f = table[nxt].get(it.key, 0.0)
                    abs_err += abs(x - f)
                    actual += x
                    by_item[it.key][0] += abs(x - f)
                    by_item[it.key][1] += x
    last = len(total) - 1
    bottoms = {it.key: _bottom(it, last, cfg, owner_days, tsb[it.key], intermittent[it.key]) for it in items}
    out["today"] = _reconcile(total_fc.get("daily") or {}, bottoms)
    out["item_wape"] = round(abs_err / actual, 4) if actual > 0 else None
    out["items"] = {it.key: {"class": classes[it.key], "wape": round(e / a, 4) if a > 0 else None, "label": it.label}
                    for it in items for e, a in [by_item.get(it.key, (0.0, 0.0))]}
    return out


def _reconcile(total_by_day, bottoms):
    """{ngày ISO: {món: số ly}}: chia tổng số ly của ngày theo tỷ lệ các dự báo riêng."""
    from datetime import date

    out = {}
    for iso, c in total_by_day.items():
        t = date.fromisoformat(iso)
        raw = {k: max(f(t), 0.0) for k, f in bottoms.items()}
        s = sum(raw.values())
        out[iso] = {k: c * v / s for k, v in raw.items() if v > 0} if s > 0 else {}
    return out


def ingredient_forecast(h, items, ingredient):
    """(external, external_daily) cho một nguyên liệu: tổng theo món của số ly × lượng mỗi ly; None nếu không món nào
    dùng nguyên liệu này hoặc chưa có dự báo tổng."""
    users = [(it.key, it.usage[ingredient]) for it in items if it.usage.get(ingredient)]
    if not users or not h["today"]:
        return None, None

    def per_day(table):
        return {iso: sum(cups.get(k, 0.0) * q for k, q in users) for iso, cups in table.items()}

    external = {o: per_day(table) for o, table in h["origins"].items()}
    return external, per_day(h["today"])


def group_shares(items, ingredient, recent_cups):
    """Phần tiêu hao của nguyên liệu theo nhóm món trong 8 tuần gần nhất: {nhóm: tỷ lệ} (cho điều chỉnh mùa theo nhóm
    món: một nhóm tăng, nhóm khác giảm thì không nhân cùng một mức cho mọi nguyên liệu)."""
    by = defaultdict(float)
    for it in items:
        q = it.usage.get(ingredient)
        if q:
            by[it.group] += q * recent_cups.get(it.key, 0.0)
    total = sum(by.values())
    return {g: v / total for g, v in by.items()} if total > 0 else {}


# ---------------- đọc dữ liệu đã dựng ----------------

def from_usage(data, now, explode=True):
    """(chuỗi tổng số ly, [Item], {món: số ly 8 tuần}) từ dữ liệu usage.build. Lượng mỗi ly quy bán thành phẩm ra
    nguyên liệu gốc khi explode (nhu cầu mua) và giữ nguyên bán thành phẩm cho chính bán thành phẩm."""
    from apps.catalog.models import ItemSize
    from apps.core import params

    from .services import current_judgements

    dates, status, configs, book = data["dates"], data["status"], data["configs"], data["book"]
    if not dates:
        return [], [], {}
    today = data["today"]
    recent_from = today - timedelta(days=56)
    cups = defaultdict(lambda: defaultdict(int))
    mix = defaultdict(lambda: defaultdict(int))
    for d, by in configs.items():
        for (item, size, opts), n in by.items():
            cups[(item, size)][d] += n
            if d >= recent_from:
                mix[(item, size)][opts] += n
    out_days = defaultdict(set)
    for ing, by_day in data["rows"].items():
        for d, r in by_day.items():
            if r["own_stockout"]:
                out_days[d].add(ing)
    keep_from = today - timedelta(days=56 + methods.DEFAULT.lookback + 7)
    judgements = current_judgements()
    sizes = {s.pk: s for s in ItemSize.objects.select_related("item", "item__group")}
    keys = {k for k, by in cups.items() if any(d >= keep_from for d in by)}
    keys |= {(sizes[sid].item_id, sid) for sid, _ in judgements if sid in sizes and sizes[sid].item.status == "dang_ban"}
    items, recent = [], {}
    for key in sorted(keys):
        item_id, size_id = key
        size = sizes.get(size_id)
        if size is None:
            continue
        usage = defaultdict(float)
        n_recent = sum(mix[key].values())
        if n_recent:
            for opts, n in mix[key].items():
                for ing, q in book.usage(item_id, size_id, opts, now, explode=explode).items():
                    usage[ing] += q * n / n_recent
        else:
            usage.update(book.usage(item_id, size_id, (), now, explode=explode))
        ings = set(book.usage(item_id, size_id, (), now).keys()) | {
            ing for opts in mix[key] for ing in book.usage(item_id, size_id, opts, now)}
        series = []
        for d in dates:
            st = status.get(d)
            if st == "dong_cua":
                series.append((d, None, "dong_cua"))
            elif st != "du_dieu_kien" or ings & out_days.get(d, set()):
                series.append((d, None, "bo_qua"))
            else:
                series.append((d, float(cups[key].get(d, 0)), "ok"))
        wd = judgements.get((size_id, "ngay_thuong"))
        we = judgements.get((size_id, "cuoi_tuan"))
        judgement = None
        if wd or we:
            wd, we = wd or we, we or wd
            judgement = {False: float(wd.typical), True: float(we.typical)}
        items.append(Item(key, series, dict(usage), judgement, size.item.group_id, f"{size.item.name} {size.name}"))
        recent[key] = n_recent
    threshold = params.get("plan_indirect_share_percent") / 100
    share_total = sum(recent.values())
    total = []
    for i, d in enumerate(dates):
        st = status.get(d)
        if st == "dong_cua":
            total.append((d, None, "dong_cua"))
            continue
        blocked = sum(recent[it.key] for it in items if it.series[i][2] == "bo_qua") / share_total if share_total else 0
        if st != "du_dieu_kien" or blocked >= threshold:
            total.append((d, None, "bo_qua"))
        else:
            total.append((d, float(sum(by.get(d, 0) for by in cups.values())), "ok"))
    return total, items, recent
