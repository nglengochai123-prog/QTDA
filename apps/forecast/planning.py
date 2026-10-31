"""Kế hoạch mua nguyên liệu: đọc dữ liệu, chạy dự báo theo nguyên liệu và bộ tính chính sách, lưu kết quả chống trùng
(thiết kế mua nguyên liệu mục 5.1, 8.3, 8.4, 9).

- Tính toàn bộ: sau khi chốt ngày (tác vụ định kỳ), hoặc khi Chủ quán bấm tính lại. Dựng chuỗi tiêu hao, chọn phương
  pháp, đo sai số cửa sổ, rồi tính chính sách cho từng nguyên liệu.
- Tính riêng một nguyên liệu: sau mỗi biến động tồn hoặc thay đổi đơn đặt, chạy sau khi giao dịch ghi đã hoàn tất;
  nhiều biến động liền nhau chỉ cần lần tính cuối. Dùng lại dự báo của lần tính toàn bộ gần nhất.
- Mỗi kết quả có khóa (nguyên liệu, ngày tính, mã phiên bản dữ liệu); cùng dữ liệu thì trả về đúng bản đã có.
- Không lần tính nào tạo đơn đặt hay liên hệ nhà cung cấp. Đơn Nháp chỉ được tạo khi Chủ quán bấm Chấp nhận.
"""

import hashlib
import json
import logging
import threading
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.core import params

from . import methods, policy, usage
from .models import IngredientPlan, OrderSuggestion, PlanRun

log = logging.getLogger(__name__)

# Đổi khi cách tính thay đổi, để bản tính cũ không được trả lại cho cùng dữ liệu sau khi nâng cấp phần mềm.
ENGINE_VERSION = "ke-hoach-mua-6"

PARAM_KEYS = tuple(k for k in params.DEFAULTS if k.startswith(("plan_", "forecast_")))
TOTAL_KEY = "tong"


def series_key(ingredient_id):
    return f"nl:{ingredient_id}"


def method_config():
    """Tham số của các cách tính dự báo, đọc từ apps/core/params.py (chỉ sửa trong file, không hiện trên giao diện)."""
    g = params.get
    return methods.Config(
        wma_weights=tuple(w / 100 for w in g("forecast_wma_weights_percent")), wma_weeks=g("forecast_wma_weeks"),
        ln_days=g("forecast_ln_days"), hw_min_days=g("forecast_hw_min_days"),
        hw_phi=g("forecast_hw_damping_percent") / 100, tsb_alpha=g("forecast_tsb_alpha_percent") / 100,
        tsb_beta=g("forecast_tsb_beta_percent") / 100, adi_cut=g("forecast_adi_cut_hundredths") / 100,
        cv2_cut=g("forecast_cv2_cut_hundredths") / 100, owner_days=g("forecast_owner_days"),
        model_days=g("forecast_model_days"), prior_days=g("forecast_prior_days"),
        min_origins=g("forecast_min_origins"), quantile_min=g("forecast_quantile_min"),
        switch_gain=g("plan_switch_gain_percent") / 100, switch_days=7 * g("plan_switch_weeks"),
        bias_limit=g("plan_bias_limit_percent") / 100, lookback=g("forecast_lookback_days"),
        auto_switch=bool(g("forecast_auto_switch")))


# ---------------- tham số theo nguyên liệu ----------------

def settings_for(ing):
    """Tham số chính sách đang áp dụng cho một nguyên liệu, kèm nguồn (Chủ quán đặt hay mặc định)."""
    shelf_limit = params.get("plan_group_a_shelf_days")
    if ing.policy_group:
        group, group_src = ing.policy_group, "Chủ quán đặt"
    else:
        group = "A" if ing.shelf_life_days and ing.shelf_life_days <= shelf_limit else "B"
        group_src = f"theo hạn dùng (A khi từ {shelf_limit} ngày trở xuống)"
    if group == "A":
        R = ing.review_period_days or params.get("plan_a_review_days")
        T = ing.target_cycle_days or params.get("plan_a_target_days")
    else:
        R = ing.review_period_days or params.get("plan_b_review_days")
        T = ing.target_cycle_days or R
    # Tham số chung theo quy ước màn hình tham số: 2 là thứ Hai … 8 là Chủ nhật.
    weekday = ing.review_weekday if ing.review_weekday is not None else (params.get("plan_b_review_weekday") - 2) % 7
    csl = params.get("plan_csl_critical_percent" if ing.is_critical else "plan_csl_normal_percent")
    csl_src = "trọng yếu" if ing.is_critical else "mặc định"
    if group == "B" and params.get("plan_csl_long_life_percent") > csl:
        # Hàng để lâu: giữ thêm gần như không mất gì vì không hỏng, nên dồn phần thiếu cho phép của BO-02 sang hàng tươi.
        csl, csl_src = params.get("plan_csl_long_life_percent"), "hàng để lâu (nhóm B)"
    if ing.service_level:
        csl, csl_src = ing.service_level, "Chủ quán đặt"
    estimate = None
    if None not in (ing.weekly_low, ing.weekly_typical, ing.weekly_high):
        estimate = (float(ing.weekly_low), float(ing.weekly_typical), float(ing.weekly_high))
    since = timezone.localdate(ing.weekly_estimate_at) if ing.weekly_estimate_at else None
    return {"group": group, "group_source": group_src, "R": int(R), "T": int(max(T, R)), "weekday": int(weekday),
            "anchor": ing.review_anchor, "estimate_since": since,
            "csl": int(csl), "csl_source": csl_src, "exposure": int(ing.exposure_days), "moq": int(ing.moq_packs or 1),
            "pack": float(ing.pack_size or 1), "pack_label": ing.pack_label or "gói", "unit": ing.get_unit_display(),
            "shelf": ing.shelf_life_days, "capacity": float(ing.storage_capacity) if ing.storage_capacity else None,
            "manual_ss": float(ing.safety_stock or 0), "estimate": estimate}


def params_version(ing, cfg):
    data = {k: params.get(k) for k in PARAM_KEYS}
    data.update({k: v for k, v in cfg.items() if k != "estimate"}, estimate=cfg["estimate"])
    return _digest(data)[:16]


