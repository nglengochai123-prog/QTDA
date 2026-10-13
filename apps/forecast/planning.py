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

PARAM_KEYS = ("plan_csl_critical_percent", "plan_csl_normal_percent", "plan_group_a_shelf_days", "plan_a_review_days",
              "plan_a_target_days", "plan_b_review_days", "plan_b_review_weekday", "plan_horizon_days",
              "plan_switch_gain_percent", "plan_switch_weeks", "plan_bias_limit_percent",
              "plan_blocked_limit_percent", "plan_indirect_share_percent", "plan_reconcile_gap_permille",
              "plan_quantile_band_points", "forecast_delta_level_percent", "forecast_delta_season_percent")


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
    csl = ing.service_level or params.get("plan_csl_critical_percent" if ing.is_critical else "plan_csl_normal_percent")
    estimate = None
    if None not in (ing.weekly_low, ing.weekly_typical, ing.weekly_high):
        estimate = (float(ing.weekly_low), float(ing.weekly_typical), float(ing.weekly_high))
    return {"group": group, "group_source": group_src, "R": int(R), "T": int(max(T, R)), "weekday": int(weekday),
            "csl": int(csl), "exposure": int(ing.exposure_days), "moq": int(ing.moq_packs or 1),
            "pack": float(ing.pack_size or 1), "pack_label": ing.pack_label or "gói", "unit": ing.get_unit_display(),
            "shelf": ing.shelf_life_days, "capacity": float(ing.storage_capacity) if ing.storage_capacity else None,
            "manual_ss": float(ing.safety_stock or 0), "estimate": estimate}


def params_version(ing, cfg):
    data = {k: params.get(k) for k in PARAM_KEYS}
    data.update({k: v for k, v in cfg.items() if k != "estimate"}, estimate=cfg["estimate"])
    return _digest(data)[:16]


