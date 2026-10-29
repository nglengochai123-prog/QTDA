"""Màn hình dự báo nhu cầu, đặt hàng đề xuất và đánh giá dự báo (chỉ Chủ quán, Bảng 5.3: Cap.FORECASTS)."""

import uuid
from collections import OrderedDict
from datetime import date, timedelta
from decimal import Decimal

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST

from apps.accounts.permissions import Cap, capability_required
from apps.audit.models import Action
from apps.audit.services import record
from apps.core import errors, numbers
from apps.core.idempotency import OperationKeyError
from apps.core.templatetags.loi_thuong import ngay_iso

from . import evaluate as ev
from . import services
from .models import HistoryBatch, MethodDecision, OrderSuggestion, SeriesConfig, SeriesForecast


Z10 = 1.2816  # khoảng 10–90%: trung bình ± 1,28 độ lệch chuẩn
SPREAD = 2 * Z10


def _combine(points):
    """Cộng nhiều dự báo độc lập (mỗi cái có mean, q10, q90): trả (kỳ vọng, thấp, cao) của tổng theo xấp xỉ chuẩn."""
    mean = sum(float(p["mean"]) for p in points)
    var = sum(((float(p["q90"]) - float(p["q10"])) / SPREAD) ** 2 for p in points)
    half = Z10 * var ** 0.5
    return mean, max(0.0, mean - half), mean + half


def _day(d):
    """"Thứ Sáu 30/10" cho đầu chú thích (viết hoa chữ đầu, giữ nguyên phần còn lại)."""
    from .policy import day_label

    text = day_label(d)
    return text[:1].upper() + text[1:]


NARROW = 360  # biểu đồ bản điện thoại: ít ngày hơn, chữ vẫn đọc được mà không phải cuộn ngang


def _sold_vs_expected(dates, past, points, width, height):
    """Số ly đã bán (nét liền) nối số dự kiến (nét đứt, cùng màu vì cùng một đại lượng), dải khoảng thường gặp và vạch
    Hôm nay. points: [(ngày, kỳ vọng, thấp, cao)] từ hôm nay."""
    from apps.reports import charts

    if not points:
        return None
    n_past = len(dates)
    sold = past + [None] * len(points)
    # Đường dự kiến nối từ điểm đã bán cuối cùng để hai đường liền mạch; dải chỉ có ở các ngày dự báo.
    expected = ([None] * (n_past - 1) + [past[-1]] if past else []) + [m for _, m, _, _ in points]
    tips = [f"{_day(d)}: " + ("đóng cửa" if past[k] is None else f"đã bán {past[k]:.0f} ly") for k, d in enumerate(dates)]
    tips += [f"{_day(d)}: dự kiến {m:.0f} ly, thường từ {a:.0f} đến {b:.0f} ly" for d, m, a, b in points]
    return charts.line([f"{d:%d/%m}" for d in dates] + [f"{d:%d/%m}" for d, *_ in points],
                       [{"name": "Đã bán", "values": sold, "slot": 1, "label_end": False},
                        {"name": "Dự kiến", "values": expected, "slot": 1, "dash": True, "label_end": False}],
                       bands=[{"name": "Khoảng thường gặp", "lo": [None] * n_past + [a for _, _, a, _ in points],
                               "hi": [None] * n_past + [b for _, _, _, b in points], "slot": 1}],
                       divider={"index": n_past, "label": "Hôm nay"}, tips=tips,
                       value_fmt=lambda v: f"{v:.0f}" if v is not None else "–", width=width, height=height)


def _by_date(series):
    return {date.fromisoformat(p["date"]): p for p in series.daily}


@capability_required(Cap.FORECASTS)
@require_http_methods(["GET", "POST"])
def overview(request):
    if request.method == "POST":
        rel = services.release(user=request.user)
        record(Action.CREATE, request=request, obj=rel, after={"phien_ban_du_lieu": rel.data_version[:12]})
        messages.success(request, "Đã cập nhật dự báo.")
        return redirect("forecast:overview")
    rel = services.latest_release()
    today = timezone.localdate()
    rows = []
    if rel:
        for s in rel.series.select_related("size", "size__item").order_by("size__item__name", "size__sort_order"):
            days = _by_date(s)
            week = [days[today + timedelta(days=k)] for k in range(7) if today + timedelta(days=k) in days]
            rows.append({"s": s, "days": days, "today": days.get(today), "tomorrow": days.get(today + timedelta(days=1)),
                         "week": _combine(week) if week else None})
    ctx = {"rel": rel, "rows": rows, "today": today, "tomorrow": today + timedelta(days=1)}
    if rows:
        ctx.update(_overview_figures(rows, today))
    return render(request, "forecast/overview.html", ctx)