def _digest(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


# ---------------- lựa chọn cách tính (BRU-21, BRU-37) ----------------

def current_choices():
    """{chuỗi: ForecastChoice đang dùng}."""
    from .models import ForecastChoice

    return {c.series_key: c for c in ForecastChoice.objects.filter(superseded_at__isnull=True).order_by("created_at", "id")}


def _evidence(fc):
    h = fc.get("decision_h")
    return {"h": h, "ngay_hoc": fc.get("eligible_days"),
            "mae": {m: (by.get(str(h)) or {}).get("mae") for m, by in (fc.get("errors") or {}).items()}}


def _remember(key, ingredient, fc, choices, now):
    """Ghi cách tự chọn lần đầu khi chuỗi vừa đủ dữ liệu để đánh giá. Không ghi đè lựa chọn đã có: sau lần đầu chỉ
    Chủ quán đổi được (BRU-37)."""
    from apps.core.models import Store

    from .models import ForecastChoice

    if fc.get("stage") != methods.STAGE_MODEL or not fc.get("method") or not fc.get("auto_pick"):
        return
    if key in choices:
        return
    store = ingredient.store if ingredient is not None else Store.get_default()
    choices[key] = ForecastChoice.objects.create(
        store=store, series_key=key, ingredient=ingredient, method=fc["method"], source=ForecastChoice.Source.AUTO,
        evidence=_evidence(fc))


def _hold_proposal(fc, choice, today, days):
    """Đề xuất đổi cách chỉ đưa ra khi cách đang dùng đã được chọn từ `days` ngày trước trở lên (lần tự chọn đầu,
    lần Chủ quán đổi hay giữ nguyên gần nhất): tránh đổi qua đổi lại, và không nhắc lại đề xuất vừa bị từ chối."""
    if fc.get("requires_approval"):
        return
    if fc.get("proposal") and (choice is None or (today - timezone.localdate(choice.created_at)).days < days):
        fc["proposal"] = None


def decide_switch(user, key, accept, note=""):
    """Chủ quán duyệt đổi sang cách dự báo được đề xuất, hoặc giữ cách đang dùng. Trả lựa chọn mới."""
    from apps.audit.models import Action
    from apps.audit.services import record
    from apps.core.models import Store
    from apps.inventory.models import Ingredient

    from .models import ForecastChoice

    if not user.is_owner:
        raise ValidationError("Chỉ Chủ quán được duyệt phương pháp dự báo.")
    ingredient = None
    if key == TOTAL_KEY:
        run = PlanRun.objects.filter(kind__in=[PlanRun.Kind.FULL, PlanRun.Kind.MANUAL]).first()
        fc = ((run.summary or {}).get("tong") or {}) if run else {}
    else:
        ingredient = Ingredient.objects.filter(pk=int(key.split(":", 1)[1])).first()
        plan = IngredientPlan.objects.filter(ingredient=ingredient, is_current=True).first() if ingredient else None
        fc = plan.forecast if plan else {}
    p = fc.get("proposal")
    if not p:
        raise ValidationError("Đề xuất này không còn; trang đã được tính lại.")
    with transaction.atomic():
        old = ForecastChoice.objects.select_for_update().filter(series_key=key, superseded_at__isnull=True)
        current = old.first()
        now = timezone.now()
        old.update(superseded_at=now)
        store = ingredient.store if ingredient is not None else Store.get_default()
        evidence = {"de_xuat": p, "ghi_chu": (note or "")[:255]}
        if accept:
            choice = ForecastChoice.objects.create(store=store, series_key=key, ingredient=ingredient,
                                                   method=p["method"], source=ForecastChoice.Source.APPROVED,
                                                   evidence=evidence, decided_by=user)
        else:
            evidence["tu_choi"] = p["method"]
            choice = ForecastChoice.objects.create(store=store, series_key=key, ingredient=ingredient,
                                                   method=current.method if current else p["from"],
                                                   source=ForecastChoice.Source.KEPT, evidence=evidence,
                                                   decided_by=user)
        target = ingredient.name if ingredient else "tổng số ly cả quán"
        record(Action.UPDATE, actor=user, obj=choice, object_type="forecast.ForecastChoice",
               after={"du_bao": target, "quyet_dinh": "Đổi cách dự báo" if accept else "Giữ cách dự báo",
                      "sai_so_giam": f"{round(p['gain'] * 100)}%"}, reason=note or "")
    return choice


def proposals(today=None):
    """Đề xuất đổi cách dự báo đang chờ Chủ quán: [(khóa, tên, mức giảm sai số, số tuần so)]."""
    out = []
    run = PlanRun.objects.filter(kind__in=[PlanRun.Kind.FULL, PlanRun.Kind.MANUAL]).first()
    p = ((run.summary or {}).get("tong") or {}).get("proposal") if run else None
    if p:
        out.append({"key": TOTAL_KEY, "name": "Tổng số ly cả quán", "gain": p["gain"], "weeks": p["weeks"]})
    for plan in current_plans().order_by("ingredient__name"):
        p = (plan.forecast or {}).get("proposal")
        if p:
            out.append({"key": series_key(plan.ingredient_id), "name": plan.ingredient.name, "gain": p["gain"],
                        "weeks": p["weeks"]})
    return out


# ---------------- phân loại ABC theo giá trị tiêu hao ----------------

def abc_classes(values):
    """{nguyên liệu: 'A' | 'B' | 'C'} theo giá trị tiêu hao 8 tuần (lượng × đơn giá nhập gần nhất): nhóm A chiếm tới
    plan_abc_a_percent tổng giá trị, nhóm B tới plan_abc_b_percent, còn lại C. Chưa có giá thì xếp C."""
    total = sum(v for v in values.values() if v)
    a_cut, b_cut = params.get("plan_abc_a_percent") / 100, params.get("plan_abc_b_percent") / 100
    out, acc = {}, 0.0
    for ing, v in sorted(values.items(), key=lambda x: -(x[1] or 0)):
        if not v or total <= 0:
            out[ing] = "C"
            continue
        out[ing] = "A" if acc < a_cut else "B" if acc < b_cut else "C"
        acc += v / total
    return out


def _unit_costs():
    from apps.inventory.models import ReceiptLine

    out = {}
    for ing, price in ReceiptLine.objects.order_by("receipt__created_at", "pk").values_list("ingredient_id", "unit_price"):
        out[ing] = price
    return out


# ---------------- dự báo theo nguyên liệu ----------------

def build_forecasts(now=None, ingredients=None, report=None):
    """Dự báo cho mọi nguyên liệu đang dùng; lưu chuỗi tiêu hao theo ngày. `report` (dict) nhận tóm tắt dự báo tổng số
    ly cả quán để lưu vào lần tính.

    Mỗi nguyên liệu được đánh giá trên chính chuỗi tiêu hao của nó với các cách: bình quân theo loại ngày, bình quân có
    trọng số cùng thứ, Holt-Winters, TSB (khi bán lác đác) và phân cấp từ tổng số ly × tỷ trọng món × định mức."""
    from apps.inventory.models import Ingredient

    from . import hierarchy

    now = now or timezone.now()
    today = timezone.localdate(now)
    data = usage.build(today, now=now)
    usage.save(data)
    horizon = params.get("plan_horizon_days")
    cfg_m = method_config()
    choices = current_choices()
    total, items, recent = hierarchy.from_usage(data, now)
    total_choice = choices.get(TOTAL_KEY)
    h = hierarchy.build(total, items, today=today, horizon=horizon, cfg=cfg_m,
                        approved=total_choice.method if total_choice else None,
                        owner_days=params.get("forecast_item_owner_days"))
    tfc = h["total"]
    _hold_proposal(tfc, total_choice, today, cfg_m.switch_days)
    _remember(TOTAL_KEY, None, tfc, choices, now)
    if report is not None:
        st7 = ((tfc.get("errors") or {}).get(tfc.get("method")) or {}).get("7") or {}
        report["tong"] = {"stage": tfc.get("stage"), "provisional": tfc.get("provisional"),
                          "eligible_days": tfc.get("eligible_days"), "proposal": tfc.get("proposal"),
                          "wape_7": st7.get("wape"), "bias_7": st7.get("bias"), "item_wape_1": h.get("item_wape"),
                          "items": len(items)}
    costs = _unit_costs()
    out, values = {}, {}
    unmeasured = _unmeasured_yields(data["book"])
    qs = Ingredient.objects.filter(is_active=True)
    if ingredients is not None:
        qs = qs.filter(pk__in=ingredients)
    for ing in qs:
        cfg = settings_for(ing)
        series = usage.series_for(data, ing.pk)
        rates = usage.rates(data, ing.pk)
        if not ing.is_semi:
            values[ing.pk] = rates["ub_8w"] * costs[ing.pk] if ing.pk in costs else None
        external, external_daily = hierarchy.ingredient_forecast(h, items, ing.pk)
        cls = methods.demand_class(series, series[-1][0], cfg_m) if series else None
        candidates = ["LN", "WMA", "HW"] + (["TSB"] if cls and cls["intermittent"] else []) + \
                     (["PH"] if external_daily is not None else [])
        key = series_key(ing.pk)
        choice = choices.get(key)
        decision_h = cfg["R"] + cfg["exposure"]
        fc = methods.forecast_series(
            series, today=today, horizon=horizon, cfg=cfg_m, candidates=candidates,
            approved=choice.method if choice else None, estimate=cfg["estimate"],
            # Ước tính không rõ thời điểm thì coi như mới có hôm nay: không dùng để đánh giá quá khứ.
            estimate_since=cfg["estimate_since"] or today, external=external, external_daily=external_daily,
            decision_h=decision_h, target_h=cfg["T"] + cfg["exposure"], csl=cfg["csl"],
            k=policy.k_for(cfg["csl"]), blocked_share=rates["blocked_share"],
            blocked_limit=params.get("plan_blocked_limit_percent") / 100)
        fc["decision_h"] = decision_h
        _hold_proposal(fc, choice, today, cfg_m.switch_days)
        if any(v for _, v, st in series if st == "ok"):  # chưa từng dùng thì chưa có gì để chọn
            _remember(key, ing, fc, choices, now)
        days = [today + timedelta(days=j) for j in range(horizon)]
        fc.update(first_day=today.isoformat(), rates=rates, factor=rates["factor"],
                  recipe_ratio={d.isoformat(): r for d, r in usage.recipe_ratio(data, ing.pk, days, now).items()},
                  seasonal=seasonal_for(ing, today, days[-1], series, hierarchy.group_shares(items, ing.pk, recent)),
                  season_current=season_current(fc, today))
        fc["warnings"].extend(season_warnings(fc["seasonal"]))
        fc["semi"] = ing.is_semi
        names = [name for semi_id, (name, parts) in unmeasured.items() if ing.pk == semi_id or ing.pk in parts]
        if names:
            fc["warnings"].append("Lượng thu mỗi mẻ của " + ", ".join(names) + " chưa cân đo thực tế: phần nhu cầu đi "
                                  "qua bán thành phẩm này là ước tính.")
        if rates["recon"]["flag"]:
            fc["warnings"].append(
                f"Đối soát lệch {rates['recon']['gap'] * 100:.1f}%".replace(".", ",")
                + f": tiêu hao tính từ dòng bán và hủy sau pha chế {rates['recon']['sold_plus_voided']:,.0f} khác sổ kho "
                  f"{rates['recon']['ledger']:,.0f}.".replace(",", "."))
        out[ing.pk] = fc
    abc = abc_classes(values)
    for pk, fc in out.items():
        fc["abc"] = abc.get(pk, "C") if not fc.get("semi") else ""
        fc.pop("version", None)
        fc["version"] = _digest(fc)[:16]
    return out


def _unmeasured_yields(book):
    """{bán thành phẩm chưa cân đo lượng thu mỗi mẻ: (tên, mọi thành phần qua các tầng)}."""
    from apps.inventory.models import SemiRecipe

    out = {}
    for r in SemiRecipe.objects.filter(yield_measured=False, product__is_active=True).select_related("product"):
        out[r.product_id] = (r.product.name, set(book.explode({r.product_id: 1.0})) - {r.product_id})
    return out


def semi_equivalent(ing):
    """Lượng nguyên liệu gốc đang nằm trong bán thành phẩm còn trong kho (quy theo định mức mẻ). Nhu cầu nguyên liệu
    gốc tính cả phần đi qua bán thành phẩm, nên phần đã làm sẵn được tính như tồn có thể dùng."""
    from apps.inventory.models import IngredientStock

    book = usage.RecipeBook()
    total = 0.0
    for st in IngredientStock.objects.filter(ingredient__kind="ban_thanh_pham", ingredient__is_active=True):
        left = float(st.physical - st.reserved)
        if left > 0:
            total += book.explode({st.ingredient_id: left}).get(ing.pk, 0.0)
    return round(total, 2)


def seasonal_for(ing, first, last, series=(), shares=None):
    """Điều chỉnh theo mùa của Chủ quán còn hiệu lực trong tầm dự báo: riêng nguyên liệu, theo nhóm món hoặc chung.

    Mức Chủ quán đặt là thay đổi so với nền ngoài mùa. Nền lấy theo thứ tự: số Chủ quán nhập có căn cứ (chỉ cho điều
    chỉnh riêng một nguyên liệu), hoặc trung bình ngày đủ điều kiện trong 28 ngày trước khi mùa bắt đầu (cần ít nhất 14
    ngày). Khi mùa đã bắt đầu mà không xác định được nền thì ghi trạng thái và không áp, vì không biết mô hình đã học
    mùa tới đâu. Điều chỉnh theo nhóm món chỉ giữ khi nguyên liệu có được dùng cho nhóm đó, kèm tỷ lệ tiêu hao của
    nguyên liệu dành cho nhóm (`shares`). Cách gộp các điều chỉnh cùng ngày ở `season_target`."""
    from django.db.models import Q

    from .models import SeasonalAdjustment

    shares = shares or {}
    rows = (SeasonalAdjustment.objects.filter(is_active=True, start__lte=last, end__gte=first)
            .filter(Q(ingredient=ing) | Q(ingredient__isnull=True)).order_by("start", "pk"))
    out = []
    for a in rows:
        if a.menu_group_id and not shares.get(a.menu_group_id):
            continue
        if a.ingredient_id and a.baseline_daily:
            baseline, source = float(a.baseline_daily), "chu_quan"
        else:
            base_days = [x for d, x, st in series if st == "ok" and a.start - timedelta(days=28) <= d < a.start]
            baseline, source = (sum(base_days) / len(base_days), "du_lieu") if len(base_days) >= 14 else (None, None)
        started = a.start <= first
        out.append({"id": a.pk, "start": a.start.isoformat(), "end": a.end.isoformat(), "percent": a.percent,
                    "basis": a.basis, "ingredient": a.ingredient_id, "independent": a.independent,
                    "menu_group": a.menu_group_id, "share": round(shares.get(a.menu_group_id, 1.0), 4)
                    if a.menu_group_id else None,
                    "created_at": a.created_at.isoformat(), "started": started,
                    "baseline": round(baseline, 2) if baseline else None, "baseline_source": source,
                    "status": ("chua_xac_dinh_nen" if started and baseline is None else
                               "chua_bat_dau" if not started else "dang_ap")})
    return out


def season_current(fc, first):
    """Mức dự báo hiện tại (trung bình 7 ngày tới) để biết mô hình đã học mùa tới đâu."""
    daily = (fc or {}).get("daily") or {}
    vals = [daily[(first + timedelta(days=j)).isoformat()] for j in range(7)
            if (first + timedelta(days=j)).isoformat() in daily]
    return sum(vals) / len(vals) if len(vals) == 7 else None


def _pick(use):
    """Nhiều điều chỉnh cùng phạm vi chỉ cộng tác động khi Chủ quán đã xác nhận tất cả là nguyên nhân độc lập; nếu
    không chỉ dùng điều chỉnh ghi gần nhất."""
    if len(use) > 1 and not all(a.get("independent") for a in use):
        return [max(use, key=lambda a: a["created_at"])]
    return use


def applicable_seasons(seasonal, iso):
    """Các điều chỉnh dùng cho một ngày. Điều chỉnh riêng của nguyên liệu thay thế mọi điều chỉnh khác; điều chỉnh
    theo nhóm món thay điều chỉnh chung cho phần tiêu hao của nhóm đó."""
    active = [a for a in seasonal or [] if a["start"] <= iso <= a["end"]]
    specific = [a for a in active if a["ingredient"]]
    if specific:
        return _pick(specific)
    groups = {}
    for a in active:
        if a.get("menu_group"):
            groups.setdefault(a["menu_group"], []).append(a)
    general = [a for a in active if not a["ingredient"] and not a.get("menu_group")]
    return [a for lst in groups.values() for a in _pick(lst)] + _pick(general)


def season_target(use):
    """Hệ số thay đổi tổng hợp so với nền: nhóm món nào có điều chỉnh riêng thì phần tiêu hao của nhóm đó nhận mức của
    nhóm; phần còn lại nhận điều chỉnh chung (nếu có)."""
    if not use:
        return 1.0
    if any(a["ingredient"] for a in use):
        target = 1.0
        for a in use:
            target *= 1 + a["percent"] / 100
        return target
    change, covered = 0.0, 0.0
    groups = {}
    for a in use:
        if a.get("menu_group"):
            groups.setdefault(a["menu_group"], []).append(a)
    for lst in groups.values():
        t = 1.0
        for a in lst:
            t *= 1 + a["percent"] / 100
        share = lst[0].get("share") or 0.0
        change += share * (t - 1)
        covered += share
    general = [a for a in use if not a.get("menu_group")]
    if general:
        t = 1.0
        for a in general:
            t *= 1 + a["percent"] / 100
        change += max(0.0, 1 - covered) * (t - 1)
    return 1 + change


def season_factor(fc, iso):
    use = applicable_seasons(fc.get("seasonal"), iso)
    if not use:
        return 1.0
    target = season_target(use)
    first = min(use, key=lambda a: a["start"])
    if not first.get("started"):
        return target  # mùa chưa bắt đầu: mô hình chưa thể học mùa, áp đủ
    if not first.get("baseline"):
        return 1.0  # chưa xác định được nền ngoài mùa: không áp, đã ghi trạng thái để Chủ quán bổ sung
    return methods.residual_season_factor((target - 1) * 100, first["baseline"], fc.get("season_current"))


def season_warnings(seasonal):
    out = []
    for a in seasonal or []:
        if a["status"] == "chua_xac_dinh_nen":
            out.append(f"Điều chỉnh mùa {a['percent']:+d}% từ {a['start']}: chưa xác định được nền ngoài mùa (cần 14 "
                       f"ngày dữ liệu trong 28 ngày trước mùa), tạm không áp. Nhập nền ngoài mùa có căn cứ nếu muốn áp.")
    specific = [a for a in seasonal or [] if a["ingredient"]]
    for g in [a for a in seasonal or [] if not a["ingredient"]]:
        if any(x["start"] <= g["end"] and g["start"] <= x["end"] for x in specific):
            out.append(f"Điều chỉnh {'theo nhóm món' if g.get('menu_group') else 'chung'} {g['percent']:+d}% bị điều "
                       f"chỉnh riêng của nguyên liệu thay thế trong phần thời gian trùng.")
    return out


def demand(fc, t):
    """d(t) = Û b(t) × (1 + r h + r vh + r k + r btp) × hệ số đổi định mức của ngày t × điều chỉnh mùa của Chủ quán."""
    base = fc.get("daily", {}).get(t.isoformat())
    if base is None:
        return None
    iso = t.isoformat()
    return base * fc.get("factor", 1.0) * fc.get("recipe_ratio", {}).get(iso, 1.0) * season_factor(fc, iso)


# ---------------- dữ liệu tồn và đơn ----------------

def _lots(ing, today):
    from apps.inventory.models import PurchaseOrder

    lots, excluded, pos = [], [], []
    for po in PurchaseOrder.objects.filter(ingredient=ing).exclude(
            status__in=[PurchaseOrder.Status.DELIVERED, PurchaseOrder.Status.CANCELLED]).order_by("expected_date", "pk"):
        st = po.effective_status(today)
        label = PurchaseOrder.Status(st).label.lower()
        if po.remaining <= 0:
            continue
        lot = policy.Lot(float(po.remaining), po.expected_date, st, po.pk, label)
        if po.is_incoming(today):
            lots.append(lot)
        else:
            if st == PurchaseOrder.Status.DRAFT:
                lot.label = "nháp đã quá ngày phải đặt"
            excluded.append(lot)
        pos.append(po)
    return lots, excluded, pos


def on_hand_lots(ing):
    """Các lô đang còn của nguyên liệu (inventory.lots) để tính phần sẽ hết hạn (EWA): [(lượng, ngày cuối còn dùng)].

    Hạn của lô: hạn ghi trên phiếu nhập; không ghi thì ngày nhập + hạn dùng − 1 (ghi sẵn khi tạo lô). Lô chưa rõ hạn
    (tồn đầu kỳ, dư kiểm kê) coi như không hết hạn."""
    from apps.inventory.models import StockLot

    return [(float(lot.remaining), lot.expiry_date or date.max)
            for lot in StockLot.objects.filter(ingredient=ing, remaining__gt=0).order_by("received_at", "pk")]


def committed(ing):
    """C: lượng ước tính của phiếu dự phòng đã ghi nhưng chưa nhập bù vào kho (chờ Chủ quán xác nhận)."""
    from apps.catalog.models import ItemSize
    from apps.orders.models import BackupSlip

    total = 0.0
    book = usage.RecipeBook()
    now = timezone.now()
    for slip in BackupSlip.objects.filter(status=BackupSlip.Status.PENDING):
        for line in (slip.payload or {}).get("lines", []):
            try:
                size = ItemSize.objects.get(pk=line.get("size"))
                per = book.usage(size.item_id, size.pk, tuple(int(o) for o in line.get("options") or ()), now,
                                 explode=True)
                total += per.get(ing.pk, 0.0) * int(line.get("quantity") or 1)
            except (ItemSize.DoesNotExist, TypeError, ValueError):
                continue
    return round(total, 2)


_profiles = {}


def remaining_today(now):
    """f0: tỷ lệ bán còn lại của hôm nay theo hồ sơ giờ 8 tuần; 0 từ giờ đóng cửa. Hồ sơ giờ chỉ đổi theo ngày nên
    được giữ lại trong ngày, để tính lại sau mỗi biến động không phải đọc lại 8 tuần đơn hàng."""
    from apps.schedule.services import _hourly_profile

    local = timezone.localtime(now)
    if local.hour >= params.get("close_hour"):
        return 0.0
    day = local.date()
    if day not in _profiles:
        _profiles.clear()
        _profiles[day] = _hourly_profile(day)[0]
    share = _profiles[day].get(local.weekday() >= 5, {})
    if share:
        return min(1.0, share.get(local.hour, 0) * (1 - local.minute / 60)
                   + sum(v for h, v in share.items() if h > local.hour))
    open_h, close_h = params.get("open_hour"), params.get("close_hour")
    hour = local.hour + local.minute / 60
    if hour <= open_h:
        return 1.0
    return max(0.0, (close_h - hour) / (close_h - open_h))


# ---------------- tính và lưu ----------------

def compute(ing, fc, now=None, run=None):
    """Tính chính sách cho một nguyên liệu từ một bản dự báo; trả IngredientPlan (bản có sẵn nếu cùng dữ liệu)."""
    from apps.inventory.models import IngredientStock, PurchaseOrder, StockMovement

    now = now or timezone.now()
    today = timezone.localdate(now)
    cfg = settings_for(ing)
    f0 = remaining_today(now)
    stock = IngredientStock.objects.filter(ingredient=ing).first()
    physical = float(stock.physical) if stock else 0.0
    reserved = float(stock.reserved) if stock else 0.0
    semi = semi_equivalent(ing)
    c = committed(ing)
    po_rows = PurchaseOrder.objects.filter(ingredient=ing)
    parts = {
        "bien_dong": StockMovement.objects.filter(ingredient=ing).order_by("-id").values_list("id", flat=True).first(),
        "don_dat": [po_rows.count(), str(max(po_rows.values_list("updated_at", flat=True), default=""))],
        "du_bao": fc.get("version"), "tham_so": params_version(ing, cfg),
        # f0 làm tròn 2 chữ số: cùng dữ liệu nhưng phần nhu cầu còn lại của hôm nay đổi thì tính lại.
        "ton": [physical, reserved, c, semi], "con_lai_hom_nay": round(f0, 2), "cach_tinh": ENGINE_VERSION,
    }
    data_hash = _digest(parts)
    existing = IngredientPlan.objects.filter(ingredient=ing, calc_date=today, data_hash=data_hash).first()
    if existing:
        return existing
    result = evaluate(ing, cfg, fc, today, f0, physical, reserved, c, semi)
    plan = _save(ing, today, now, data_hash, parts, fc, result, run)
    return plan


def evaluate(ing, cfg, fc, today, f0, physical, reserved, c, semi=0.0):
    """Chạy bộ tính với dự báo đã có; không ghi gì. semi: lượng quy đổi đang nằm trong bán thành phẩm đã làm."""
    lots, excluded, _ = _lots(ing, today)
    if not fc.get("method") or fc.get("requires_approval"):
        return {"action": policy.NO_DATA, "reason": "; ".join(fc.get("warnings") or ["Chưa đủ dữ liệu."]),
                "available": physical - reserved + semi, "physical": physical, "reserved": reserved, "lots": lots,
                "excluded": excluded}
    horizon = params.get("plan_horizon_days")
    daily = {}
    for j in range(horizon):
        t = today + timedelta(days=j)
        v = demand(fc, t)
        if v is not None:
            daily[t] = v
    factor = fc.get("factor", 1.0)
    sigma = [s * factor for s in fc.get("sigma", [])]
    quantiles = _quantile_mode(fc, cfg, factor)
    aging = on_hand_lots(ing)
    inp = policy.Inputs(
        today=today, daily=daily, sigma=sigma, csl=cfg["csl"], available=physical - reserved + semi, physical=physical,
        reserved=reserved, committed=c, lots=lots, excluded=excluded, f0=f0, group=cfg["group"],
        review_days=cfg["R"], target_days=cfg["T"], review_weekday=cfg["weekday"], exposure=cfg["exposure"],
        pack=cfg["pack"], pack_label=cfg["pack_label"], unit=cfg["unit"], moq=cfg["moq"], shelf_life=cfg["shelf"],
        capacity=cfg["capacity"], manual_ss=cfg["manual_ss"], quantiles=quantiles,
        sigma_label=fc.get("sigma_label", ""), sigma_measured=fc.get("sigma_measured"),
        review_anchor=cfg["anchor"],
        on_hand_lots=aging if cfg["shelf"] or any(e != date.max for _, e in aging) else None)
    result = policy.compute(inp)
    result["periods"] = periods(daily, sigma, today, f0, cfg, fc.get("sigma_measured") or [])
    result["settings"] = cfg
    if semi:
        result["semi_equivalent"] = semi
    return result


def _quantile_mode(fc, cfg, factor):
    """Tồn an toàn theo phân vị sai số cửa sổ khi đã có đủ gốc đánh giá (forecast_quantile_min); chưa đủ thì bộ tính
    dùng kσ. Phân vị âm (dự báo thường cao hơn thực tế) lấy 0: tồn an toàn không âm."""
    q, n = fc.get("error_quantiles") or {}, fc.get("quantile_n") or {}
    need = params.get("forecast_quantile_min")
    ok = {int(h): max(float(qv), 0.0) * factor for h, qv in q.items() if (n.get(h, n.get(str(h))) or 0) >= need}
    return {"by_h": ok} if ok else None


def periods(daily, sigma, today, f0, cfg, measured=()):
    """Nhu cầu tuần này (từ hôm nay), tuần sau và phần còn lại của tháng, kèm khoảng 80% và quy ra số gói. Khoảng
    của cửa sổ chưa được đo trực tiếp ghi là ước lượng tạm."""
    def sig(h):
        if h <= 0 or not sigma:
            return 0.0
        return sigma[h - 1] if h <= len(sigma) else sigma[-1] * (h / len(sigma)) ** 0.5

    def block(label, days):
        days = [d for d in days if d in daily]
        if not days:
            return None
        mu = sum(daily[d] * (f0 if d == today else 1) for d in days)
        h = sum(1 for d in days if d != today or f0 > 0)
        half = 1.2816 * sig(h)
        return {"label": label, "from": days[0], "to": days[-1], "mean": round(mu, 2),
                "measured": bool(0 < h <= len(measured) and measured[h - 1]),
                "low": round(max(mu - half, 0), 2), "high": round(mu + half, 2),
                "packs": round(mu / cfg["pack"], 1) if cfg["pack"] else None}

    week_end = today + timedelta(days=6 - today.weekday())
    next_start = week_end + timedelta(days=1)
    month_end = (date(today.year + (today.month == 12), today.month % 12 + 1, 1) - timedelta(days=1))
    span = lambda a, b: [a + timedelta(days=j) for j in range((b - a).days + 1)]  # noqa: E731
    return [p for p in (block("Tuần này, từ hôm nay", span(today, week_end)),
                        block("Tuần sau", span(next_start, next_start + timedelta(days=6))),
                        block("Tháng này, từ hôm nay", span(today, month_end))) if p]


def _jsonable(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, policy.Lot):
        return {"quantity": value.quantity, "arrival": value.arrival.isoformat(), "status": value.status,
                "po_id": value.po_id, "label": value.label}
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_jsonable(v) for v in value]
    if isinstance(value, Decimal):
        return float(value)
    return value


