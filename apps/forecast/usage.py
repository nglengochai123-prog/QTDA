"""Chuỗi tiêu hao nguyên liệu theo ngày (thiết kế mua nguyên liệu mục 5).

- U b: dòng món có tính tiền theo ngày bán × định mức có hiệu lực tại ngày được dự báo (mục 5.4), gồm đủ tùy chọn
  thật của dòng đơn. Chuỗi lịch sử dựng theo định mức hiện hành; ngày tương lai có định mức hẹn ngày được nhân hệ số
  quy đổi riêng (recipe_ratio).
- U h: ly đã pha rồi hủy; hao hụt vận hành (pha hỏng, đổ vỡ, khác, trừ sự cố đơn lẻ); chênh lệch kiểm kê có hệ thống
  (âm liên tiếp ít nhất 4 lần). Hư hỏng và hết hạn là chỉ số, không phải nhu cầu.
- Cờ ngày: đóng cửa, chưa chốt, hết hàng của chính nguyên liệu, bị chặn gián tiếp do món dùng nguyên liệu khác bị
  ngừng bán (món đó chiếm từ 20% tiêu hao của nguyên liệu này).
- Đối soát: U b theo lượng chụp lúc bán cộng U h phải khớp tiêu hao pha chế trong sổ kho, lệch trên 1% thì báo.
"""

from collections import defaultdict
from datetime import datetime, time, timedelta

from django.conf import settings
from django.utils import timezone

from apps.core import params

WINDOW = 56  # 8 tuần cho các tỷ lệ
OPERATIONAL = ("pha_hong", "do_vo", "khac")
STOCK_LOSS = ("hu_hong", "het_han")


def empty_row():
    return {"sales": 0.0, "sales_as_sold": 0.0, "voided": 0.0, "waste_operational": 0.0, "waste_one_off": 0.0,
            "waste_stock": 0.0, "count_adjust": 0.0, "consumed_ledger": 0.0, "own_stockout": False,
            "indirect_block": False}


def _aware(day):
    return timezone.make_aware(datetime.combine(day, time.min), timezone.get_current_timezone())


def _local_day(dt):
    return timezone.localtime(dt).date()


class RecipeBook:
    """Lượng nguyên liệu mỗi ly theo cấu hình (kích cỡ, tùy chọn) và phiên bản định mức hiệu lực tại một thời điểm."""

    def __init__(self):
        self._versions = {}
        self._lines = {}

    def version(self, item_id, at):
        from apps.inventory.models import RecipeVersion

        key = (item_id, at)
        if key not in self._versions:
            self._versions[key] = (RecipeVersion.objects.published().filter(item_id=item_id, effective_from__lte=at)
                                   .order_by("-effective_from", "-number").values_list("pk", flat=True).first())
        return self._versions[key]

    def lines(self, version_id):
        from apps.inventory.models import RecipeLine

        if version_id not in self._lines:
            by_size, by_option = defaultdict(dict), defaultdict(dict)
            for line in RecipeLine.objects.filter(version_id=version_id):
                target = by_size[line.size_id] if line.size_id else by_option[line.option_id]
                target[line.ingredient_id] = target.get(line.ingredient_id, 0.0) + float(line.quantity)
            self._lines[version_id] = (by_size, by_option)
        return self._lines[version_id]

    def usage(self, item_id, size_id, option_ids, at):
        version = self.version(item_id, at)
        if version is None:
            return {}
        by_size, by_option = self.lines(version)
        out = dict(by_size.get(size_id, {}))
        for opt in option_ids:
            for ing, q in by_option.get(opt, {}).items():
                out[ing] = out.get(ing, 0.0) + q
        return out

    def items_using(self, at_items, ingredient_id, at):
        """Món có dòng định mức (kích cỡ hoặc tùy chọn) dùng nguyên liệu này."""
        out = set()
        for item_id in at_items:
            version = self.version(item_id, at)
            if version is None:
                continue
            by_size, by_option = self.lines(version)
            if any(ingredient_id in d for d in by_size.values()) or any(ingredient_id in d for d in by_option.values()):
                out.add(item_id)
        return out