def _overview_figures(rows, today):
    """Số tổng hôm nay, ngày mai, 7 ngày tới (kèm khoảng thường gặp), biểu đồ tổng số ly 4 tuần qua nối 14 ngày tới,
    và số ly 7 ngày tới của từng món chia theo cỡ."""
    from apps.reports import charts

    from . import planning

    def total(day):
        pts = [r["days"][day] for r in rows if day in r["days"]]
        return _combine(pts) if pts else None

    week_pts = [r["days"][today + timedelta(days=k)] for r in rows for k in range(7)
                if today + timedelta(days=k) in r["days"]]
    week = _combine(week_pts) if week_pts else None
    dates, status, cups, _ = services.history(today, days=28)
    past = [None if status.get(d) == "dong_cua" else sum(series.get(d, 0) for series in cups.values()) for d in dates]
    last7 = [v for d, v in zip(dates, past) if d >= today - timedelta(days=7) and v is not None]
    sold7 = sum(last7) if last7 else None
    # So theo bình quân mỗi ngày có bán: ngày đóng cửa hoặc chưa ghi số bán không làm lệch phần trăm.
    selling = [v for v in last7 if v > 0]
    per_day_sold = sum(selling) / len(selling) if selling else None
    ahead = [today + timedelta(days=k) for k in range(14)]
    fut = [total(d) for d in ahead]
    fut = [(d, t) for d, t in zip(ahead, fut) if t is not None]
    points = [(d, m, a, b) for d, (m, a, b) in fut]
    trend = _sold_vs_expected(dates, past, points, charts.WIDE, 240)
    trend_narrow = _sold_vs_expected(dates[-7:], past[-7:], points, NARROW, 230)
    peak = max(fut[:7], key=lambda x: x[1][0]) if fut else None
    # Theo món: gộp các cỡ của cùng món, mỗi cỡ một màu theo thứ tự cỡ cố định (màu đi theo cỡ, không theo hạng).
    size_names = []
    for r in sorted(rows, key=lambda r: r["s"].size.sort_order):
        if r["s"].size.name not in size_names:
            size_names.append(r["s"].size.name)
    slot_of = {name: k + 1 if k < 3 else "muted" for k, name in enumerate(size_names)}
    items = OrderedDict()
    for r in rows:
        if r["week"] is None:
            continue
        it = items.setdefault(r["s"].size.item.name, {"name": r["s"].size.item.name, "parts": [], "week": []})
        it["parts"].append({"size": r["s"].size.name, "value": r["week"][0], "slot": slot_of[r["s"].size.name]})
        it["week"] += [r["days"][today + timedelta(days=k)] for k in range(7) if today + timedelta(days=k) in r["days"]]
    item_rows = []
    for it in items.values():
        m, a, b = _combine(it["week"])
        item_rows.append({"name": it["name"], "total": m, "lo": a, "hi": b,
                          "parts": sorted(it["parts"], key=lambda p: size_names.index(p["size"]))})
    item_rows.sort(key=lambda x: -x["total"])
    top = max((x["total"] for x in item_rows), default=0) or 1
    for x in item_rows:
        x["pct"] = round(x["total"] / top * 100, 1)
        for p in x["parts"]:
            p["pct"] = round(p["value"] / top * 100, 2)
        sizes = ", ".join(f"cỡ {p['size']} {p['value']:.0f}" for p in x["parts"]) if len(x["parts"]) > 1 else ""
        x["tip"] = (f"{x['name']}: dự kiến {x['total']:.0f} ly trong 7 ngày tới" + (f" ({sizes})" if sizes else "")
                    + f", thường từ {x['lo']:.0f} đến {x['hi']:.0f} ly")
    delta = round((week[0] / 7 - per_day_sold) / per_day_sold * 100) if week and per_day_sold else None
    order_now = order_soon = n_plans = 0
    for p in planning.current_plans():
        n_plans += 1
        label = planning.group_label(p, today)
        order_now += label == "Đặt ngay"
        order_soon += label == "Đặt trong 2 ngày"
    return {"t_today": total(today), "t_tomorrow": total(today + timedelta(days=1)), "t_week": week,
            "sold7": sold7, "week_delta": delta, "week_delta_abs": abs(delta) if delta is not None else None,
            "peak": {"day": peak[0], "mean": peak[1][0]} if peak else None, "trend_chart": trend,
            "trend_narrow": trend_narrow,
            "item_rows": item_rows, "size_legend": [{"name": f"Cỡ {n}", "slot": slot_of[n]} for n in size_names]
            if len(size_names) > 1 else [], "order_now": order_now, "order_soon": order_soon, "has_plans": n_plans > 0}