def _digest(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


# ---------------- dự báo theo nguyên liệu ----------------

def build_forecasts(now=None, ingredients=None):
    """Dự báo cho mọi nguyên liệu đang dùng từ chuỗi tiêu hao; lưu chuỗi vào bảng tiêu hao theo ngày."""
    from apps.inventory.models import Ingredient

    now = now or timezone.now()
    today = timezone.localdate(now)
    data = usage.build(today, now=now)
    usage.save(data)
    horizon = params.get("plan_horizon_days")
    dl = params.get("forecast_delta_level_percent") / 100
    ds = params.get("forecast_delta_season_percent") / 100
    out = {}
    qs = Ingredient.objects.filter(is_active=True)
    if ingredients is not None:
        qs = qs.filter(pk__in=ingredients)
    for ing in qs:
        cfg = settings_for(ing)
        series = usage.series_for(data, ing.pk)
        rates = usage.rates(data, ing.pk)
        prev = (IngredientPlan.objects.filter(ingredient=ing, is_current=True).values_list("forecast", flat=True)
                .first() or {})
        fc = methods.forecast_ingredient(
            series, today=today, horizon=horizon, estimate=cfg["estimate"], delta_level=dl, delta_season=ds,
            previous_method=prev.get("method"), decision_h=cfg["R"] + cfg["exposure"],
            k=policy.k_for(cfg["csl"]), csl=cfg["csl"], blocked_share=rates["blocked_share"],
            blocked_limit=params.get("plan_blocked_limit_percent") / 100,
            switch_gain=params.get("plan_switch_gain_percent") / 100, switch_days=7 * params.get("plan_switch_weeks"),
            bias_limit=params.get("plan_bias_limit_percent") / 100)
        days = [today + timedelta(days=j) for j in range(horizon)]
        fc.update(first_day=today.isoformat(), rates=rates, factor=rates["factor"],
                  recipe_ratio={d.isoformat(): r for d, r in usage.recipe_ratio(data, ing.pk, days, now).items()})
        if rates["recon"]["flag"]:
            fc["warnings"].append(
                f"Đối soát lệch {rates['recon']['gap'] * 100:.1f}%: tiêu hao tính từ dòng bán và hủy sau pha chế "
                f"{rates['recon']['sold_plus_voided']:,.0f} khác sổ kho {rates['recon']['ledger']:,.0f}."
                .replace(",", "."))
        fc.pop("version", None)
        fc["version"] = _digest(fc)[:16]
        out[ing.pk] = fc
    return out


def demand(fc, t):
    """d(t) = Û b(t) × (1 + r h + r vh + r k) × hệ số đổi định mức của ngày t."""
    base = fc.get("daily", {}).get(t.isoformat())
    if base is None:
        return None
    return base * fc.get("factor", 1.0) * fc.get("recipe_ratio", {}).get(t.isoformat(), 1.0)


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
                per = book.usage(size.item_id, size.pk, tuple(int(o) for o in line.get("options") or ()), now)
                total += per.get(ing.pk, 0.0) * int(line.get("quantity") or 1)
            except (ItemSize.DoesNotExist, TypeError, ValueError):
                continue
    return round(total, 2)


def remaining_today(now):
    """f0: tỷ lệ bán còn lại của hôm nay; 0 từ giờ đóng cửa."""
    from .services import _remaining_today_fraction

    if timezone.localtime(now).hour >= params.get("close_hour"):
        return 0.0
    return _remaining_today_fraction(now)


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
    c = committed(ing)
    po_rows = PurchaseOrder.objects.filter(ingredient=ing)
    parts = {
        "bien_dong": StockMovement.objects.filter(ingredient=ing).order_by("-id").values_list("id", flat=True).first(),
        "don_dat": [po_rows.count(), str(max(po_rows.values_list("updated_at", flat=True), default=""))],
        "du_bao": fc.get("version"), "tham_so": params_version(ing, cfg),
        "ton": [physical, reserved, c], "sau_dong_cua": f0 == 0,
    }
    data_hash = _digest(parts)
    existing = IngredientPlan.objects.filter(ingredient=ing, calc_date=today, data_hash=data_hash).first()
    if existing:
        return existing
    result = evaluate(ing, cfg, fc, today, f0, physical, reserved, c)
    plan = _save(ing, today, now, data_hash, parts, fc, result, run)
    return plan


def evaluate(ing, cfg, fc, today, f0, physical, reserved, c):
    """Chạy bộ tính với dự báo đã có; không ghi gì."""
    lots, excluded, _ = _lots(ing, today)
    if not fc.get("method"):
        return {"action": policy.NO_DATA, "reason": "; ".join(fc.get("warnings") or ["Chưa đủ dữ liệu."]),
                "available": physical - reserved, "physical": physical, "reserved": reserved, "lots": lots,
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
    inp = policy.Inputs(
        today=today, daily=daily, sigma=sigma, csl=cfg["csl"], available=physical - reserved, physical=physical,
        reserved=reserved, committed=c, lots=lots, excluded=excluded, f0=f0, group=cfg["group"],
        review_days=cfg["R"], target_days=cfg["T"], review_weekday=cfg["weekday"], exposure=cfg["exposure"],
        pack=cfg["pack"], pack_label=cfg["pack_label"], unit=cfg["unit"], moq=cfg["moq"], shelf_life=cfg["shelf"],
        capacity=cfg["capacity"], manual_ss=cfg["manual_ss"], quantiles=quantiles,
        sigma_label=fc.get("sigma_label", ""))
    result = policy.compute(inp)
    result["periods"] = periods(daily, sigma, today, f0, cfg)
    result["settings"] = cfg
    return result


def _quantile_mode(fc, cfg, factor):
    """Cách phân vị chỉ bật khi độ phủ thực tế của phân vị nằm trong CSL ± 3 điểm ở cả hai cửa sổ."""
    q, cov = fc.get("error_quantiles") or {}, fc.get("quantile_coverage") or {}
    band = params.get("plan_quantile_band_points") / 100
    target = cfg["csl"] / 100
    ok = {}
    for h, qv in q.items():
        c = cov.get(h, cov.get(str(h)))
        if c is not None and abs(c - target) <= band:
            ok[int(h)] = qv * factor
    return {"by_h": ok} if ok else None


def periods(daily, sigma, today, f0, cfg):
    """Nhu cầu tuần này (từ hôm nay), tuần sau và phần còn lại của tháng, kèm khoảng 80% và quy ra số gói."""
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
    forecasts = build_forecasts(now)
    counts = {}
    for ing in Ingredient.objects.filter(is_active=True, pk__in=forecasts).select_related("main_supplier"):
        plan = compute(ing, forecasts[ing.pk], now, run)
        counts[plan.action] = counts.get(plan.action, 0) + 1
    run.summary = {"nguyen_lieu": len(forecasts), "hanh_dong": counts}
    run.save(update_fields=["summary", "updated_at"])
    return run


def recompute(ingredient_id, now=None):
    """Tính lại chính sách cho một nguyên liệu với dự báo của lần tính toàn bộ gần nhất."""
    from apps.inventory.models import Ingredient

    ing = Ingredient.objects.filter(pk=ingredient_id, is_active=True).first()
    if ing is None:
        return None
    last = IngredientPlan.objects.filter(ingredient=ing).order_by("-calculated_at", "-id").first()
    if last is None or not last.forecast:
        return None
    return compute(ing, last.forecast, now)


def ensure_daily(now=None):
    """Tác vụ định kỳ: tính toàn bộ một lần sau mỗi giờ đóng cửa (và lần đầu khi chưa có)."""
    now = now or timezone.now()
    local = timezone.localtime(now)
    close = timezone.make_aware(datetime.combine(local.date(), time(params.get("close_hour"))),
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
    return (IngredientPlan.objects.filter(is_current=True, ingredient__is_active=True)
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

    ing = plan.ingredient
    quantity = Decimal(str(quantity))
    suggested = plan.suggested_quantity
    if quantity <= 0:
        raise ValidationError("Số lượng đặt phải lớn hơn 0.")
    decision = OrderSuggestion.Decision.ACCEPT if quantity == suggested else OrderSuggestion.Decision.EDIT
    note = (note or "").strip()
    if decision == OrderSuggestion.Decision.EDIT and not note:
        raise ValidationError("Số lượng khác đề xuất: ghi lý do (BRU-24, NFR-22).")
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