@transaction.atomic
def _save(ing, today, now, data_hash, parts, fc, result, run):
    action = result["action"]
    order_by = result.get("order_by")
    alert_on = action in (policy.BUY, policy.TOP_UP, policy.EXPEDITE) and order_by is not None and order_by <= today
    prev = (IngredientPlan.objects.select_for_update().filter(ingredient=ing, is_current=True)
            .order_by("-calculated_at", "-id").first())
    plan = IngredientPlan.objects.create(
        ingredient=ing, run=run, calc_date=today, calculated_at=now, data_hash=data_hash, data_parts=_jsonable(parts),
        forecast_version=fc.get("version") or "", forecast=_jsonable(fc), result=_jsonable(result), action=action,
        order_by=order_by, order_now=bool(result.get("order_now")), risk_date=result.get("risk_date"),
        stockout_date=result.get("stockout_date"), suggested_quantity=Decimal(str(result.get("quantity") or 0)),
        packs=result.get("packs") or 0, alert_on=alert_on)
    if alert_on:
        if prev is not None and prev.alert_on and prev.episode_key:
            plan.episode_start, plan.episode_key = prev.episode_start, prev.episode_key
        else:  # đợt rủi ro mới: cảnh báo mới dù cảnh báo đợt trước đã đóng tay
            plan.episode_start, plan.episode_key = today, f"{today:%Y%m%d}-{plan.pk}"
        plan.save(update_fields=["episode_start", "episode_key"])
    IngredientPlan.objects.filter(ingredient=ing, is_current=True).exclude(pk=plan.pk).update(
        is_current=False, superseded_at=now)
    return plan