@capability_required(Cap.FORECASTS)
def series_detail(request, pk):
    from apps.reports import charts

    s = get_object_or_404(SeriesForecast.objects.select_related("size", "size__item", "release"), pk=pk)
    today = timezone.localdate()
    days = _by_date(s)
    dates, status, cups, _ = services.history(today, days=28)
    mine = cups.get(s.size_id, {})
    past = [None if status.get(d) == "dong_cua" else mine.get(d, 0) for d in dates]
    fut = [(today + timedelta(days=k), days[today + timedelta(days=k)]) for k in range(14)
           if today + timedelta(days=k) in days]
    points = [(d, float(p["mean"]), float(p["q10"]), float(p["q90"])) for d, p in fut]
    chart = _sold_vs_expected(dates, past, points, charts.WIDE, 230)
    chart_narrow = _sold_vs_expected(dates[-7:], past[-7:], points, NARROW, 220)
    week = [p for d, p in fut[:7]]
    return render(request, "forecast/series.html", {
        "s": s, "check": services.prior_check(s.size_id), "chart": chart, "chart_narrow": chart_narrow,
        "today_fc": days.get(today),
        "tomorrow_fc": days.get(today + timedelta(days=1)), "tomorrow": today + timedelta(days=1),
        "week": _combine(week) if week else None, "fut": fut})


@capability_required(Cap.FORECASTS)
@require_http_methods(["GET", "POST"])
def ordering(request):
    from apps.inventory import operations as ops
    from apps.inventory.models import Ingredient

    rel = services.latest_release()
    if request.method == "POST":
        ing = get_object_or_404(Ingredient, pk=request.POST.get("ingredient"))
        st = services.ordering_status(ing, rel)
        sug = st.get("suggestion") or {}
        try:
            qty = numbers.qty(request.POST.get("quantity", ""), "Số lượng đặt")
            expected = ops.delivery_date(request.POST.get("expected_date"))
        except ValidationError as error:
            messages.error(request, error.messages[0])
            return redirect("forecast:ordering")
        except ValueError:
            messages.error(request, "Nhập ngày giao dự kiến hợp lệ.")
            return redirect("forecast:ordering")
        note = request.POST.get("note", "").strip()
        suggested = Decimal(str(sug.get("quantity") or 0))
        if qty != suggested and not note:
            messages.error(request, "Số lượng khác đề xuất: ghi lý do.")
            return redirect("forecast:ordering")
        if ing.main_supplier_id is None:
            messages.error(request, f"{ing.name} chưa có nhà cung cấp chính.")
            return redirect("forecast:ordering")
        def save_suggestion(po):
            # Lưu đề xuất trong cùng thao tác chạy một lần: gửi lại biểu mẫu chỉ trả về đơn đã tạo.
            OrderSuggestion.objects.create(
                store=ing.store, release=rel, ingredient=ing, components=_jsonable(st, sug),
                suggested_quantity=suggested, final_quantity=qty, purchase_order=po, decided_by=request.user,
                decision_note=note,
                decision=OrderSuggestion.Decision.ACCEPT if qty == suggested else OrderSuggestion.Decision.EDIT)

        try:
            with transaction.atomic():
                ops.create_purchase_order(request.user, ing.main_supplier_id, ing.pk, qty, expected,
                                          operation_key=request.POST.get("operation_key") or uuid.uuid4().hex,
                                          on_created=save_suggestion)
        except (ValidationError, OperationKeyError) as error:
            for m in getattr(error, "messages", [str(error)]):
                messages.error(request, m)
            return redirect("forecast:ordering")
        messages.success(request, f"Đã ghi lần đặt {numbers.fmt(qty)} {ing.get_unit_display()} {ing.name}.")
        return redirect("forecast:ordering")
    groups = OrderedDict()
    if rel:
        for ing in (Ingredient.objects.filter(is_active=True).exclude(kind="ban_thanh_pham")
                    .select_related("stock", "main_supplier").order_by("name")):
            st = services.ordering_status(ing, rel)
            if not st.get("has_forecast"):
                continue
            st["expected_date"] = timezone.localdate() + timedelta(days=ing.lead_time_days)
            key = ing.main_supplier.name if ing.main_supplier else "Chưa có nhà cung cấp chính"
            groups.setdefault(key, []).append(st)
        for items in groups.values():
            items.sort(key=lambda x: (not x.get("need_order"), x["ingredient"].name))
    return render(request, "forecast/ordering.html", {"rel": rel, "groups": groups, "operation_key": uuid.uuid4().hex,
                                                      "recent": OrderSuggestion.objects.select_related(
                                                          "ingredient", "purchase_order", "decided_by")[:10]})


