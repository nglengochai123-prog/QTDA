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
    """{size_id: {ngày}}: ngày có trường hợp thiếu một nguyên liệu nằm trong định mức của kích cỡ đó, hoặc của một tùy
    chọn của món (thiếu nguyên liệu của tùy chọn cũng giới hạn số bán của mọi kích cỡ của món)."""
    from apps.catalog.models import ItemSize
    from apps.inventory.models import RecipeLine, ShortageCase

    by_ing = defaultdict(set)
    for case in ShortageCase.objects.filter(day__gte=start, day__lte=end):
        by_ing[case.ingredient_id].add(case.day)
    out = defaultdict(set)
    if not by_ing:
        return out
    by_item = defaultdict(set)
    for line in RecipeLine.objects.filter(ingredient_id__in=by_ing, version__status="ap_dung").select_related("version"):
        if line.size_id:
            out[line.size_id] |= by_ing[line.ingredient_id]
        elif line.option_id:
            by_item[line.version.item_id] |= by_ing[line.ingredient_id]
    for size in ItemSize.objects.filter(item_id__in=by_item):
        out[size.pk] |= by_item[size.item_id]
    return out


def imported_history(include_simulated=False):
    """Lịch sử nhập từ tệp của các lần nhập đang dùng: ({ngày: trạng thái}, {size_id: {ngày: số ly}})."""
    from .models import HistoricalDay, HistoricalSale, HistoryBatch

    kinds = [HistoryBatch.Kind.REAL] + ([HistoryBatch.Kind.SIMULATED] if include_simulated else [])
    days, cups = {}, defaultdict(lambda: defaultdict(int))
    for d in HistoricalDay.objects.filter(batch__active=True, batch__kind__in=kinds):
        days[d.date] = d.status
    for row in HistoricalSale.objects.filter(batch__active=True, batch__kind__in=kinds):
        cups[row.size_id][row.date] += row.cups
        days.setdefault(row.date, "mo_cua")
    return days, cups


def history(today=None, days=None, include_simulated=None):
    """Chuỗi quan sát của mọi món-kích cỡ: (danh sách ngày theo thứ tự, trạng thái ngày, số ly, cờ thiếu hàng).

    Gộp dữ liệu hệ thống với lịch sử bán nhập từ tệp. Ngày có ca trên hệ thống dùng dữ liệu hệ thống; ngày chỉ có
    trong tệp dùng số trong tệp; ngày không có ở đâu là đóng cửa. Ngày thiếu hàng trong tệp bị gắn cờ cho mọi món.
    """
    from apps.shifts.models import Shift

    from django.conf import settings

    today = today or timezone.localdate()
    if include_simulated is None:
        include_simulated = settings.LAM_FORECAST_INCLUDE_SIMULATED
    imp_days, imp_cups = imported_history(include_simulated)
    first = Shift.objects.order_by("starts_at").values_list("starts_at", flat=True).first()
    starts = ([_local_day(first)] if first else []) + ([min(imp_days)] if imp_days else [])
    if not starts:
        return [], {}, {}, {}
    start = min(starts)
    if days:
        start = max(start, today - timedelta(days=days))
    end = today - timedelta(days=1)
    if end < start:
        return [], {}, {}, {}
    status = day_status(start, end, today)
    cups = cups_by_day(start, end)
    flags = shortage_flags(start, end)
    short_days = set()
    for d, st in imp_days.items():
        if not (start <= d <= end) or status.get(d) != "dong_cua":
            continue  # ngày đã có ca trên hệ thống: dữ liệu hệ thống được ưu tiên
        if st == "dong_cua":
            continue
        status[d] = "du_dieu_kien"
        if st == "thieu_hang":
            short_days.add(d)
        for size_id, series in imp_cups.items():
            if d in series:
                cups[size_id][d] += series[d]
    if short_days:
        for size_id in set(cups) | {sid for sid in flags}:
            flags[size_id] = set(flags.get(size_id, set())) | short_days
        flags["*"] = short_days  # áp cho món chưa có số bán trong tệp
    dates = sorted(status)
    return dates, status, cups, flags


def size_flags(flags, size_id):
    return set(flags.get(size_id, set())) | set(flags.get("*", set()))


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


