"""Đánh giá ngoài mẫu theo kiểu cuốn chiếu (mục 5 khung lý thuyết; Hyndman và Athanasopoulos 2021).

Tại mỗi mốc, mô hình chỉ dùng dữ liệu trước mốc để dự báo 1..H ngày sau. So sánh ba cách trên cùng các ngày đích:
ước tính ban đầu của Chủ quán, số bán cùng thứ tuần trước, và mô hình Bayes động. Hệ số chiết khấu mức nền được chọn
trên nửa đầu các mốc (giai đoạn chọn cấu hình) và chỉ báo cáo kết quả trên nửa sau (giai đoạn kiểm tra cuối).

Chỉ tiêu: sai số tuyệt đối trung bình của trung vị dự báo (MAE), sai số có dấu trung bình của trung vị (dương là
dự báo dư), CRPS của cả phân phối (Gneiting và Raftery 2007), tỷ lệ số bán thực nằm trong khoảng 10%–90% và độ rộng
trung bình của khoảng. Không dùng tỷ lệ phần trăm sai số khi số bán thực bằng 0.
"""

from collections import defaultdict
from datetime import timedelta

from django.utils import timezone

from apps.core import params

from . import dglm
from .models import DayType
from .services import VAGUE, _sizes, current_judgements, fit, history, prior_for

HORIZONS = (1, 3, 7)
DELTAS = (0.90, 0.95, 0.98)


def _nb(a, b):
    mean, (q10, q50, q90) = dglm.nb_summary(a, b)
    upto = int(mean + 12 * (mean + mean * mean / a) ** 0.5 + 20)
    return {"pmf": dglm.nb_pmf_list(a, b, upto), "q10": q10, "q50": q50, "q90": q90}


def _poisson(lam):
    lam = max(lam, 0.5)
    upto = int(lam + 12 * lam ** 0.5 + 20)
    pmf = dglm.poisson_pmf_list(lam, upto)
    acc, qs, targets = 0.0, [], [0.1, 0.5, 0.9]
    for k, p in enumerate(pmf):
        acc += p
        while targets and acc >= targets[0]:
            qs.append(k)
            targets.pop(0)
    while targets:
        qs.append(upto)
        targets.pop(0)
    return {"pmf": pmf, "q10": qs[0], "q50": qs[1], "q90": qs[2]}


def _score(dist, y):
    return {"ae": abs(dist["q50"] - y), "err": dist["q50"] - y, "crps": dglm.crps_discrete(dist["pmf"], y),
            "cover": dist["q10"] <= y <= dist["q90"], "width": dist["q90"] - dist["q10"]}


def _aggregate(rows):
    n = len(rows)
    if not n:
        return None
    return {"n": n, "mae": round(sum(r["ae"] for r in rows) / n, 2), "bias": round(sum(r["err"] for r in rows) / n, 2),
            "crps": round(sum(r["crps"] for r in rows) / n, 3), "coverage": round(100 * sum(r["cover"] for r in rows) / n),
            "width": round(sum(r["width"] for r in rows) / n, 1)}


def _model_points(series, dates, status, flags, prior, dl, ds, max_h):
    """Một lượt học tuần tự; tại mỗi mốc ghi dự báo 1..max_h ngày tới. Trả {(chỉ số mốc, h): (α, β)}."""
    if prior is not None and prior["independent"]:
        m, C = dglm.prior_state(prior["weekday"], prior["weekend"])
    else:
        m, C = dglm.prior_state(VAGUE, VAGUE)
    model = dglm.PoissonDGLM(m, C, dl, ds)
    out = {}
    for i, d in enumerate(dates):
        ahead = model.ahead([dd.weekday() for dd in dates[i:i + max_h]])
        for h, ab in enumerate(ahead, start=1):
            out[(i, h)] = ab
        if status.get(d) == "du_dieu_kien" and d not in flags:
            model.update(series.get(d, 0), d.weekday())
        else:
            model.skip()
    return out