def _jsonable(st, sug):
    comp = dict(sug.get("components") or {})
    comp.update({"available": st.get("available"), "lots_by_arrival": st.get("lots_by_arrival"),
                 "lead_demand": st.get("lead_demand"), "lead": st.get("lead"),
                 "latest_order_date": str(st.get("latest_order_date") or "")})
    return comp


@capability_required(Cap.FORECASTS)
def evaluation(request):
    from django.conf import settings

    simulated = request.GET.get("mo_phong") == "1" or settings.LAM_FORECAST_INCLUDE_SIMULATED
    result = ev.evaluate(include_simulated=simulated)
    from apps.inventory.models import Ingredient

    names = dict(Ingredient.objects.values_list("pk", "name"))
    weekly = ev.ingredient_weekly()
    for row in weekly:
        row["name"] = names.get(row["ingredient_id"], row["ingredient_id"])
    current = {}
    for r in result["rows"]:
        current[r["size"].pk] = services.method_for(r["size"].pk, has_prior=r["has_prior"])
        r["current_label"] = MethodDecision.Method(current[r["size"].pk]).label
    return render(request, "forecast/evaluation.html", {"result": result, "weekly": weekly, "current": current,
                                                        "accuracy": services.release_accuracy(),
                                                        "simulated": simulated,
                                                        "has_simulated": HistoryBatch.objects.filter(
                                                            kind=HistoryBatch.Kind.SIMULATED, active=True).exists(),
                                                        "methods": dict(MethodDecision.Method.choices),
                                                        "horizons": ev.HORIZONS})


@capability_required(Cap.FORECASTS)
@require_POST
def choose_method(request, size_id):
    from apps.catalog.models import ItemSize

    size = get_object_or_404(ItemSize, pk=size_id)
    method = request.POST.get("method")
    if method not in MethodDecision.Method.values:
        return redirect("forecast:evaluation")
    evidence = {}
    for r in ev.evaluate()["rows"]:
        if r["size"].pk == size.pk:
            evidence = {"delta": r["delta"], "obs_var": r["obs_var"], "verdict": r["verdict"],
                        "split": str(r["split"]), "dispersion": r["dispersion"], "sensitivity": r["sensitivity"],
                        "horizons": {str(h): v for h, v in r["horizons"].items()}}
    if method == MethodDecision.Method.MODEL and evidence.get("verdict") != "mo_hinh_tot_hon" and not request.POST.get("note"):
        messages.error(request, "Đánh giá chưa cho thấy mô hình tốt hơn; ghi lý do nếu vẫn muốn dùng mô hình.")
        return redirect("forecast:evaluation")
    d = MethodDecision.objects.create(store=size.item.store, size=size, method=method, evidence=evidence,
                                      note=request.POST.get("note", "")[:255], decided_by=request.user)
    if method == MethodDecision.Method.MODEL and "delta" in evidence:
        # Cấu hình đánh giá chọn được chỉ áp dụng từ khi Chủ quán duyệt (mục 6.1)
        SeriesConfig.objects.update_or_create(size=size, defaults={
            "delta_level": evidence["delta"], "obs_var": evidence["obs_var"], "evidence": evidence,
            "approved_by": request.user, "approved_at": timezone.now()})
    record(Action.UPDATE, request=request, obj=d, object_type="forecast.MethodDecision",
           after={"mon": str(size), "cach_tinh": d.get_method_display()}, reason=d.note)
    messages.success(request, f"{size.item.name} {size.name}: dùng {d.get_method_display().lower()} cho đặt hàng từ lần "
                              f"phát hành tới.")
    return redirect("forecast:evaluation")