def initial_model(prior, delta_level, delta_season, obs_var=0.0):
    if prior is not None and prior["independent"]:
        m, C = dglm.prior_state(prior["weekday"], prior["weekend"])
    else:
        m, C = dglm.prior_state(VAGUE, VAGUE)
    return dglm.PoissonDGLM(m, C, delta_level, delta_season, obs_var)


def fit(series, dates, status, flags, prior, delta_level, delta_season, until=None, obs_var=0.0):
    """Học tuần tự trên các ngày (tới trước `until`); trả mô hình và số ngày đã dùng, số ngày bị gắn cờ."""
    model = initial_model(prior, delta_level, delta_season, obs_var)
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


def approved_config(size_id):
    """Cấu hình mô hình đã được Chủ quán duyệt cùng quyết định dùng mô hình; chưa duyệt thì None (dùng mặc định)."""
    from .models import SeriesConfig

    cfg = SeriesConfig.objects.filter(size_id=size_id, approved_at__isnull=False).first()
    if cfg and method_for(size_id) == MethodDecision.Method.MODEL:
        return cfg
    return None


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
        cfg = approved_config(size.pk)
        s_dl, s_v = (cfg.delta_level, cfg.obs_var) if cfg else (dl, 0.0)
        model, used, flagged = fit(series, dates, status, size_flags(flags, size.pk), prior, s_dl, ds, obs_var=s_v)
        limitations = []
        if prior is None:
            limitations.append("Chưa có nhận định của Chủ quán cho món này; những ngày đầu dự báo còn rộng.")
        elif not prior["independent"]:
            limitations.append("Nhận định được lấy từ chính số bán trong hệ thống nên chỉ dùng để tham khảo.")
        if prior and prior["capped"] and used < min_history:  # đủ số bán rồi thì nhận định không còn ảnh hưởng đáng kể
            limitations.append("Nhận định của Chủ quán ghi khoảng rất hẹp; hệ thống chỉ tin ở mức vừa phải cho tới khi "
                               "có thêm số bán.")
        if used < min_history:
            limitations.append(f"Mới có {used} ngày bán dùng được; dự báo sẽ chắc hơn khi đủ {min_history} ngày.")
        if flagged:
            limitations.append(f"{flagged} ngày bị bỏ qua vì thiếu nguyên liệu; số bán ngày đó thấp hơn nhu cầu thật.")
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
        if cfg:
            limitations.append("Dùng cách tính riêng đã được Chủ quán duyệt cho món này.")
        SeriesForecast.objects.create(
            release=rel, size=size, method=method, eligible_days=used, flagged_days=flagged,
            prior_days=prior["days"] if prior else None, prior_capped=bool(prior and prior["capped"]),
            daily=daily, totals=totals, limitations=limitations)
    _ingredient_forecasts(rel, size_paths, today, days_ahead)
    return rel


def option_posteriors(today, window=56):
    """Hậu nghiệm Beta(1 + số ly có tùy chọn, 1 + số ly không có) của tỷ lệ chọn từng tùy chọn mỗi món (mục 6.2)."""
    post = {}
    for item, (n, chosen) in option_counts(today - timedelta(days=window), today - timedelta(days=1)).items():
        post[item] = {opt: (x + 1, n - x + 1) for opt, x in chosen.items()}
    return post