def run_full(now=None, user=None, kind=PlanRun.Kind.FULL):
    """Tính toàn bộ: dự báo mới cho mọi nguyên liệu rồi tính chính sách."""
    from apps.inventory.models import Ingredient

    now = now or timezone.now()
    run = PlanRun.objects.create(kind=kind, started_at=now, triggered_by=user)
    report = {}
    forecasts = build_forecasts(now, report=report)
    counts, semi = {}, {}
    for ing in Ingredient.objects.filter(is_active=True, pk__in=forecasts).select_related("main_supplier"):
        if ing.is_semi:
            semi[str(ing.pk)] = semi_outlook(forecasts[ing.pk], timezone.localdate(now))
            continue
        plan = compute(ing, forecasts[ing.pk], now, run)
        counts[plan.action] = counts.get(plan.action, 0) + 1
    IngredientPlan.objects.filter(is_current=True, ingredient__kind="ban_thanh_pham").update(
        is_current=False, superseded_at=now)
    run.summary = {"nguyen_lieu": len(forecasts) - len(semi), "hanh_dong": counts, "ban_thanh_pham": semi, **report}
    run.save(update_fields=["summary", "updated_at"])
    return run


def semi_outlook(fc, today, days=3):
    """Nhu cầu bán thành phẩm vài ngày tới (đã gồm hủy, pha hỏng và đổ bỏ) để gợi ý số mẻ cần làm."""
    out = []
    for j in range(days):
        t = today + timedelta(days=j)
        v = demand(fc, t) if fc.get("method") else None
        out.append([t.isoformat(), round(v, 1) if v is not None else None])
    return {"daily": out, "provisional": bool(fc.get("provisional")), "warnings": fc.get("warnings", [])[:3]}