@capability_required(Cap.FORECASTS)
@require_http_methods(["GET", "POST"])
def history_import(request):
    """Nhập lịch sử bán từ tệp CSV; lịch sử thật và dữ liệu mô phỏng lưu riêng, bật tắt từng lần nhập."""
    if request.method == "POST":
        if request.POST.get("action") == "toggle":
            batch = get_object_or_404(HistoryBatch, pk=request.POST.get("batch"))
            batch.active = not batch.active
            batch.save(update_fields=["active", "updated_at"])
            record(Action.STATUS_CHANGE, request=request, obj=batch, object_type="forecast.HistoryBatch",
                   after={"dang_dung": batch.active})
            messages.success(request, f"{'Bật' if batch.active else 'Tắt'} lần nhập {batch.file_name}.")
            return redirect("forecast:history")
        f = request.FILES.get("file")
        kind = request.POST.get("kind")
        if not f or kind not in HistoryBatch.Kind.values:
            messages.error(request, "Chọn tệp CSV hoặc Excel và loại dữ liệu.")
            return redirect("forecast:history")
        try:
            batch = services.import_history(f, f.name, kind, request.user, request.POST.get("note", ""))
        except UnicodeDecodeError:
            messages.error(request, "Không đọc được tệp: chữ trong tệp không phải mã UTF-8. Trong Excel chọn Lưu thành "
                                    "\"CSV UTF-8\" rồi nhập lại, hoặc nhập thẳng tệp .xlsx.")
            return redirect("forecast:history")
        except (ValueError, ValidationError) as error:
            messages.error(request, "Không nhập được tệp: " + " ".join(errors.messages_of(error)))
            return redirect("forecast:history")
        sm = batch.summary
        messages.success(request, f"Đã nhập {numbers.fmt(sm['cups'], 0)} ly trong {sm['days']} ngày "
                                  f"({ngay_iso(sm['from'])} đến {ngay_iso(sm['to'])}).")
        skipped = ([f"{sm['bad_rows']} dòng không đọc được ngày hoặc số ly"] if sm.get("bad_rows") else []) + \
                  ([f"{sm['future']} dòng từ hôm nay trở đi"] if sm.get("future") else [])
        if skipped:
            messages.warning(request, "Đã bỏ qua " + ", ".join(skipped) + ".")
        if sm.get("unmatched"):
            messages.warning(request, "Món không khớp thực đơn (chưa nhập): " +
                             "; ".join(f"{k} ({v} dòng)" for k, v in sm["unmatched"].items()))
        return redirect("forecast:history")
    return render(request, "forecast/history.html", {"batches": HistoryBatch.objects.select_related("imported_by"),
                                                     "kinds": HistoryBatch.Kind.choices})


# ---------------- Kế hoạch mua nguyên liệu (thiết kế mua nguyên liệu mục 9) ----------------

def _d(value):
    """Ngày lưu dạng ISO trong kết quả tính → date để hiển thị."""
    from datetime import date

    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


RUNWAY_DAYS = 14  # thanh "còn đủ dùng" đầy khi đủ từ 14 ngày trở lên


def _plan_view(plan):
    from . import policy

    r = dict(plan.result or {})
    cfg = r.get("settings") or {}
    for k in ("risk_date", "stockout_date", "order_by", "next_review", "today", "expedite_day"):
        r[k] = _d(r.get(k))
    for k in ("window_s", "window_S"):
        r[k] = [_d(x) for x in r.get(k) or []]
    r["window_S_end"] = r["window_S"][-1] if r["window_S"] else None
    for k in ("counted_lots", "uncounted_lots", "excluded_lots"):
        r[k] = [{**lot, "arrival": _d(lot.get("arrival"))} for lot in r.get(k) or []]
    r["timeline"] = [{**row, "date": _d(row.get("date"))} for row in r.get("timeline") or []]
    r["periods"] = [{**p, "from": _d(p.get("from")), "to": _d(p.get("to"))} for p in r.get("periods") or []]
    fc = dict(plan.forecast or {})
    fc["seasonal"] = [{**a, "share_pct": round(a["share"] * 100) if a.get("share") is not None else None}
                      for a in fc.get("seasonal") or []]
    cover = r.get("cover_days")
    return {"plan": plan, "r": r, "cfg": cfg, "fc": fc, "action_label": policy.ACTION_LABELS.get(plan.action, ""),
            "group": planning_group(plan), "cover_pct": round(min(cover, RUNWAY_DAYS) / RUNWAY_DAYS * 100)
            if cover is not None else 100}


def planning_group(plan):
    from . import planning

    return planning.group_label(plan, timezone.localdate())


