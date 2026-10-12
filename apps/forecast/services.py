"""Dự báo nhu cầu, quy đổi nguyên vật liệu, cảnh báo Cần đặt hàng và đề xuất số lượng (FR-28, FR-29, FR-31).

Theo khung lý thuyết của dự án (12/10/2026):
- Đơn vị phân tích: số ly của một món-kích cỡ trong một ngày kinh doanh (mục 2.2).
- Ngày đủ điều kiện: đã qua, có ca và mọi ca của ngày đã kết và có báo cáo cuối ca. Ngày đóng cửa (không có ca)
  hoặc dữ liệu chưa chốt không được coi là ngày bán 0 ly. Ngày có trường hợp thiếu nguyên liệu dùng cho món bị gắn
  cờ giới hạn nguồn cung và không đưa vào cập nhật của món đó (mục 2.2).
- Mỗi lần phát hành tính lại từ tiên nghiệm gốc trên toàn bộ ngày đủ điều kiện, nên nhập bù làm đổi ngày cũ không
  bị cộng hai lần (mục 3.2).
- Tổng nhu cầu nhiều ngày tính trên từng đường mô phỏng rồi mới lấy phân vị (mục 4.2).
"""

import hashlib
import math
from collections import defaultdict
from datetime import datetime, time, timedelta
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal

from django.db import transaction
from django.utils import timezone

from apps.core import params

from . import dglm
from .models import DayType, ExpertJudgement, ForecastRelease, IngredientForecast, MethodDecision, SeriesForecast

MODEL_VERSION = "poisson-dglm-1"


def _day_type(day):
    return DayType.WEEKEND if day.weekday() >= 5 else DayType.WEEKDAY


def _local_day(dt):
    return timezone.localtime(dt).date()


# ---------------- dữ liệu quan sát ----------------

def day_status(start, end, today=None):
    """{ngày: 'du_dieu_kien' | 'dong_cua' | 'chua_chot'} cho các ngày từ start đến end."""
    from apps.shifts.models import Shift

    today = today or timezone.localdate()
    shifts = defaultdict(list)
    tz = timezone.get_current_timezone()
    lo = timezone.make_aware(datetime.combine(start, time.min), tz)
    hi = timezone.make_aware(datetime.combine(end + timedelta(days=1), time.min), tz)
    for s in Shift.objects.filter(starts_at__gte=lo, starts_at__lt=hi).select_related("report"):
        shifts[_local_day(s.starts_at)].append(s)
    out = {}
    d = start
    while d <= end:
        day_shifts = shifts.get(d, [])
        if not day_shifts:
            out[d] = "dong_cua"
        elif d >= today or any(s.status != Shift.Status.CLOSED or not hasattr(s, "report") for s in day_shifts):
            out[d] = "chua_chot"
        else:
            out[d] = "du_dieu_kien"
        d += timedelta(days=1)
    return out


def cups_by_day(start, end):
    """{size_id: {ngày bán: số ly tính tiền}}; ngày bán của phiếu dự phòng là thời điểm bán ghi trên phiếu."""
    from apps.orders.models import OrderLine

    tz = timezone.get_current_timezone()
    lo = timezone.make_aware(datetime.combine(start - timedelta(days=2), time.min), tz)
    hi = timezone.make_aware(datetime.combine(end + timedelta(days=1), time.min), tz)
    out = defaultdict(lambda: defaultdict(int))
    lines = (OrderLine.objects.filter(order__created_at__gte=lo, order__created_at__lt=hi + timedelta(days=2))
             .select_related("order", "order__backup_slip"))
    for line in lines:
        slip = getattr(line.order, "backup_slip", None)
        sold = slip.sold_at if slip is not None and slip.sold_at else line.order.created_at
        day = _local_day(sold)
        if start <= day <= end and line.billable_quantity > 0:
            out[line.size_id][day] += line.billable_quantity
    return out