def production_suggestions(now=None):
    """Bán thành phẩm cần làm: nhu cầu phần còn lại của hôm nay (sau giờ đóng cửa thì cho ngày mai) theo lần tính toàn
    bộ gần nhất, trừ tồn có thể dùng, quy ra số mẻ nguyên (làm tròn lên)."""
    import math

    from apps.inventory.models import Ingredient, SemiRecipe
    from apps.inventory.stock import ensure_stock_rows

    ensure_stock_rows()
    now = now or timezone.now()
    today = timezone.localdate(now)
    last = PlanRun.objects.filter(kind__in=[PlanRun.Kind.FULL, PlanRun.Kind.MANUAL]).order_by("-started_at").first()
    outlook = (last.summary or {}).get("ban_thanh_pham", {}) if last else {}
    recipes = {r.product_id: r for r in SemiRecipe.objects.prefetch_related("lines__ingredient")}
    f0 = remaining_today(now)
    day = today if f0 > 0 else today + timedelta(days=1)
    out = []
    for ing in Ingredient.objects.filter(kind="ban_thanh_pham", is_active=True).select_related("stock").order_by("name"):
        o = outlook.get(str(ing.pk)) or {}
        daily = dict((d, v) for d, v in o.get("daily", []))
        base = daily.get(day.isoformat())
        need = None if base is None else base * (f0 if day == today else 1.0)
        available = float(ing.stock.available)
        recipe = recipes.get(ing.pk)
        batches = None
        if need is not None and recipe is not None:
            gap = need - available
            batches = math.ceil(gap / float(recipe.batch_output) - 1e-9) if gap > 0 else 0
        out.append({"ingredient": ing, "recipe": recipe, "available": available, "need": need,
                    "for_today": day == today, "batches": batches, "provisional": o.get("provisional", False)})
    return out