def option_rates(today, window=56):
    """Tỷ lệ chọn bình quân (trung bình hậu nghiệm), dùng khi chỉ cần kỳ vọng."""
    return {item: {opt: a / (a + b) for opt, (a, b) in opts.items()}
            for item, opts in option_posteriors(today, window).items()}


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
    """Nhu cầu nguyên liệu trên từng đường mô phỏng: số ly × định mức kích cỡ, cộng phần tùy chọn với tỷ lệ chọn rút
    từ hậu nghiệm Beta cho mỗi đường và số ly có tùy chọn xấp xỉ nhị thức (mục 6.2: tùy chọn có tỷ lệ riêng)."""
    from apps.catalog.models import ItemSize

    sizes = {s.pk: s for s in ItemSize.objects.filter(pk__in=size_paths).select_related("item")}
    per_size, per_option = _recipe_usage(sizes.values())
    post = option_posteriors(today)
    methods = {s.size_id: s.method for s in rel.series.all()}
    n = len(next(iter(size_paths.values()))) if size_paths else 0
    horizon = len(days_ahead)
    demand = defaultdict(lambda: [[0.0] * horizon for _ in range(n)])
    contributors = defaultdict(dict)
    rng = dglm.make_rng(rel.data_version, "tuy-chon")
    for size_id, paths in size_paths.items():
        size = sizes[size_id]
        label = f"{size.item.name} {size.name}"
        for ing, qty in per_size.get(size_id, {}).items():
            contributors[ing][label] = methods.get(size_id)
            rows = demand[ing]
            for i, path in enumerate(paths):
                row = rows[i]
                for t, c in enumerate(path):
                    row[t] += c * qty
        for opt, ings in per_option.get(size.item_id, {}).items():
            if opt not in post.get(size.item_id, {}):
                continue  # chưa từng bán kèm tùy chọn này: không cộng
            a, b = post[size.item_id][opt]
            for ing in ings:
                contributors[ing][label] = methods.get(size_id)
            for i, path in enumerate(paths):
                p = rng.betavariate(a, b)
                for t, c in enumerate(path):
                    if c <= 0:
                        continue
                    k = c * p + rng.gauss(0, math.sqrt(max(c * p * (1 - p), 0)))
                    k = min(max(round(k), 0), c)
                    if k:
                        for ing, q in ings.items():
                            demand[ing][i][t] += k * q
    for ing, paths in demand.items():
        daily = []
        for t, d in enumerate(days_ahead):
            st = _summ([p[t] for p in paths])
            daily.append({"date": d.isoformat(), "mean": round(st["mean"], 2), "q10": round(st["q10"], 2),
                          "q90": round(st["q90"], 2)})
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
    """Phần nhu cầu hôm nay còn lại: tổng tỷ lệ bán của các giờ còn lại trong lịch sử 8 tuần; thiếu dữ liệu theo giờ
    thì chia đều theo giờ mở cửa."""
    from apps.schedule.services import _hourly_profile

    local = timezone.localtime(now)
    share = _hourly_profile(local.date())[0].get(local.weekday() >= 5, {})
    if share:
        frac_hour = 1 - local.minute / 60
        return min(1.0, share.get(local.hour, 0) * frac_hour + sum(v for h, v in share.items() if h > local.hour))
    open_h, close_h = params.get("open_hour"), params.get("close_hour")
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
    idx = lead + offset - 1  # cùng cửa sổ với cột kỳ vọng: từ hôm nay, đủ `lead` ngày
    if lead > 0 and fc.paths_sample and idx < len(fc.paths_sample[0]):
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


# ---------------- kiểm tra nhận định bằng kịch bản (mục 6.1) ----------------

def prior_check(size_id, n=2000):
    """Sinh các tuần bán hàng theo nhận định để Chủ quán đối chiếu tính hợp lý trước khi dùng."""
    prior = prior_for(size_id, current_judgements(), params.get("forecast_prior_max_days"))
    if prior is None:
        return None
    rng = dglm.make_rng("kiem-tra", size_id)
    paths = _owner_paths(prior, list(range(7)), n, rng)
    weekday = sorted(v for p in paths for v in p[:5])
    weekend = sorted(v for p in paths for v in p[5:])
    week = sorted(sum(p) for p in paths)
    peak = sorted(max(p) for p in paths)
    q = dglm.quantile
    return {"weekday": (q(weekday, 0.1), q(weekday, 0.9)), "weekend": (q(weekend, 0.1), q(weekend, 0.9)),
            "week": (q(week, 0.1), q(week, 0.5), q(week, 0.9)), "peak95": q(peak, 0.95),
            "days": round(prior["days"], 1), "capped": prior["capped"]}


# ---------------- đối chiếu các lần phát hành đã lưu (mục 6.1) ----------------

BUCKETS = [(1, 1, "1 ngày"), (2, 3, "2–3 ngày"), (4, 7, "4–7 ngày"), (8, 60, "8 ngày trở lên")]


