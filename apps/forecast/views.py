"""Màn hình dự báo nhu cầu, đặt hàng đề xuất và đánh giá dự báo (chỉ Chủ quán, Bảng 5.3: Cap.FORECASTS)."""

import uuid
from collections import OrderedDict
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST

from apps.accounts.permissions import Cap, capability_required
from apps.audit.models import Action
from apps.audit.services import record
from apps.core.idempotency import OperationKeyError

from . import evaluate as ev
from . import services
from .models import HistoryBatch, MethodDecision, OrderSuggestion, SeriesConfig, SeriesForecast


@capability_required(Cap.FORECASTS)
@require_http_methods(["GET", "POST"])
def overview(request):
    if request.method == "POST":
        rel = services.release(user=request.user)
        record(Action.CREATE, request=request, obj=rel, after={"phien_ban_du_lieu": rel.data_version[:12]})
        messages.success(request, "Đã phát hành dự báo mới.")
        return redirect("forecast:overview")
    rel = services.latest_release()
    rows = []
    if rel:
        for s in rel.series.select_related("size", "size__item").order_by("size__item__name", "size__sort_order"):
            rows.append({"s": s, "method_label": MethodDecision.Method(s.method).label,
                         "tomorrow": s.daily[1] if len(s.daily) > 1 else None,
                         "t3": s.totals.get("3"), "t7": s.totals.get("7")})
    return render(request, "forecast/overview.html", {"rel": rel, "rows": rows,
                                                      "methods": dict(MethodDecision.Method.choices)})


@capability_required(Cap.FORECASTS)
def series_detail(request, pk):
    s = get_object_or_404(SeriesForecast.objects.select_related("size", "size__item", "release"), pk=pk)
    return render(request, "forecast/series.html", {"s": s, "method_label": MethodDecision.Method(s.method).label,
                                                    "check": services.prior_check(s.size_id)})


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
            qty = Decimal(str(request.POST.get("quantity", "")).replace(",", "."))
            expected = timezone.datetime.fromisoformat(request.POST.get("expected_date", "")).date()
        except (InvalidOperation, ValueError):
            messages.error(request, "Nhập số lượng và ngày giao dự kiến hợp lệ.")
            return redirect("forecast:ordering")
        note = request.POST.get("note", "").strip()
        suggested = Decimal(str(sug.get("quantity") or 0))
        if qty != suggested and not note:
            messages.error(request, "Số lượng khác đề xuất: ghi lý do (BRU-24, NFR-22).")
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
        messages.success(request, f"Đã ghi lần đặt {qty.normalize():f} {ing.get_unit_display()} {ing.name}.")
        return redirect("forecast:ordering")
    groups = OrderedDict()
    if rel:
        for ing in Ingredient.objects.filter(is_active=True).select_related("stock", "main_supplier").order_by("name"):
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
            messages.error(request, "Chọn tệp CSV và loại dữ liệu.")
            return redirect("forecast:history")
        try:
            batch = services.import_history(f, f.name, kind, request.user, request.POST.get("note", ""))
        except (ValueError, UnicodeDecodeError) as error:
            messages.error(request, f"Không đọc được tệp: {error}")
            return redirect("forecast:history")
        sm = batch.summary
        messages.success(request, f"Đã nhập {sm['cups']} ly trong {sm['days']} ngày ({sm['from']} đến {sm['to']}).")
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


def _plan_view(plan):
    from . import methods, policy

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
    fc = plan.forecast or {}
    return {"plan": plan, "r": r, "cfg": cfg, "fc": fc, "action_label": policy.ACTION_LABELS.get(plan.action, ""),
            "method_label": methods.METHOD_LABELS.get(fc.get("method"), "Chưa có"),
            "stage_label": methods.STAGE_LABELS.get(fc.get("stage"), ""),
            "group": planning_group(plan)}


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
        record(Action.CREATE, request=request, obj=run, object_type="forecast.PlanRun", after=run.summary)
        messages.success(request, f"Đã tính lại kế hoạch mua cho {run.summary.get('nguyen_lieu', 0)} nguyên liệu.")
        return redirect("forecast:plans")
    today = timezone.localdate()
    rows = sorted(planning.current_plans(), key=lambda p: planning.sort_key(p, today))
    groups = OrderedDict()
    for p in rows:
        groups.setdefault(planning.group_label(p, today), []).append(_plan_view(p))
    last_run = PlanRun.objects.filter(kind__in=[PlanRun.Kind.FULL, PlanRun.Kind.MANUAL]).first()
    return render(request, "forecast/plans.html", {"groups": groups, "last_run": last_run, "today": today})


@capability_required(Cap.FORECASTS)
@require_http_methods(["GET", "POST"])
def plan_detail(request, ingredient_id):
    """Chi tiết một nguyên liệu và bốn thao tác: Chấp nhận, Sửa rồi chấp nhận, Bỏ qua, Đã báo nhà cung cấp."""
    from apps.inventory import operations as ops
    from apps.inventory.models import Ingredient, PurchaseOrder

    from . import planning
    from .models import IngredientPlan

    ing = get_object_or_404(Ingredient.objects.select_related("main_supplier"), pk=ingredient_id)
    if request.method == "POST":
        p = request.POST
        action = p.get("action")
        try:
            if action in ("chap_nhan", "bo_qua"):
                plan = get_object_or_404(IngredientPlan, pk=p.get("plan"), ingredient=ing)
                if action == "chap_nhan":
                    qty = Decimal(str(p.get("quantity", "")).replace(",", "."))
                    expected = timezone.datetime.fromisoformat(p.get("expected_date", "")).date()
                    po = planning.accept(request.user, plan, qty, p.get("note", ""), expected,
                                         p.get("operation_key") or uuid.uuid4().hex)
                    messages.success(request, f"Đã tạo đơn Nháp {po.quantity.normalize():f} {ing.get_unit_display()} "
                                              f"{ing.name}. Báo nhà cung cấp rồi bấm Đã báo nhà cung cấp.")
                else:
                    planning.skip(request.user, plan, p.get("reason", ""), p.get("operation_key") or uuid.uuid4().hex)
                    messages.success(request, f"Đã bỏ qua đề xuất {ing.name}; đề xuất vẫn được lưu để đánh giá.")
            elif action == "da_bao_ncc":
                expected = p.get("expected_date")
                ops.mark_ordered(request.user, p.get("po"),
                                 timezone.datetime.fromisoformat(expected).date() if expected else None)
                messages.success(request, "Đơn đã chuyển sang Đã đặt.")
            elif action == "huy_don":
                ops.cancel_order(request.user, p.get("po"), p.get("reason", ""))
                messages.success(request, "Đã hủy đơn.")
        except (InvalidOperation, ValueError):
            messages.error(request, "Nhập số lượng và ngày giao dự kiến hợp lệ.")
        except (ValidationError, OperationKeyError) as error:
            for m in getattr(error, "messages", [str(error)]):
                messages.error(request, m)
        return redirect("forecast:plan", ingredient_id=ing.pk)
    plan = IngredientPlan.objects.filter(ingredient=ing, is_current=True).first()
    ctx = _plan_view(plan) if plan else {"plan": None}
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