def recompute(ingredient_id, now=None):
    """Tính lại chính sách cho một nguyên liệu với dự báo của lần tính toàn bộ gần nhất. Bán thành phẩm không có kế
    hoạch mua: tồn của nó đổi thì tính lại các nguyên liệu gốc của nó (tồn quy đổi đã đổi)."""
    from apps.inventory.models import Ingredient

    ing = Ingredient.objects.filter(pk=ingredient_id, is_active=True).first()
    if ing is None:
        return None
    if ing.is_semi:
        from apps.inventory.models import semi_components

        for comp in semi_components(ing.pk):
            recompute(comp, now)
        return None
    last = IngredientPlan.objects.filter(ingredient=ing).order_by("-calculated_at", "-id").first()
    if last is None or not last.forecast:
        return None
    return compute(ing, last.forecast, now)


def ensure_daily(now=None):
    """Tác vụ định kỳ: tính toàn bộ một lần sau mỗi giờ đóng cửa (và lần đầu khi chưa có)."""
    now = now or timezone.now()
    local = timezone.localtime(now)
    close = timezone.make_aware(datetime.combine(local.date(), time.min) + timedelta(hours=params.get("close_hour")),
                                timezone.get_current_timezone())
    last_close = close if now >= close else close - timedelta(days=1)
    last = PlanRun.objects.filter(kind__in=[PlanRun.Kind.FULL, PlanRun.Kind.MANUAL]).order_by("-started_at").first()
    if last is None or last.started_at < last_close:
        return run_full(now).pk
    return None