@capability_required(Cap.FORECASTS)
@require_http_methods(["GET", "POST"])
def plans(request):
    """Danh sách nguyên liệu theo ngày phải đặt: Đặt ngay, Đặt trong 2 ngày, Theo dõi, Đủ hàng (mục 9.2)."""
    from . import planning
    from .models import PlanRun

    if request.method == "POST" and request.POST.get("action") == "tinh_lai":
        run = planning.run_full(user=request.user, kind=PlanRun.Kind.MANUAL)
        record(Action.CREATE, request=request, obj=run, object_type="forecast.PlanRun",
               after={"nguyen_lieu": run.summary.get("nguyen_lieu"), "hanh_dong": run.summary.get("hanh_dong")})
        messages.success(request, f"Đã tính lại kế hoạch mua cho {run.summary.get('nguyen_lieu', 0)} nguyên liệu.")
        return redirect("forecast:plans")
    if request.method == "POST" and request.POST.get("action") in ("doi_cach", "giu_cach"):
        accept = request.POST["action"] == "doi_cach"
        try:
            if not request.user.is_owner:
                raise ValidationError("Chỉ Chủ quán duyệt đổi cách dự báo.")
            planning.decide_switch(request.user, request.POST.get("key", ""), accept)
        except (ValidationError, ValueError) as error:
            for m in errors.messages_of(error):
                messages.error(request, m)
            return redirect("forecast:plans")
        if accept:
            planning.run_full(user=request.user, kind=PlanRun.Kind.MANUAL)
            messages.success(request, "Đã đổi cách dự báo và tính lại kế hoạch mua.")
        else:
            messages.success(request, "Giữ cách dự báo hiện tại; đề xuất này không nhắc lại trong 4 tuần.")
        return redirect("forecast:plans")
    from . import policy

    today = timezone.localdate()
    rows = sorted(planning.current_plans(), key=lambda p: planning.sort_key(p, today))
    # Việc cần làm lên trước, mỗi nhóm một bảng; Đủ hàng gập lại, tách riêng nguyên liệu chưa dùng tới trong tầm dự báo.
    groups = OrderedDict((k, []) for k in ("Đặt ngay", "Đặt trong 2 ngày", "Theo dõi", "Chưa đủ dữ liệu"))
    enough, unused = [], []
    for p in rows:
        v = _plan_view(p)
        label = "Chưa đủ dữ liệu" if p.action == policy.NO_DATA else planning.group_label(p, today)
        if label != "Đủ hàng":
            groups[label].append(v)
        elif any(row.get("demand") for row in v["r"]["timeline"]):
            enough.append(v)
        else:
            unused.append(v)
    anchors = {"Đặt ngay": "dat-ngay", "Đặt trong 2 ngày": "dat-trong-2-ngay", "Theo dõi": "theo-doi",
               "Chưa đủ dữ liệu": "chua-du-du-lieu"}
    counts = {"now": len(groups["Đặt ngay"]), "soon": len(groups["Đặt trong 2 ngày"]), "watch": len(groups["Theo dõi"]),
              "enough": len(enough) + len(unused)}
    groups = [{"label": k, "id": anchors[k], "items": v} for k, v in groups.items() if v]
    last_run = PlanRun.objects.filter(kind__in=[PlanRun.Kind.FULL, PlanRun.Kind.MANUAL]).first()
    proposals = [{**p, "gain_pct": round(p["gain"] * 100)} for p in planning.proposals(today)]
    return render(request, "forecast/plans.html", {"groups": groups, "enough": enough, "unused": unused,
                                                   "counts": counts, "last_run": last_run, "today": today,
                                                   "proposals": proposals, "can_decide": request.user.is_owner})