def release_accuracy(today=None, lookback=56):
    """So dự báo đã phát hành (giữ nguyên) với số bán thực trên ngày đủ điều kiện, theo thời hạn và theo món.

    Số bán thực lấy theo dữ liệu hiện tại, đã gồm nhập bù muộn; số điểm có nhập bù sau thời điểm phát hành được đếm
    riêng để phân biệt kết quả ban đầu với kết quả sau điều chỉnh."""
    from apps.catalog.models import ItemSize
    from apps.orders.models import BackupSlip

    today = today or timezone.localdate()
    dates, status, cups, flags = history(today)
    late = defaultdict(set)
    for slip in BackupSlip.objects.filter(sold_at__isnull=False, order__isnull=False).select_related("order"):
        late[_local_day(slip.sold_at)].add(slip.order.created_at)
    points = []  # (size_id, h, row, y)
    revised = 0
    for rel in ForecastRelease.objects.filter(first_day__gte=today - timedelta(days=lookback)):
        for s in rel.series.all():
            fl = size_flags(flags, s.size_id)
            for row in s.daily:
                d = datetime.fromisoformat(row["date"]).date()
                if d >= today or status.get(d) != "du_dieu_kien" or d in fl:
                    continue
                y = cups.get(s.size_id, {}).get(d, 0)
                if any(t > rel.issued_at for t in late.get(d, ())):
                    revised += 1
                points.append((s.size_id, (d - rel.first_day).days + 1, row, y))

    def agg(pts):
        n = len(pts)
        return {"n": n, "mae": round(sum(abs(r["q50"] - y) for r, y in pts) / n, 2),
                "bias": round(sum(r["q50"] - y for r, y in pts) / n, 2),
                "coverage": round(100 * sum(r["q10"] <= y <= r["q90"] for r, y in pts) / n)}

    buckets = []
    for lo, hi, label in BUCKETS:
        pts = [(r, y) for _, h, r, y in points if lo <= h <= hi]
        if pts:
            buckets.append({"label": label, **agg(pts)})
    labels = {s.pk: f"{s.item.name} {s.name}" for s in ItemSize.objects.select_related("item")}
    per_size = defaultdict(list)
    for sid, h, r, y in points:
        if h == 1:
            per_size[sid].append((r, y))
    sizes = sorted(({"label": labels.get(sid, sid), **agg(pts)} for sid, pts in per_size.items()),
                   key=lambda x: str(x["label"]))
    return {"buckets": buckets, "sizes": sizes, "revised": revised, "points": len(points)}


# ---------------- nhập lịch sử bán từ tệp ----------------

HEADERS = {
    "date": ("ngay", "ngày", "date", "thoi_gian", "thời gian", "ngay_ban", "ngày bán", "created_at", "time"),
    "item": ("mon", "món", "ten_mon", "tên món", "item", "san_pham", "sản phẩm", "product"),
    "size": ("kich_co", "kích cỡ", "size", "co", "cỡ"),
    "qty": ("so_ly", "số ly", "so_luong", "số lượng", "qty", "quantity", "sl"),
    "status": ("trang_thai", "trạng thái", "tinh_trang", "tình trạng", "status"),
}
STATUS_WORDS = {"dong_cua": ("đóng cửa", "dong cua", "dong_cua", "nghỉ", "nghi", "closed"),
                "thieu_hang": ("thiếu hàng", "thieu hang", "thieu_hang", "hết hàng", "het hang", "stockout")}
DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%d/%m/%Y %H:%M",
                "%d/%m/%Y %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M")


def _parse_day(value):
    value = (value or "").strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        pass
    from apps.core.xlsx_read import excel_date

    if value.replace(".", "", 1).isdigit():
        return excel_date(value)  # ô ngày trong Excel lưu dạng số ngày
    return None