# ---------------- giám sát sau biến động ----------------

_local = threading.local()


def schedule_recompute(ingredient_id):
    """Đăng ký tính lại sau khi giao dịch hiện tại ghi xong; nhiều lần đăng ký cho cùng nguyên liệu trong một giao dịch
    chỉ chạy lần cuối. Lỗi khi tính không làm hỏng nghiệp vụ đã ghi."""
    tokens = getattr(_local, "tokens", None)
    if tokens is None:
        tokens = _local.tokens = {}
    token = object()
    tokens[int(ingredient_id)] = token

    def run():
        if tokens.get(int(ingredient_id)) is not token:
            return
        tokens.pop(int(ingredient_id), None)
        try:
            recompute(int(ingredient_id))
        except Exception:  # noqa: BLE001
            log.exception("Không tính lại được kế hoạch mua của nguyên liệu %s", ingredient_id)

    transaction.on_commit(run)


def on_movement(sender, instance, created, **kwargs):
    if created:
        schedule_recompute(instance.ingredient_id)


# ---------------- đọc cho màn hình và cảnh báo ----------------

def current_plans():
    return (IngredientPlan.objects.filter(is_current=True, ingredient__is_active=True, ingredient__kind="mua_vao")
            .select_related("ingredient", "ingredient__main_supplier"))