def sold_configs(start, end):
    """{ngày bán: {(món, kích cỡ, tùy chọn): số ly tính tiền}} và {ngày: {nguyên liệu: lượng theo định mức lúc bán}}.

    Ngày bán của phiếu dự phòng là thời điểm bán ghi trên phiếu. Đọc bằng values_list vì lịch sử có thể hàng chục nghìn
    dòng."""
    from apps.orders.models import OrderLine, OrderLineOption

    lo, hi = _aware(start - timedelta(days=2)), _aware(end + timedelta(days=3))
    options = defaultdict(list)
    for line_id, option_id in (OrderLineOption.objects.filter(line__order__created_at__gte=lo,
                                                               line__order__created_at__lt=hi)
                               .values_list("line_id", "option_id")):
        options[line_id].append(option_id)
    configs = defaultdict(lambda: defaultdict(int))
    as_sold = defaultdict(lambda: defaultdict(float))
    rows = (OrderLine.objects.filter(order__created_at__gte=lo, order__created_at__lt=hi)
            .values_list("id", "item_id", "size_id", "quantity", "cancelled_quantity", "voided_done_quantity",
                         "usage_per_unit", "order__created_at", "order__backup_slip__sold_at"))
    for line_id, item_id, size_id, qty, cancelled, voided, per_unit, created, sold_at in rows.iterator(chunk_size=5000):
        cups = qty - cancelled - voided
        day = _local_day(sold_at or created)
        if not (start <= day <= end) or cups <= 0:
            continue
        configs[day][(item_id, size_id, tuple(sorted(options.get(line_id, ()))))] += cups
        for ing, q in (per_unit or {}).items():
            as_sold[day][int(ing)] += float(q) * cups
    return configs, as_sold


def _imported(include_simulated):
    from .services import imported_history

    return imported_history(include_simulated)


def build(today=None, days=365, include_simulated=None, now=None):
    """Dựng chuỗi tiêu hao cho mọi nguyên liệu. Trả dict:
    {"dates": [...], "status": {ngày: trạng thái}, "rows": {ing: {ngày: {...}}}, "configs": ..., "book": RecipeBook}.
    """
    from apps.inventory.models import (Ingredient, QuickReport, ShortageCase, StockCount, StockMovement, Waste)
    from apps.orders.models import PostPrepCancellation
    from apps.shifts.models import Shift

    from .services import day_status

    now = now or timezone.now()
    today = today or timezone.localdate(now)
    if include_simulated is None:
        include_simulated = settings.LAM_FORECAST_INCLUDE_SIMULATED
    imp_days, imp_cups = _imported(include_simulated)
    first = Shift.objects.order_by("starts_at").values_list("starts_at", flat=True).first()
    starts = ([_local_day(first)] if first else []) + ([min(imp_days)] if imp_days else [])
    end = today - timedelta(days=1)
    result = {"dates": [], "status": {}, "rows": {}, "configs": {}, "book": RecipeBook(), "today": today,
              "imported_days": set(), "stock_counts": {}}
    if not starts:
        return result
    start = max(min(starts), today - timedelta(days=days))
    if end < start:
        return result
    status = day_status(start, end, today)
    configs, as_sold = sold_configs(start, end)
    imported_days, short_days = set(), set()
    for d, st in imp_days.items():
        if not (start <= d <= end) or status.get(d) != "dong_cua" or st == "dong_cua":
            continue
        status[d] = "du_dieu_kien"
        imported_days.add(d)
        if st == "thieu_hang":
            short_days.add(d)
    dates = sorted(status)
    book = result["book"]
    at_now = now
    ingredients = list(Ingredient.objects.filter(is_active=True).values_list("pk", flat=True))
    rows = {ing: {} for ing in ingredients}

    def row(ing, d):
        return rows.setdefault(ing, {}).setdefault(d, empty_row())

    from apps.catalog.models import ItemSize

    size_item = dict(ItemSize.objects.values_list("pk", "item_id"))
    for d, by_key in configs.items():
        for (item_id, size_id, opts), cups in by_key.items():
            for ing, q in book.usage(item_id, size_id, opts, at_now).items():
                row(ing, d)["sales"] += q * cups
        for ing, q in as_sold[d].items():
            row(ing, d)["sales_as_sold"] += q
    for size_id, series in imp_cups.items():
        item_id = size_item.get(size_id)
        if item_id is None:
            continue
        per_cup = book.usage(item_id, size_id, (), at_now)
        for d, cups in series.items():
            if d in imported_days:
                configs.setdefault(d, defaultdict(int))[(item_id, size_id, ())] += cups
                for ing, q in per_cup.items():
                    row(ing, d)["sales"] += q * cups
    lo, hi = _aware(start), _aware(end + timedelta(days=1))
    for p in PostPrepCancellation.objects.filter(created_at__gte=lo, created_at__lt=hi):
        d = _local_day(p.created_at)
        for ing, q in p.usage.items():
            row(int(ing), d)["voided"] += float(q)
    for w in Waste.objects.filter(created_at__gte=lo, created_at__lt=hi):
        r = row(w.ingredient_id, _local_day(w.created_at))
        if w.reason in STOCK_LOSS:
            r["waste_stock"] += float(w.quantity)
        elif w.is_one_off:
            r["waste_one_off"] += float(w.quantity)
        else:
            r["waste_operational"] += float(w.quantity)
    open_h, close_h = params.get("open_hour"), params.get("close_hour")
    for m in StockMovement.objects.filter(created_at__gte=lo, created_at__lt=hi,
                                          kind__in=["pha_che", "kiem_ke", "nhap_hang", "hao_hut"]).order_by("id"):
        d = _local_day(m.created_at)
        r = row(m.ingredient_id, d)
        if m.kind == "pha_che":
            r["consumed_ledger"] -= float(m.quantity)
        elif m.kind == "kiem_ke":
            r["count_adjust"] += float(m.quantity)
        hour = timezone.localtime(m.created_at).hour
        if m.balance_after <= 0 and m.quantity < 0 and open_h <= hour < close_h:
            r["own_stockout"] = True  # tồn về 0 trong giờ mở cửa
    own = defaultdict(set)
    for c in ShortageCase.objects.filter(day__gte=start, day__lte=end):
        own[c.ingredient_id].add(c.day)
    for q in QuickReport.objects.filter(level=QuickReport.Level.OUT, created_at__gte=lo, created_at__lt=hi):
        own[q.ingredient_id].add(_local_day(q.created_at))
    for ing in rows:
        for d, r in rows[ing].items():
            if r["own_stockout"]:
                own[ing].add(d)
    for ing, ds in own.items():
        for d in ds:
            row(ing, d)["own_stockout"] = True
    for d in short_days:  # ngày tệp ghi thiếu hàng: số bán của cả quán bị giới hạn
        for ing in rows:
            row(ing, d)["own_stockout"] = True
    _indirect(rows, own, configs, book, at_now, today)
    counts = defaultdict(list)
    for c in StockCount.objects.filter(status="da_ap_dung").order_by("created_at"):
        counts[c.ingredient_id].append((_local_day(c.created_at), float(c.difference)))
    result.update(dates=dates, status=status, rows=rows, configs=configs, imported_days=imported_days,
                  stock_counts=counts, start=start, end=end)
    return result