def option_counts(start, end):
    """{item_id: (số ly, {option_id: số ly có tùy chọn})} để ước tính tỷ lệ chọn tùy chọn."""
    from apps.orders.models import OrderLine

    tz = timezone.get_current_timezone()
    lo = timezone.make_aware(datetime.combine(start, time.min), tz)
    hi = timezone.make_aware(datetime.combine(end + timedelta(days=1), time.min), tz)
    totals, chosen = defaultdict(int), defaultdict(lambda: defaultdict(int))
    for line in OrderLine.objects.filter(order__created_at__gte=lo, order__created_at__lt=hi).prefetch_related("options"):
        cups = line.billable_quantity
        if cups <= 0:
            continue
        totals[line.item_id] += cups
        for o in line.options.all():
            chosen[line.item_id][o.option_id] += cups
    return {item: (n, dict(chosen[item])) for item, n in totals.items()}


def shortage_flags(start, end):
    """{size_id: {ngày}}: ngày có trường hợp thiếu một nguyên liệu nằm trong định mức của kích cỡ đó."""
    from apps.inventory.models import RecipeLine, ShortageCase

    by_ing = defaultdict(set)
    for case in ShortageCase.objects.filter(day__gte=start, day__lte=end):
        by_ing[case.ingredient_id].add(case.day)
    out = defaultdict(set)
    if not by_ing:
        return out
    for line in RecipeLine.objects.filter(ingredient_id__in=by_ing, version__status="ap_dung").select_related("size"):
        if line.size_id:
            out[line.size_id] |= by_ing[line.ingredient_id]
    return out


def history(today=None, days=None):
    """Chuỗi quan sát của mọi món-kích cỡ: (danh sách ngày theo thứ tự, trạng thái ngày, số ly, cờ thiếu hàng)."""
    from apps.shifts.models import Shift

    today = today or timezone.localdate()
    first = Shift.objects.order_by("starts_at").values_list("starts_at", flat=True).first()
    if first is None:
        return [], {}, {}, {}
    start = _local_day(first)
    if days:
        start = max(start, today - timedelta(days=days))
    end = today - timedelta(days=1)
    if end < start:
        return [], {}, {}, {}
    status = day_status(start, end, today)
    dates = sorted(status)
    return dates, status, cups_by_day(start, end), shortage_flags(start, end)


# ---------------- tiên nghiệm ----------------

def current_judgements():
    """{(size_id, loại ngày): nhận định đang dùng}; bỏ qua nhận định dựa trên chính lịch sử hệ thống (mục 6.1)."""
    out = {}
    for j in ExpertJudgement.objects.filter(superseded_at__isnull=True).order_by("created_at"):
        out[(j.size_id, j.day_type)] = j
    return out


def prior_for(size_id, judgements, max_days):
    """Tiên nghiệm Gamma cho ngày thường và cuối tuần, kèm thông tin để công bố."""
    wd = judgements.get((size_id, DayType.WEEKDAY))
    we = judgements.get((size_id, DayType.WEEKEND))
    if wd is None and we is None:
        return None
    wd, we = wd or we, we or wd
    gwd = dglm.gamma_from_judgement(wd.typical, wd.low, wd.high, max_days)
    gwe = dglm.gamma_from_judgement(we.typical, we.low, we.high, max_days)
    return {"weekday": gwd[:2], "weekend": gwe[:2], "days": min(gwd[2], gwe[2]), "capped": gwd[3] or gwe[3],
            "independent": not (wd.based_on_system_history or we.based_on_system_history)}


VAGUE = (0.5, 0.05)  # Gamma(0.5, 0.05): trung bình 10 ly, rất rộng; chỉ dùng khi chưa có nhận định Chủ quán