def sort_key(plan, today):
    """Đặt ngay lên đầu, rồi đặt trong 2 ngày, rồi theo ngày phải đặt; đủ hàng cuối cùng."""
    buy = plan.action in (policy.BUY, policy.TOP_UP, policy.EXPEDITE)
    if plan.order_by is None:
        rank = 3 if not buy else 1
    elif plan.order_by <= today:
        rank = 0
    elif plan.order_by <= today + timedelta(days=2):
        rank = 1
    else:
        rank = 2
    return (rank, plan.order_by or date.max, plan.ingredient.name)


def group_label(plan, today):
    rank = sort_key(plan, today)[0]
    return ["Đặt ngay", "Đặt trong 2 ngày", "Theo dõi", "Đủ hàng"][rank]


def alert_items(today=None):
    """Mục cần cảnh báo Cần đặt hàng: ngày phải đặt là hôm nay hoặc đã qua, theo đợt rủi ro (mục 9.3)."""
    from apps.inventory.models import PurchaseOrder

    today = today or timezone.localdate()
    out = []
    for plan in current_plans().filter(alert_on=True):
        r = plan.result
        unit = plan.ingredient.get_unit_display()
        detail = (f"{plan.get_action_display()}: {plan.packs} {r.get('settings', {}).get('pack_label', 'gói')} "
                  f"({policy.fmt(plan.suggested_quantity)} {unit}). {r.get('reason', '')}")
        if r.get("infeasible"):
            detail = "Không khả thi trong sức chứa. " + detail
        out.append({"ingredient": plan.ingredient, "episode": plan.episode_key, "detail": detail,
                    "order_by": plan.order_by})
    for po in PurchaseOrder.objects.filter(status=PurchaseOrder.Status.DRAFT).select_related("ingredient"):
        limit = po.order_by or timezone.localdate(po.created_at)
        if limit <= today:
            out.append({"ingredient": po.ingredient, "episode": f"nhap-{po.pk}", "order_by": limit,
                        "detail": f"Đơn nháp {policy.fmt(po.quantity)} {po.ingredient.get_unit_display()} chưa báo "
                                  f"nhà cung cấp; phải đặt chậm nhất {limit:%d/%m/%Y}."})
    return out


# ---------------- thao tác của Chủ quán ----------------

def accept(user, plan, quantity, note, expected_date, operation_key):
    """Chấp nhận hoặc sửa rồi chấp nhận: tạo đơn ở trạng thái Nháp và lưu đề xuất cùng số cuối cùng, trong một thao tác
    chạy một lần (gửi lại trả về đơn đã tạo)."""
    from apps.inventory import operations as ops

    if plan.forecast.get("requires_approval"):
        raise ValidationError("Cần duyệt phương pháp dự báo trước khi chấp nhận kế hoạch mua.")
    ing = plan.ingredient
    quantity = Decimal(str(quantity))
    suggested = plan.suggested_quantity
    if quantity <= 0:
        raise ValidationError("Số lượng đặt phải lớn hơn 0.")
    decision = OrderSuggestion.Decision.ACCEPT if quantity == suggested else OrderSuggestion.Decision.EDIT
    note = (note or "").strip()
    if decision == OrderSuggestion.Decision.EDIT and not note:
        raise ValidationError("Số lượng khác đề xuất: ghi lý do.")
    if ing.main_supplier_id is None:
        raise ValidationError(f"{ing.name} chưa có nhà cung cấp chính.")
    order_by = plan.order_by if plan.order_by and plan.order_by > plan.calc_date else timezone.localdate()

    def save(po):
        OrderSuggestion.objects.create(
            store=ing.store, plan=plan, ingredient=ing, components=_suggestion_components(plan),
            suggested_quantity=suggested, final_quantity=quantity, purchase_order=po, decided_by=user,
            decision_note=note, decision=decision)

    return ops.create_purchase_order(user, ing.main_supplier_id, ing.pk, quantity, expected_date,
                                     note=f"Từ kế hoạch mua: {note}"[:255] if note else "Từ kế hoạch mua",
                                     operation_key=operation_key, status="nhap", order_by=order_by, on_created=save,
                                     extra_payload={"plan": plan.pk})


def skip(user, plan, reason, operation_key):
    """Bỏ qua kèm lý do; đề xuất vẫn được lưu để đánh giá về sau."""
    from apps.audit.models import Action
    from apps.audit.services import record
    from apps.core.idempotency import run_once

    reason = (reason or "").strip()
    if not reason:
        raise ValidationError("Ghi lý do bỏ qua đề xuất.")

    def action():
        s = OrderSuggestion.objects.create(
            store=plan.ingredient.store, plan=plan, ingredient=plan.ingredient,
            components=_suggestion_components(plan), suggested_quantity=plan.suggested_quantity,
            final_quantity=Decimal(0), decided_by=user, decision_note=reason[:255],
            decision=OrderSuggestion.Decision.SKIP)
        record(Action.CREATE, actor=user, obj=s, object_type="forecast.OrderSuggestion",
               after={"nguyen_lieu": plan.ingredient.name, "quyet_dinh": "Bỏ qua",
                      "de_xuat": str(plan.suggested_quantity)}, reason=reason)
        return {"suggestion": s.pk}

    return run_once(operation_key, "plan_skip", {"plan": plan.pk, "reason": reason}, action, actor=user)


def _suggestion_components(plan):
    r = plan.result
    keep = ("s", "S", "ip_s", "ip_S", "q0", "packs", "delta", "risk_date", "order_by", "mu_s", "mu_S", "ss_s",
            "ss_S", "binding", "action")
    return {"ke_hoach": plan.pk, "ma_du_lieu": plan.data_hash[:12], **{k: r.get(k) for k in keep}}