@transaction.atomic
def import_history(fileobj, file_name, kind, user, note=""):
    """Nhập lịch sử bán dạng CSV (mỗi dòng là một món của một đơn, hoặc tổng một ngày); gộp theo ngày và món-kích cỡ.

    Cột nhận theo tên (ngày, món, kích cỡ, số ly, trạng thái). Dòng có trạng thái đóng cửa hoặc thiếu hàng đánh dấu
    cả ngày. Món không khớp tên trong thực đơn được liệt kê, không đoán."""
    import csv
    import io
    import unicodedata

    from apps.audit.models import Action
    from apps.audit.services import record
    from apps.catalog.models import ItemSize

    from .models import HistoricalDay, HistoricalSale, HistoryBatch

    raw = fileobj.read()

    def norm(x):
        return unicodedata.normalize("NFC", (x or "").strip().lower())

    def columns(header):
        cols = {}
        for key, names in HEADERS.items():
            for i, h in enumerate(header):
                if norm(h) in names:
                    cols[key] = i
                    break
        return cols

    sheet_name = ""
    if isinstance(raw, bytes) and raw[:2] == b"PK":
        # Tệp Excel: chọn sheet nhỏ nhất có cột ngày, món và số ly (bảng tổng theo ngày thay vì từng dòng hóa đơn)
        from apps.core import xlsx_read

        found = None
        for entry in sorted(xlsx_read.sheets(io.BytesIO(raw)), key=xlsx_read.part_size):
            it = xlsx_read.rows(entry)
            header = next(it, None)
            if header and {"date", "item", "qty"} <= set(columns(header)):
                found = (entry[0], header, it)
                break
        if found is None:
            raise ValueError("Không có sheet nào có đủ cột ngày, món và số ly.")
        sheet_name, header, reader = found
    else:
        text = raw.decode("utf-8-sig") if isinstance(raw, bytes) else raw
        try:
            dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;" + chr(9))
        except csv.Error:
            dialect = csv.excel
        reader = csv.reader(io.StringIO(text), dialect)
        header = next(reader, None)
        if not header:
            raise ValueError("Tệp trống.")
    cols = columns(header)
    if "date" not in cols or "item" not in cols:
        raise ValueError("Không tìm thấy cột ngày và cột món trong dòng tiêu đề.")
    sizes = {}
    for s in ItemSize.objects.select_related("item"):
        sizes[(norm(s.item.name), norm(s.name))] = s
        sizes.setdefault((norm(s.item.name), ""), s)
    totals, day_map, unmatched, bad_rows, future = defaultdict(int), {}, defaultdict(int), 0, 0
    today = timezone.localdate()
    for row in reader:
        if not any(str(c).strip() for c in row):
            continue

        def get(k):
            return row[cols[k]].strip() if k in cols and cols[k] < len(row) else ""

        day = _parse_day(get("date"))
        if day is None:
            bad_rows += 1
            continue
        if day >= today:
            future += 1  # từ hôm nay trở đi đã có dữ liệu hệ thống hoặc chưa xảy ra
            continue
        st = norm(get("status"))
        for key, words in STATUS_WORDS.items():
            if st in words:
                day_map[day] = key
        name = norm(get("item"))
        if not name:
            day_map.setdefault(day, "mo_cua")
            continue
        size = sizes.get((name, norm(get("size")))) if get("size") else sizes.get((name, ""))
        if size is None:
            unmatched[f"{get('item')} {get('size')}".strip()] += 1
            continue
        try:
            qty = int(float((get("qty") or "1").replace(",", ".")))
        except ValueError:
            bad_rows += 1
            continue
        totals[(day, size.pk)] += max(qty, 0)
        day_map.setdefault(day, "mo_cua")
    if not day_map:
        reasons = [f"{bad_rows} dòng không đọc được ngày hoặc số ly"] if bad_rows else []
        reasons += [f"{future} dòng từ hôm nay trở đi"] if future else []
        reasons += ["món không khớp thực đơn: " + "; ".join(f"{k} ({v} dòng)" for k, v in list(unmatched.items())[:10])
                    ] if unmatched else []
        raise ValueError("Không có dòng nào nhập được" + (" (" + ", ".join(reasons) + ")." if reasons else "."))
    batch = HistoryBatch.objects.create(kind=kind, file_name=file_name[:200], note=note[:255], imported_by=user)
    HistoricalSale.objects.bulk_create([HistoricalSale(batch=batch, date=d, size_id=sid, cups=n)
                                        for (d, sid), n in totals.items()])
    HistoricalDay.objects.bulk_create([HistoricalDay(batch=batch, date=d, status=st) for d, st in day_map.items()])
    days = sorted(day_map)
    batch.summary = {"cups": sum(totals.values()), "days": len(days), "from": str(days[0]) if days else "",
                     "to": str(days[-1]) if days else "", "sizes": len({sid for _, sid in totals}),
                     "unmatched": dict(sorted(unmatched.items(), key=lambda x: -x[1])[:30]), "bad_rows": bad_rows, "future": future,
                     "closed": sum(1 for v in day_map.values() if v == "dong_cua"),
                     "short": sum(1 for v in day_map.values() if v == "thieu_hang"), "sheet": sheet_name}
    batch.save(update_fields=["summary"])
    record(Action.CREATE, actor=user, obj=batch, object_type="forecast.HistoryBatch", after=batch.summary)
    return batch