@capability_required(Cap.FORECASTS)
@require_http_methods(["GET", "POST"])
def plan_detail(request, ingredient_id):
    """Chi tiết một nguyên liệu và bốn thao tác: Chấp nhận, Sửa rồi chấp nhận, Bỏ qua, Đã báo nhà cung cấp."""
    from apps.inventory import operations as ops
    from apps.inventory.models import Ingredient, PurchaseOrder

    from . import planning
    from .models import IngredientPlan

    ing = get_object_or_404(Ingredient.objects.select_related("main_supplier"), pk=ingredient_id)
    if ing.is_semi:  # bán thành phẩm không mua: xem nhu cầu và số mẻ nên làm ở trang làm bán thành phẩm
        return redirect("inventory:semi")
    if request.method == "POST":
        p = request.POST
        action = p.get("action")
        try:
            if action in ("chap_nhan", "bo_qua"):
                plan = get_object_or_404(IngredientPlan, pk=p.get("plan"), ingredient=ing)
                if action == "chap_nhan":
                    qty = numbers.qty(p.get("quantity", ""), "Số lượng đặt")
                    expected = ops.delivery_date(p.get("expected_date"))
                    po = planning.accept(request.user, plan, qty, p.get("note", ""), expected,
                                         p.get("operation_key") or uuid.uuid4().hex)
                    messages.success(request, f"Đã tạo đơn Nháp {numbers.fmt(po.quantity)} {ing.get_unit_display()} "
                                              f"{ing.name}. Báo nhà cung cấp rồi bấm Đã báo nhà cung cấp.")
                else:
                    planning.skip(request.user, plan, p.get("reason", ""), p.get("operation_key") or uuid.uuid4().hex)
                    messages.success(request, f"Đã bỏ qua đề xuất {ing.name}; đề xuất vẫn được lưu để đánh giá.")
            elif action == "da_bao_ncc":
                expected = p.get("expected_date")
                ops.mark_ordered(request.user, p.get("po"), ops.delivery_date(expected) if expected else None)
                messages.success(request, "Đơn đã chuyển sang Đã đặt.")
            elif action == "huy_don":
                ops.cancel_order(request.user, p.get("po"), p.get("reason", ""))
                messages.success(request, "Đã hủy đơn.")
        except ValueError:
            messages.error(request, "Nhập ngày giao dự kiến hợp lệ.")
        except (ValidationError, OperationKeyError) as error:
            for m in getattr(error, "messages", [str(error)]):
                messages.error(request, m)
        return redirect("forecast:plan", ingredient_id=ing.pk)
    plan = IngredientPlan.objects.filter(ingredient=ing, is_current=True).first()
    ctx = _plan_view(plan) if plan else {"plan": None}
    if plan:
        ctx.update(_plan_figures(ctx["r"], ctx["cfg"]))
    ctx.update({
        "ing": ing, "operation_key": uuid.uuid4().hex,
        "expected_date": timezone.localdate() + timedelta(days=ing.exposure_days),
        "orders": PurchaseOrder.objects.filter(ingredient=ing).exclude(
            status__in=[PurchaseOrder.Status.DELIVERED, PurchaseOrder.Status.CANCELLED]).order_by("expected_date"),
        "decisions": OrderSuggestion.objects.filter(ingredient=ing, plan__isnull=False).select_related(
            "decided_by", "purchase_order")[:10],
        "today": timezone.localdate(),
    })
    return render(request, "forecast/plan.html", ctx)


def _plan_figures(r, cfg):
    """Biểu đồ tồn cuối ngày 14 ngày tới: nếu không đặt thêm và nếu đặt hôm nay đúng số đề xuất; mức dùng mỗi ngày."""
    from apps.reports import charts

    rows = r["timeline"][:14]
    if not rows:
        return {"has_demand": False}
    unit = cfg.get("unit", "")
    demand7 = sum(float(x["demand"] or 0) for x in rows[:7])
    with_order = (r.get("with_order") or [])[:len(rows)] if r.get("packs") else []

    def amount(v):
        return f"còn {numbers.fmt(v, 0)} {unit}" if v >= 0 else f"thiếu {numbers.fmt(-v, 0)} {unit}"

    tips = []
    for k, x in enumerate(rows):
        parts = [f"dùng khoảng {numbers.fmt(x['demand'], 0)} {unit}"]
        if x.get("arriving"):
            parts.append(f"hàng về {numbers.fmt(x['arriving'], 0)} {unit}")
        if with_order:
            parts += [f"không đặt thêm: {amount(x['level'])}", f"đặt theo đề xuất: {amount(with_order[k])}"]
        else:
            parts.append(f"cuối ngày {amount(x['level'])}")
        tips.append(f"{_day(x['date'])}" + (" (đóng cửa)" if x.get("closed") else "") + ": "
                    + "; ".join(parts))
    series = []
    if with_order:
        series.append({"name": "Nếu đặt hôm nay theo đề xuất", "values": with_order, "slot": 1, "label_end": False})
        series.append({"name": "Nếu không đặt thêm", "values": [x["level"] for x in rows], "slot": 2,
                       "label_end": False})
    else:
        series.append({"name": "Tồn cuối ngày", "values": [x["level"] for x in rows], "slot": 1, "label_end": False})
    risk = r.get("risk_date")
    idx = next((k for k, x in enumerate(rows) if risk and x["date"] == risk), None)
    divider = {"index": idx, "label": "Có thể thiếu"} if idx is not None else None
    labels = [f"{x['date']:%d/%m}" for x in rows]
    chart = charts.line(labels, series, tips=tips, value_fmt=charts.fmt, divider=divider, width=charts.WIDE,
                        height=230)
    narrow = charts.line(labels, series, tips=tips, value_fmt=charts.fmt, divider=divider, width=NARROW, height=220)
    until = None
    for x, level in zip(rows, with_order):
        if level < 0:
            break
        until = x["date"]
    return {"stock_chart": chart, "stock_narrow": narrow, "per_day": demand7 / min(len(rows), 7), "demand7": demand7,
            "order_until": until, "has_demand": any(float(x["demand"] or 0) > 0 for x in r["timeline"])}