def fit(series, dates, status, flags, prior, delta_level, delta_season, until=None):
    """Học tuần tự trên các ngày (tới trước `until`); trả mô hình và số ngày đã dùng, số ngày bị gắn cờ."""
    if prior is not None and prior["independent"]:
        m, C = dglm.prior_state(prior["weekday"], prior["weekend"])
    else:
        m, C = dglm.prior_state(VAGUE, VAGUE)
    model = dglm.PoissonDGLM(m, C, delta_level, delta_season)
    used = flagged = 0
    for d in dates:
        if until is not None and d >= until:
            break
        if status.get(d) == "du_dieu_kien" and d not in flags:
            model.update(series.get(d, 0), d.weekday())
            used += 1
        else:
            flagged += 1 if (status.get(d) == "du_dieu_kien" and d in flags) else 0
            model.skip()
    return model, used, flagged


# ---------------- phát hành ----------------

def _sizes():
    from apps.catalog.models import ItemSize, MenuItem

    return list(ItemSize.objects.filter(is_active=True, item__status=MenuItem.Status.ON_SALE)
                .select_related("item").order_by("item__name", "sort_order"))


def method_for(size_id, has_prior=True):
    """Cách tính dùng cho đặt hàng: theo quyết định gần nhất của Chủ quán, mặc định Ước tính ban đầu.
    Chưa có nhận định thì không có ước tính ban đầu, nên dùng mô hình (bắt đầu từ tiên nghiệm rộng)."""
    d = MethodDecision.objects.filter(size_id=size_id).order_by("-created_at").first()
    method = d.method if d else MethodDecision.Method.OWNER
    if method == MethodDecision.Method.OWNER and not has_prior:
        return MethodDecision.Method.MODEL
    return method


def _summ(values):
    s = sorted(values)
    n = len(s)
    return {"mean": round(sum(s) / n, 2) if n else 0, "q10": dglm.quantile(s, 0.1), "q50": dglm.quantile(s, 0.5),
            "q90": dglm.quantile(s, 0.9)}


def _owner_paths(prior, dows, n, rng):
    """Đường mô phỏng theo nhận định: mỗi đường rút một cường độ cho từng loại ngày rồi rút số ly mỗi ngày."""
    paths = []
    for _ in range(n):
        lam = {False: rng.gammavariate(prior["weekday"][0], 1 / prior["weekday"][1]),
               True: rng.gammavariate(prior["weekend"][0], 1 / prior["weekend"][1])}
        paths.append([dglm.poisson(lam[d >= 5], rng) for d in dows])
    return paths


def required_horizon():
    from apps.inventory.models import Ingredient

    h = params.get("forecast_horizon_days")
    for ing in Ingredient.objects.filter(is_active=True):
        span = ing.lead_time_days + max(ing.order_cycle_days or 0, ing.shelf_life_days or 0) + 1
        h = max(h, span)
    return min(h, 60)