def _indirect(rows, own, configs, book, at, today):
    """Ngày nguyên liệu I bị chặn gián tiếp: món dùng nguyên liệu J đang thiếu bị ngừng bán và các món đó chiếm từ
    20% tiêu hao thường lệ của I (mục 5.5)."""
    if not own:
        return
    threshold = params.get("plan_indirect_share_percent") / 100
    recent = [d for d in configs if d >= today - timedelta(days=WINDOW)]
    share = defaultdict(lambda: defaultdict(float))  # ing -> item -> lượng
    items = set()
    for d in recent:
        for (item_id, size_id, opts), cups in configs[d].items():
            items.add(item_id)
            for ing, q in book.usage(item_id, size_id, opts, at).items():
                share[ing][item_id] += q * cups
    users = {j: book.items_using(items, j, at) for j in own}
    for ing, by_item in share.items():
        total = sum(by_item.values())
        if total <= 0:
            continue
        for j, days in own.items():
            if j == ing:
                continue
            blocked = sum(by_item.get(item, 0.0) for item in users[j]) / total
            if blocked >= threshold:
                for d in days:
                    rows.setdefault(ing, {}).setdefault(d, empty_row())["indirect_block"] = True


def series_for(data, ingredient_id):
    """[(ngày, giá trị U b hoặc None, trạng thái)] liên tục theo lịch; trạng thái 'ok', 'dong_cua', 'bo_qua'.

    Ngày đóng cửa không học; ngày chưa chốt, hết hàng, bị chặn gián tiếp bị bỏ qua khi học và đo sai số."""
    rows = data["rows"].get(ingredient_id, {})
    out = []
    for d in data["dates"]:
        st = data["status"].get(d)
        r = rows.get(d)
        if st == "dong_cua":
            out.append((d, None, "dong_cua"))
        elif st != "du_dieu_kien" or (r and (r["own_stockout"] or r["indirect_block"])):
            out.append((d, None, "bo_qua"))
        else:
            out.append((d, r["sales"] if r else 0.0, "ok"))
    return out