def evaluate_series(size, dates, status, cups, flags, judgements, max_days, ds):
    series = cups.get(size.pk, {})
    flagged = flags.get(size.pk, set())
    prior = prior_for(size.pk, judgements, max_days)
    eligible = [i for i, d in enumerate(dates) if status.get(d) == "du_dieu_kien" and d not in flagged]
    if len(eligible) < 2:
        return None
    max_h = max(HORIZONS)
    split = dates[eligible[len(eligible) // 2]]  # mốc chia: nửa đầu chọn cấu hình, nửa sau kiểm tra
    by_delta = {dl: _model_points(series, dates, status, flagged, prior, dl, ds, max_h) for dl in DELTAS}

    def targets(selection):
        for i in range(len(dates)):
            origin = dates[i]
            if (origin < split) != selection:
                continue
            for h in range(1, max_h + 1):
                j = i + h - 1
                if j >= len(dates):
                    break
                d = dates[j]
                if status.get(d) == "du_dieu_kien" and d not in flagged:
                    yield i, h, d, series.get(d, 0)

    # chọn hệ số chiết khấu trên nửa đầu
    sel = {}
    for dl, pts in by_delta.items():
        rows = [_score(_nb(*pts[(i, h)]), y) for i, h, d, y in targets(True)]
        sel[dl] = _aggregate(rows)
    choices = [dl for dl in DELTAS if sel[dl]]
    chosen = min(choices, key=lambda dl: sel[dl]["crps"]) if choices else params.get("forecast_delta_level_percent") / 100
    pts = by_delta.get(chosen) or by_delta[DELTAS[1]]
    result = {"size": size, "delta": chosen, "selection": {str(k): v for k, v in sel.items()}, "split": split,
              "eligible_days": len(eligible), "has_prior": prior is not None, "horizons": {}}
    for H in HORIZONS:
        model_rows, owner_rows, naive_rows = [], [], []
        for i, h, d, y in targets(False):
            if h != H:
                continue
            last = d - timedelta(days=7)
            naive_ok = status.get(last) == "du_dieu_kien" and last not in flagged
            if not naive_ok:
                continue  # chỉ so trên các ngày mọi cách đều có dự báo (thiếu nhận định thì bỏ cách Ước tính ban đầu)
            model_rows.append(_score(_nb(*pts[(i, h)]), y))
            if prior is not None:
                pa, pb = prior["weekend"] if d.weekday() >= 5 else prior["weekday"]
                owner_rows.append(_score(_nb(pa, pb), y))
            naive_rows.append(_score(_poisson(series.get(last, 0)), y))
        result["horizons"][H] = {"model": _aggregate(model_rows), "owner": _aggregate(owner_rows),
                                 "naive": _aggregate(naive_rows)}
    h1 = result["horizons"][1]
    min_test = 14
    if h1["model"] and h1["model"]["n"] >= min_test:
        def baselines(H):
            return [result["horizons"][H][k]["crps"] for k in ("owner", "naive") if result["horizons"][H][k]]

        better = all(result["horizons"][H]["model"]["crps"] < min(baselines(H))
                     for H in HORIZONS if result["horizons"][H]["model"] and baselines(H))
        result["verdict"] = "mo_hinh_tot_hon" if better else "chua_tot_hon"
    else:
        result["verdict"] = "chua_du_du_lieu"
    return result


def evaluate(today=None):
    today = today or timezone.localdate()
    dates, status, cups, flags = history(today)
    judgements = current_judgements()
    max_days = params.get("forecast_prior_max_days")
    ds = params.get("forecast_delta_season_percent") / 100
    out = []
    for size in _sizes():
        r = evaluate_series(size, dates, status, cups, flags, judgements, max_days, ds)
        if r:
            out.append(r)
    return {"rows": out, "days": len(dates), "eligible": sum(1 for d in dates if status[d] == "du_dieu_kien"),
            "min_history": params.get("forecast_min_history_days")}


def ingredient_weekly(today=None, weeks=8):
    """FR-28: đối chiếu hằng tuần nhu cầu ước tính với tiêu hao thực tế theo món đã pha, trên các ngày đủ điều kiện.

    Ước tính ban đầu: kỳ vọng theo nhận định. Mô hình: kỳ vọng dự báo 1 ngày trước (chỉ dùng dữ liệu trước ngày đó).
    """
    from apps.inventory.models import StockMovement

    from .services import _recipe_usage, option_rates

    today = today or timezone.localdate()
    dates, status, cups, flags = history(today)
    first_week = today - timedelta(days=today.weekday() + 7 * weeks)
    sizes = _sizes()
    per_size, per_option = _recipe_usage(sizes)
    rates = option_rates(today)
    judgements = current_judgements()
    max_days = params.get("forecast_prior_max_days")
    dl = params.get("forecast_delta_level_percent") / 100
    ds = params.get("forecast_delta_season_percent") / 100
    est_owner, est_model = defaultdict(float), defaultdict(float)
    for size in sizes:
        usage = dict(per_size.get(size.pk, {}))
        for opt, ings in per_option.get(size.item_id, {}).items():
            for ing, qty in ings.items():
                usage[ing] = usage.get(ing, 0.0) + rates.get(size.item_id, {}).get(opt, 0.0) * qty
        if not usage:
            continue
        prior = prior_for(size.pk, judgements, max_days)
        pts = _model_points(cups.get(size.pk, {}), dates, status, flags.get(size.pk, set()), prior, dl, ds, 1)
        for i, d in enumerate(dates):
            week = d - timedelta(days=d.weekday())
            if status.get(d) != "du_dieu_kien" or week < first_week:
                continue
            a, b = pts[(i, 1)]
            for ing, qty in usage.items():
                est_model[(ing, week)] += a / b * qty
                if prior is not None:
                    pa, pb = prior["weekend"] if d.weekday() >= 5 else prior["weekday"]
                    est_owner[(ing, week)] += pa / pb * qty
    actual = defaultdict(float)
    eligible_days = {d for d in dates if status.get(d) == "du_dieu_kien" and d >= first_week}
    for mv in StockMovement.objects.filter(kind=StockMovement.Kind.CONSUME).only("ingredient_id", "quantity", "created_at"):
        d = timezone.localtime(mv.created_at).date()
        if d in eligible_days:
            actual[(mv.ingredient_id, d - timedelta(days=d.weekday()))] += -float(mv.quantity)
    rows = []
    for key in sorted(set(actual) | set(est_model), key=lambda k: (k[0], k[1])):
        a = actual.get(key, 0.0)

        def pct(est):
            return round(100 * abs(est - a) / a) if a > 0 else None

        rows.append({"ingredient_id": key[0], "week": key[1], "actual": round(a, 1),
                     "owner": round(est_owner[key], 1) if key in est_owner else None, "owner_err": pct(est_owner[key]) if key in est_owner else None,
                     "model": round(est_model.get(key, 0.0), 1), "model_err": pct(est_model.get(key, 0.0))})
    return rows


def day_type_label(d):
    return DayType.WEEKEND.label if d.weekday() >= 5 else DayType.WEEKDAY.label