@transaction.atomic
def release(user=None, now=None):
    """Phát hành dự báo mới cho mọi món đang bán; lưu nguyên để đánh giá sau (mục 6.1)."""
    now = now or timezone.now()
    today = timezone.localdate(now)
    horizon = required_horizon()
    dl = params.get("forecast_delta_level_percent") / 100
    ds = params.get("forecast_delta_season_percent") / 100
    max_days = params.get("forecast_prior_max_days")
    n_paths = params.get("forecast_paths")
    min_history = params.get("forecast_min_history_days")
    dates, status, cups, flags = history(today)
    judgements = current_judgements()
    days_ahead = [today + timedelta(days=k) for k in range(horizon)]
    dows = [d.weekday() for d in days_ahead]
    digest = hashlib.sha256()
    for d in dates:
        digest.update(f"{d}:{status[d]};".encode())
    for size_id in sorted(cups):
        for d in sorted(cups[size_id]):
            digest.update(f"{size_id}:{d}:{cups[size_id][d]};".encode())
    rel = ForecastRelease.objects.create(
        issued_at=now, first_day=today, horizon_days=horizon, model_version=MODEL_VERSION,
        data_version=digest.hexdigest(), issued_by=user,
        parameters={"delta_level": dl, "delta_season": ds, "prior_max_days": max_days, "paths": n_paths})
    size_paths = {}
    for size in _sizes():
        prior = prior_for(size.pk, judgements, max_days)
        method = method_for(size.pk, has_prior=prior is not None)
        series = cups.get(size.pk, {})
        model, used, flagged = fit(series, dates, status, flags.get(size.pk, set()), prior, dl, ds)
        limitations = []
        if prior is None:
            limitations.append("Chưa có nhận định của Chủ quán; mô hình bắt đầu từ tiên nghiệm rất rộng.")
        elif not prior["independent"]:
            limitations.append("Nhận định dựa trên chính số bán trong hệ thống nên không dùng làm tiên nghiệm độc lập.")
        if prior and prior["capped"]:
            limitations.append(f"Khoảng của nhận định rất hẹp; sức nặng bị giới hạn ở {max_days} ngày tương đương.")
        if used < min_history:
            limitations.append(f"Mới có {used} ngày dữ liệu đủ điều kiện (mốc đánh giá thử là {min_history} ngày).")
        if flagged:
            limitations.append(f"{flagged} ngày bị loại vì thiếu nguyên liệu; số bán ngày đó không phản ánh đủ nhu cầu.")
        model_days = model.ahead(dows)
        daily = []
        for d, (a, b) in zip(days_ahead, model_days):
            mean, (q10, q50, q90) = dglm.nb_summary(a, b)
            row = {"date": d.isoformat(), "mean": round(mean, 2), "q10": q10, "q50": q50, "q90": q90}
            if prior is not None:
                pa, pb = prior["weekend"] if d.weekday() >= 5 else prior["weekday"]
                pm, (p10, p50, p90) = dglm.nb_summary(pa, pb)
                row["owner"] = {"mean": round(pm, 2), "q10": p10, "q50": p50, "q90": p90}
            daily.append(row)
        rng = dglm.make_rng(rel.data_version, size.pk, today)
        if method == MethodDecision.Method.OWNER and prior is not None:
            paths = _owner_paths(prior, dows, n_paths, rng)
        else:
            paths = model.simulate(dows, n_paths, rng)
        size_paths[size.pk] = paths
        totals = {str(k): _summ([sum(p[:k]) for p in paths]) for k in (1, 3, 7) if k <= horizon}
        SeriesForecast.objects.create(
            release=rel, size=size, method=method, eligible_days=used, flagged_days=flagged,
            prior_days=prior["days"] if prior else None, prior_capped=bool(prior and prior["capped"]),
            daily=daily, totals=totals, limitations=limitations)
    _ingredient_forecasts(rel, size_paths, today, days_ahead)
    return rel


def option_rates(today, window=56):
    """Tỷ lệ chọn từng tùy chọn của mỗi món: trung bình hậu nghiệm Beta(1, 1) trên các ly đã bán gần đây."""
    rates = {}
    for item, (n, chosen) in option_counts(today - timedelta(days=window), today - timedelta(days=1)).items():
        rates[item] = {opt: (x + 1) / (n + 2) for opt, x in chosen.items()}
    return rates


def _recipe_usage(sizes):
    """Lượng nguyên liệu mỗi ly theo kích cỡ và mỗi lần chọn tùy chọn, theo phiên bản định mức đang áp dụng."""
    from apps.inventory.models import RecipeVersion

    per_size, per_option = defaultdict(dict), defaultdict(lambda: defaultdict(dict))
    for size in sizes:
        version = RecipeVersion.objects.current_for(size.item)
        if version is None:
            continue
        for line in version.lines.all():
            if line.size_id == size.pk:
                per_size[size.pk][line.ingredient_id] = per_size[size.pk].get(line.ingredient_id, 0) + float(line.quantity)
            elif line.option_id:
                per_option[size.item_id][line.option_id][line.ingredient_id] = float(line.quantity)
    return per_size, per_option