def rates(data, ingredient_id):
    """Tỷ lệ cộng vào nhu cầu và các chỉ số, trên 8 tuần gần nhất (mục 5.3), kèm đối soát với sổ kho."""
    today = data["today"]
    lo = today - timedelta(days=WINDOW)
    rows = data["rows"].get(ingredient_id, {})
    finalized = {d for d, st in data["status"].items() if st == "du_dieu_kien" and d >= lo}
    sums = defaultdict(float)
    for d, r in rows.items():
        if d not in finalized:
            continue
        for k in ("sales", "sales_as_sold", "voided", "waste_operational", "waste_one_off", "waste_stock",
                  "consumed_ledger"):
            sums[k] += r[k]
    ub = sums["sales"]
    r_h = sums["voided"] / ub if ub > 0 else 0.0
    r_vh = sums["waste_operational"] / ub if ub > 0 else 0.0
    r_k, run = 0.0, []
    for day, diff in data["stock_counts"].get(ingredient_id, []):
        run = run + [(day, diff)] if diff < 0 else []
    if len(run) >= 4:
        first = run[0][0]
        base = sum(r["sales"] for d, r in rows.items() if first <= d <= run[-1][0])
        r_k = -sum(x for _, x in run) / base if base > 0 else 0.0
    system_days = {d for d in finalized if d not in data["imported_days"]}
    sold = sum(rows[d]["sales_as_sold"] + rows[d]["voided"] for d in system_days if d in rows)
    ledger = sum(rows[d]["consumed_ledger"] for d in system_days if d in rows)
    gap = abs(sold - ledger) / ledger if ledger > 0 else (0.0 if sold == 0 else 1.0)
    open_days = [d for d in finalized]
    blocked = sum(1 for d in open_days if d in rows and (rows[d]["own_stockout"] or rows[d]["indirect_block"]))
    return {"r_h": round(r_h, 4), "r_vh": round(r_vh, 4), "r_k": round(r_k, 4),
            "factor": round(1 + r_h + r_vh + r_k, 4), "ub_8w": round(ub, 2),
            "waste_stock_8w": round(sums["waste_stock"], 2), "waste_one_off_8w": round(sums["waste_one_off"], 2),
            "recon": {"sold_plus_voided": round(sold, 2), "ledger": round(ledger, 2), "gap": round(gap, 4),
                      "flag": gap > params.get("plan_reconcile_gap_permille") / 1000 and (sold > 0 or ledger > 0)},
            "blocked_share": round(blocked / len(open_days), 3) if open_days else 0.0,
            "blocked_days": blocked}


def recipe_ratio(data, ingredient_id, future_days, now):
    """{ngày: hệ số} cho ngày tương lai có phiên bản định mức khác bản hiện hành: lượng của 8 tuần gần nhất tính lại theo
    định mức của ngày đó chia lượng theo định mức hiện hành (đổi định mức có hiệu lực ngay từ ngày hẹn)."""
    configs, book, today = data["configs"], data["book"], data["today"]
    recent = [d for d in configs if d >= today - timedelta(days=WINDOW)]
    agg = defaultdict(int)
    for d in recent:
        for key, cups in configs[d].items():
            agg[key] += cups
    if not agg:
        return {}

    def total(at):
        return sum(book.usage(item, size, opts, at).get(ingredient_id, 0.0) * cups
                   for (item, size, opts), cups in agg.items())

    base = total(now)
    out = {}
    tz = timezone.get_current_timezone()
    for d in future_days:
        at = timezone.make_aware(datetime.combine(d, time(12)), tz)
        if at <= now:
            continue
        versions = {item: book.version(item, at) for item, _, _ in agg}
        if all(versions[item] == book.version(item, now) for item in versions):
            continue
        out[d] = (total(at) / base) if base > 0 else 1.0
    return out


def save(data):
    """Lưu chuỗi tiêu hao vào bảng lưu sẵn để xem lại và đối soát (ghi đè theo nguyên liệu và ngày)."""
    from .models import IngredientDailyUsage

    objs = []
    for ing, by_day in data["rows"].items():
        for d in data["dates"]:
            r = by_day.get(d)
            st = data["status"].get(d)
            if r is None and st != "du_dieu_kien":
                continue
            r = r or empty_row()
            objs.append(IngredientDailyUsage(
                ingredient_id=ing, date=d, day_status=st,
                source="tep" if d in data["imported_days"] else "he_thong",
                eligible=st == "du_dieu_kien" and not r["own_stockout"] and not r["indirect_block"],
                **{k: v for k, v in r.items()}))
    fields = ["source", "day_status", "sales", "sales_as_sold", "voided", "waste_operational", "waste_one_off",
              "waste_stock", "count_adjust", "consumed_ledger", "own_stockout", "indirect_block", "eligible"]
    IngredientDailyUsage.objects.bulk_create(objs, batch_size=500, update_conflicts=True,
                                             unique_fields=["ingredient", "date"], update_fields=fields)
    return len(objs)