DEMAND_WORDS = {"deu": "Đều", "dao_dong": "Dao động mạnh", "lac_dac": "Lác đác", "thua_tho": "Lác đác, dao động mạnh"}


def _week_error(fc):
    """Sai số và độ chệch của dự báo đang dùng cho tổng 7 ngày (hoặc cửa sổ đặt hàng nếu chưa đo được 7 ngày), theo
    phần trăm của lượng thực tế. Độ chệch dương: thực tế cao hơn dự báo."""
    by = (fc.get("errors") or {}).get(fc.get("method")) or {}
    st = by.get("7") or by.get(str(fc.get("decision_h"))) or {}
    if not st or st.get("wape") is None:
        return None, None, 0
    mean = st["mae"] / st["wape"] if st.get("wape") else None
    bias = round(st["bias"] / mean * 100, 1) if mean else 0.0
    return round(st["wape"] * 100, 1), bias, st.get("n", 0)


@capability_required(Cap.FORECASTS)
def accuracy(request):
    """Độ chính xác của dự báo cho kế hoạch mua, ba tầng: số ly bán, lượng nguyên liệu theo định mức, lượng thực dùng
    trong sổ kho; kèm ngày thiếu hàng và lượng hết hạn 8 tuần. Chỉ hiện kết quả, không hiện cách tính."""
    from . import planning
    from .models import PlanRun

    run = PlanRun.objects.filter(kind__in=[PlanRun.Kind.FULL, PlanRun.Kind.MANUAL]).first()
    total = (run.summary or {}).get("tong") if run else None
    if total:
        total = {**total, "wape_pct": round(total["wape_7"] * 100, 1) if total.get("wape_7") is not None else None,
                 "item_pct": round(total["item_wape_1"] * 100, 1) if total.get("item_wape_1") is not None else None}
    rows = []
    order = {"A": 0, "B": 1, "C": 2}
    for plan in planning.current_plans():
        fc = plan.forecast or {}
        rates = fc.get("rates") or {}
        wape, bias, n = _week_error(fc)
        cls = fc.get("demand_class") or {}
        ub = rates.get("ub_8w") or 0
        recon = rates.get("recon") or {}
        rows.append({
            "ing": plan.ingredient, "unit": plan.ingredient.get_unit_display(), "abc": fc.get("abc", "C"),
            "demand": DEMAND_WORDS.get(cls.get("kind"), "Chưa đủ dữ liệu"), "wape": wape, "bias": bias, "n": n,
            "measured": fc.get("stage") == "mo_hinh", "stockout_days": rates.get("blocked_days", 0),
            "expired": rates.get("waste_stock_8w", 0), "expired_pct": round(rates.get("waste_stock_8w", 0) / ub * 100, 1)
            if ub else None, "recon_pct": round(recon.get("gap", 0) * 100, 1) if recon.get("ledger") else None,
            "recon_flag": recon.get("flag"), "waste_pct": round((rates.get("r_vh") or 0) * 100, 1), "used": ub > 0})
    # Nguyên liệu chưa dùng tới (không có lượng dùng 8 tuần, chưa đo được sai số) chỉ đếm, không liệt kê.
    unused = [r for r in rows if r["wape"] is None and not r["used"]]
    rows = [r for r in rows if r["wape"] is not None or r["used"]]
    rows.sort(key=lambda r: (r["wape"] is None, -(r["wape"] or 0), order.get(r["abc"], 3), r["ing"].name))
    measured = [r for r in rows if r["wape"] is not None]
    top = max((r["wape"] for r in measured), default=0) or 1
    for r in measured:
        r["pct"] = round(r["wape"] / top * 100, 1)
        lean = ("dùng nhiều hơn dự báo" if r["bias"] > 0 else "dùng ít hơn dự báo") if r["bias"] else "không lệch hẳn về phía nào"
        r["tip"] = (f"{r['ing'].name}: sai số tổng 7 ngày {numbers.fmt(r['wape'], 1)}%"
                    + (f"; thực tế thường {lean} {numbers.fmt(abs(r['bias']), 1)}%" if r["bias"] else f"; {lean}")
                    + ("; số tạm, chưa đủ 8 tuần dữ liệu" if not r["measured"] else ""))
    figures = {"stockout_days": sum(r["stockout_days"] for r in rows),
               "stockout_items": sum(1 for r in rows if r["stockout_days"]),
               "expired_items": [r for r in rows if r["expired"]],
               "recon_flags": sum(1 for r in rows if r["recon_flag"])}
    return render(request, "forecast/accuracy.html", {"total": total, "rows": rows, "measured": measured,
                                                      "unused": len(unused), "figures": figures, "run": run})