def _ingredient_forecasts(rel, size_paths, today, days_ahead):
    from apps.catalog.models import ItemSize

    sizes = {s.pk: s for s in ItemSize.objects.filter(pk__in=size_paths).select_related("item")}
    per_size, per_option = _recipe_usage(sizes.values())
    rates = option_rates(today)
    methods = {s.size_id: s.method for s in rel.series.all()}
    n = len(next(iter(size_paths.values()))) if size_paths else 0
    horizon = len(days_ahead)
    demand = defaultdict(lambda: [[0.0] * horizon for _ in range(n)])
    contributors = defaultdict(dict)
    for size_id, paths in size_paths.items():
        size = sizes[size_id]
        usage = dict(per_size.get(size_id, {}))
        for opt, ings in per_option.get(size.item_id, {}).items():
            rate = rates.get(size.item_id, {}).get(opt, 0.0)
            for ing, qty in ings.items():
                usage[ing] = usage.get(ing, 0.0) + rate * qty
        for ing, qty in usage.items():
            if qty <= 0:
                continue
            contributors[ing][f"{size.item.name} {size.name}"] = methods.get(size_id)
            target = demand[ing]
            for i, path in enumerate(paths):
                row = target[i]
                for t, c in enumerate(path):
                    row[t] += c * qty
    for ing, paths in demand.items():
        daily = []
        for t, d in enumerate(days_ahead):
            s = _summ([p[t] for p in paths])
            daily.append({"date": d.isoformat(), "mean": round(s["mean"], 2), "q10": round(s["q10"], 2),
                          "q90": round(s["q90"], 2)})
        cumulative = []
        for p in paths[:400]:  # mẫu đường để tính phân vị nhu cầu trong thời gian giao (giữ phụ thuộc giữa các ngày)
            acc, row = 0.0, []
            for v in p:
                acc += v
                row.append(round(acc, 2))
            cumulative.append(row)
        IngredientForecast.objects.create(release=rel, ingredient_id=ing, daily=daily, paths_sample=cumulative,
                                          methods=contributors[ing])


def latest_release():
    return ForecastRelease.objects.order_by("-issued_at").first()


def ensure_today_release(now=None):
    """Tác vụ định kỳ: mỗi ngày phát hành một lần (sau khi dữ liệu ngày hôm trước đã chốt)."""
    now = now or timezone.now()
    rel = latest_release()
    if rel is None or rel.first_day < timezone.localdate(now):
        return release(now=now)
    return None


# ---------------- đặt hàng (BRU-22, BRU-24) ----------------

def _remaining_today_fraction(now):
    open_h, close_h = params.get("open_hour"), params.get("close_hour")
    local = timezone.localtime(now)
    hour = local.hour + local.minute / 60
    if hour <= open_h:
        return 1.0
    if hour >= close_h:
        return 0.0
    return (close_h - hour) / (close_h - open_h)


def ordering_status(ingredient, rel=None, now=None):
    """Tồn dự kiến khi hàng về, cần đặt hay không, ngày đặt muộn nhất và đề xuất số lượng, kèm thành phần phép tính."""
    from apps.inventory.models import PurchaseOrder

    now = now or timezone.now()
    today = timezone.localdate(now)
    rel = rel or latest_release()
    fc = rel and IngredientForecast.objects.filter(release=rel, ingredient=ingredient).first()
    stock = getattr(ingredient, "stock", None)
    available = float(stock.available) if stock else 0.0
    safety = float(ingredient.safety_stock)
    lead = ingredient.lead_time_days
    result = {"ingredient": ingredient, "available": available, "safety": safety, "lead": lead,
              "has_forecast": bool(fc), "release": rel}
    if not fc:
        return result
    offset = (today - rel.first_day).days
    daily = [row["mean"] for row in fc.daily[offset:]] if offset >= 0 else [row["mean"] for row in fc.daily]
    if daily:
        daily[0] *= _remaining_today_fraction(now)
    incoming = [(po.expected_date, float(po.remaining)) for po in
                PurchaseOrder.objects.filter(ingredient=ingredient).exclude(status=PurchaseOrder.Status.DELIVERED)
                if po.counts_as_incoming]

    def demand(days):
        return sum(daily[:days]) if days <= len(daily) else None

    def projected(k):
        arrive = today + timedelta(days=k + lead)
        lots = sum(q for d, q in incoming if d <= arrive)
        need = demand(k + lead)  # nhu cầu từ hôm nay đến trước ngày hàng về
        return None if need is None else available + lots - need, lots, need

    p0, lots0, need0 = projected(0)
    result.update({"incoming": incoming, "lots_by_arrival": lots0, "lead_demand": need0, "projected": p0,
                   "need_order": p0 is not None and p0 < safety, "daily": daily})
    latest = None
    for k in range(0, len(daily)):
        pk = projected(k)[0]
        if pk is None:
            break
        if pk >= safety:
            latest = today + timedelta(days=k)
        else:
            break
    result["latest_order_date"] = today if result["need_order"] else latest
    # Khoảng 80% của nhu cầu trong thời gian giao, từ đường mô phỏng (thông tin thêm, không thay quy tắc BRU-22)
    idx = lead + offset
    if fc.paths_sample and idx < len(fc.paths_sample[0]):
        base = [p[offset - 1] if offset > 0 else 0 for p in fc.paths_sample]
        vals = sorted(p[idx] - b for p, b in zip(fc.paths_sample, base))
        result["lead_demand_q90"] = dglm.quantile(vals, 0.9)
    result["suggestion"] = suggestion(ingredient, daily, p0, safety, lead)
    return result


def _round_up(qty, pack):
    if pack <= 0:
        return qty
    return float((Decimal(str(qty)) / Decimal(str(pack))).to_integral_value(ROUND_CEILING) * Decimal(str(pack)))


def suggestion(ingredient, daily, projected, safety, lead):
    """BRU-24: nhu cầu từ khi hàng về đến lần nhận kế tiếp + tồn an toàn − tồn dự kiến khi hàng về, làm tròn lên theo
    quy cách; không vượt nhu cầu trong thời hạn sử dụng + tồn an toàn − tồn dự kiến, không vượt sức chứa."""
    if projected is None:
        return None
    cycle = ingredient.order_cycle_days
    pack = float(ingredient.pack_size or 0)
    comp = {"cycle": cycle, "pack": pack, "projected": round(projected, 2), "safety": safety,
            "shelf": ingredient.shelf_life_days, "capacity": float(ingredient.storage_capacity or 0) or None}
    if not cycle:
        comp["missing"] = "Chưa khai báo chu kỳ đặt hàng của nguyên liệu này."
        return {"quantity": None, "components": comp}
    arrive = lead  # chỉ số ngày hàng về (hôm nay là 0)
    cycle_demand = sum(daily[arrive:arrive + cycle])
    comp["cycle_demand"] = round(cycle_demand, 2)
    base = max(cycle_demand + safety - projected, 0)
    limited_by = None
    if ingredient.shelf_life_days:
        shelf_demand = sum(daily[arrive:arrive + ingredient.shelf_life_days])
        comp["shelf_demand"] = round(shelf_demand, 2)
        cap = max(shelf_demand + safety - projected, 0)
        if cap < base:
            base, limited_by = cap, "thời hạn sử dụng"
    qty = _round_up(base, pack)
    if comp["capacity"]:
        room = max(comp["capacity"] - max(projected, 0), 0)
        if qty > room:
            qty = float((Decimal(str(room)) / Decimal(str(pack))).to_integral_value(ROUND_FLOOR) * Decimal(str(pack))) \
                if pack > 0 else room
            limited_by = "sức chứa bảo quản"
    comp["limited_by"] = limited_by
    comp["packs"] = round(qty / pack, 2) if pack > 0 else None
    return {"quantity": round(qty, 2), "components": comp}


def orders_needed(now=None):
    """Nguyên liệu đang cần đặt theo BRU-22 (dùng cho cảnh báo Cần đặt hàng)."""
    from apps.inventory.models import Ingredient

    rel = latest_release()
    if rel is None:
        return []
    out = []
    for ing in Ingredient.objects.filter(is_active=True).select_related("stock", "main_supplier"):
        st = ordering_status(ing, rel, now)
        if st.get("need_order"):
            out.append(st)
    return out
