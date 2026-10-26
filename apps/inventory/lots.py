"""Quản lý kho theo lô: thứ tự lấy lô, phân bổ biến động vào lô, trạng thái hạn dùng và dự kiến dùng kịp.

Quy tắc xuất (Ingredient.issue_rule):
- FEFO, hết hạn trước xuất trước: mặc định. Lô có hạn sớm hơn lấy trước; lô không ghi hạn xếp sau, giữa chúng
  là nhập trước xuất trước. Vì vậy hàng không có hạn dùng (ly, ống hút, nắp) thực chất được xuất FIFO.
- FIFO, nhập trước xuất trước: theo ngày nhập, bỏ qua hạn. Dùng khi hạn của các lô luôn tăng theo ngày nhập.
- LIFO, nhập sau xuất trước: chỉ cho hàng không có hạn dùng mà lô mới nằm trên, dễ lấy (đá viên, bao than).
  Không dùng để tính giá trị tồn: Thông tư 200/2014/TT-BTC đã bỏ phương pháp này; giá trị tồn ở đây tính theo
  giá thực tế đích danh của từng lô.
Mọi quy tắc đều để lô đã quá hạn xuống cuối: không bao giờ gợi ý lấy lô quá hạn khi còn lô dùng được.

Phân bổ (gọi từ stock.move, trong cùng giao dịch):
- Nhập hàng và tồn đầu kỳ tạo lô mới. Nếu sổ kho đang âm (đã pha khi sổ ghi thiếu), lô mới bù phần âm trước.
- Pha chế, hao hụt, thiếu khi kiểm kê trừ lần lượt theo thứ tự lấy lô. Hao hụt vì hết hạn và thiếu khi kiểm kê
  trừ lô quá hạn trước, vì đó là phần dễ đã bị bỏ đi mà chưa ghi.
- Dư khi kiểm kê trả lại các lô còn dùng được đã bị trừ (theo thứ tự lấy lô), phần còn lại thành lô "Dư khi kiểm kê".
Bất biến: lô.còn lại = tổng LotDraw của lô; tổng còn lại các lô = max(tồn vật lý, 0).
"""

import math
from datetime import timedelta
from decimal import Decimal

from django.db.models import Min, Sum
from django.utils import timezone

from apps.core import params

from .models import IssueRule, LotDraw, StockLot, StockMovement

EXPIRED, NEAR, OK, UNKNOWN, EMPTY = "qua_han", "sap_het_han", "con_han", "chua_ro_han", "da_dung_het"
STATUS_LABELS = {EXPIRED: "Quá hạn", NEAR: "Sắp hết hạn", OK: "Còn hạn", UNKNOWN: "Chưa rõ hạn", EMPTY: "Đã dùng hết"}
USAGE_WINDOW_DAYS = 28  # tốc độ dùng để dự kiến lô hết khi nào: trung bình 4 tuần gần nhất
PROJECTION_DAYS = 400


# ---------------- Hàm thuần: không đọc cơ sở dữ liệu ----------------

def is_expired(lot, today):
    return lot.expiry_date is not None and lot.expiry_date < today


def _rule_key(rule):
    if rule == IssueRule.FIFO:
        return lambda l: (l.received_at, l.pk or 0)
    if rule == IssueRule.LIFO:
        return lambda l: (-l.received_at.timestamp(), -(l.pk or 0))
    return lambda l: (l.expiry_date is None, l.expiry_date or l.received_at.date(), l.received_at, l.pk or 0)


def issue_order(lots, rule, today, prefer=None, expired_first=False):
    """Thứ tự lấy lô: lô còn dùng được theo quy tắc, rồi lô quá hạn (hạn sớm trước).

    expired_first: đặt lô quá hạn lên đầu (hao hụt vì hết hạn, thiếu khi kiểm kê). prefer: lô người dùng chọn."""
    usable = sorted((l for l in lots if not is_expired(l, today)), key=_rule_key(rule))
    expired = sorted((l for l in lots if is_expired(l, today)), key=lambda l: (l.expiry_date, l.received_at, l.pk or 0))
    seq = expired + usable if expired_first else usable + expired
    if prefer is not None:
        seq = [l for l in seq if l.pk == prefer] + [l for l in seq if l.pk != prefer]
    return seq


def near_days(shelf_life_days, days=None, percent=None):
    """Số ngày trước hạn bắt đầu báo Sắp hết hạn: lấy số lớn hơn giữa số ngày cố định và một phần hạn dùng."""
    days = params.get("lot_near_expiry_days") if days is None else days
    percent = params.get("lot_near_expiry_percent") if percent is None else percent
    return max(days, math.ceil((shelf_life_days or 0) * percent / 100))


def status(lot, today, near):
    if lot.remaining <= 0:
        return EMPTY
    if lot.expiry_date is None:
        return UNKNOWN
    left = (lot.expiry_date - today).days
    if left < 0:
        return EXPIRED
    return NEAR if left <= near else OK


def project(ordered, rate, today, horizon=PROJECTION_DAYS):
    """Dự kiến từng lô dùng hết ngày nào và bao nhiêu sẽ quá hạn trước khi kịp dùng.

    Mỗi ngày dùng `rate`, lấy theo thứ tự `ordered`; hết ngày ghi trên hạn mà lô còn thì phần còn lại coi như bỏ.
    Trả về {lot.pk: {"start": ngày bắt đầu lấy, "used_up": ngày dùng hết hoặc None, "waste": lượng}}. rate = 0: lô có hạn coi như bỏ hết khi tới hạn."""
    left = [float(l.remaining) for l in ordered]
    out = {l.pk: {"used_up": None, "waste": 0.0, "start": None} for l in ordered}
    rate = max(float(rate or 0), 0.0)
    for day in range(horizon):
        d = today + timedelta(days=day)
        for i, lot in enumerate(ordered):
            if left[i] > 1e-9 and lot.expiry_date is not None and lot.expiry_date < d:
                out[lot.pk]["waste"] += left[i]
                left[i] = 0.0
        need = rate
        for i, lot in enumerate(ordered):
            if need <= 1e-9:
                break
            if left[i] <= 1e-9:
                continue
            take = min(left[i], need)
            left[i] -= take
            need -= take
            if out[lot.pk]["start"] is None:
                out[lot.pk]["start"] = d
            if left[i] <= 1e-9:
                left[i] = 0.0
                out[lot.pk]["used_up"] = d
        if not any(x > 1e-9 for x in left):
            break
    return out


# ---------------- Phân bổ biến động vào lô ----------------

def _draw(lot, movement, qty, note=""):
    lot.remaining += qty
    lot.save(update_fields=["remaining", "updated_at"])
    LotDraw.objects.create(lot=lot, movement=movement, quantity=qty, note=note[:120],
                           created_at=movement.created_at if movement else timezone.now())


def _open_lots(ingredient_id):
    return list(StockLot.objects.select_for_update().filter(ingredient_id=ingredient_id, remaining__gt=0))


def new_lot_code(store, prefix):
    """Mã lô duy nhất trong cửa hàng; prefix đã đủ phân biệt (mã phiếu nhập, mã kiểm kê), thêm số khi trùng."""
    code, n = prefix[:24], 1
    while StockLot.objects.filter(store=store, code=code).exists():
        n += 1
        code = f"{prefix[:20]}-{n}"
    return code


def record(ingredient, movement, before, delta, *, new_lot=None, prefer=None, expired_first=False):
    """Phân bổ một biến động `delta` (đã ghi vào `movement`) vào các lô của nguyên liệu. `before`: tồn vật lý trước."""
    today = timezone.localdate(movement.created_at)
    if delta > 0:
        deficit = max(-before, Decimal(0))
        if new_lot is not None or movement.kind in (StockMovement.Kind.RECEIPT, StockMovement.Kind.OPENING):
            return _receive(ingredient, movement, delta, deficit, new_lot or {}, today)
        return _surplus(ingredient, movement, delta - min(deficit, delta), today)
    need = min(-delta, max(before, Decimal(0)))
    if need <= 0:
        return []
    drawn = []
    for lot in issue_order(_open_lots(ingredient.pk), ingredient.rule, today, prefer=prefer,
                           expired_first=expired_first):
        if need <= 0:
            break
        take = min(lot.remaining, need)
        _draw(lot, movement, -take, "Lấy từ lô quá hạn" if is_expired(lot, today) else "")
        drawn.append((lot, take))
        need -= take
    return drawn


def _receive(ingredient, movement, qty, deficit, spec, today):
    expiry, estimated = spec.get("expiry_date"), False
    received = movement.created_at
    if expiry is None and ingredient.shelf_life_days and movement.kind == StockMovement.Kind.RECEIPT:
        expiry, estimated = timezone.localdate(received) + timedelta(days=ingredient.shelf_life_days - 1), True
    source = spec.get("source") or (StockLot.Source.RECEIPT if movement.kind == StockMovement.Kind.RECEIPT
                                    else StockLot.Source.OPENING)
    prefix = spec.get("code") or (f"DK{timezone.localtime(received):%y%m%d}-{ingredient.pk}"
                                  if source == StockLot.Source.OPENING else f"L{movement.pk}")
    lot = StockLot.objects.create(
        store=ingredient.store, ingredient=ingredient, code=new_lot_code(ingredient.store, prefix),
        supplier_lot=(spec.get("supplier_lot") or "")[:40], source=source, receipt_line=spec.get("receipt_line"),
        supplier=spec.get("supplier"), received_at=received, expiry_date=expiry, expiry_estimated=estimated,
        quantity=qty, remaining=0, unit_cost=spec.get("unit_cost"))
    _draw(lot, movement, qty)
    if deficit > 0:
        _draw(lot, movement, -min(deficit, qty), "Bù phần sổ kho âm trước khi nhập")
    return [(lot, qty)]


def _surplus(ingredient, movement, qty, today):
    if qty <= 0:
        return []
    out = []
    candidates = [l for l in StockLot.objects.select_for_update().filter(ingredient=ingredient)
                  if l.remaining < l.quantity and not is_expired(l, today)]
    for lot in issue_order(candidates, ingredient.rule, today):
        if qty <= 0:
            break
        back = min(lot.quantity - lot.remaining, qty)
        _draw(lot, movement, back, "Trả lại phần đã trừ (dư khi kiểm kê)")
        out.append((lot, back))
        qty -= back
    if qty > 0:
        lot = StockLot.objects.create(
            store=ingredient.store, ingredient=ingredient, code=new_lot_code(ingredient.store, f"KK{movement.pk}"),
            source=StockLot.Source.COUNT, received_at=movement.created_at, quantity=qty, remaining=0)
        _draw(lot, movement, qty)
        out.append((lot, qty))
    return out


# ---------------- Đọc: trạng thái lô cho màn hình và cảnh báo ----------------

def daily_usage(ingredient_ids=None, today=None, days=USAGE_WINDOW_DAYS):
    """Lượng dùng bình quân mỗi ngày (pha chế) trong `days` ngày gần nhất: {ingredient_id: số}.

    Nguyên liệu mới theo dõi chưa đủ `days` ngày thì chia cho số ngày đã có sổ kho, để không tính thiếu tốc độ dùng."""
    today = today or timezone.localdate()
    since = today - timedelta(days=days)
    rows = StockMovement.objects.filter(kind=StockMovement.Kind.CONSUME, created_at__date__gt=since,
                                        created_at__date__lte=today)
    if ingredient_ids is not None:
        rows = rows.filter(ingredient_id__in=ingredient_ids)
    sums = {r["ingredient_id"]: float(-r["s"]) for r in rows.values("ingredient_id").annotate(s=Sum("quantity"))
            if r["s"]}
    first = dict(StockMovement.objects.filter(ingredient_id__in=list(sums)).values("ingredient_id")
                 .annotate(f=Min("created_at")).values_list("ingredient_id", "f"))
    out = {}
    for ing, used in sums.items():
        start = timezone.localdate(first[ing]) if first.get(ing) else since
        out[ing] = used / max(1, min(days, (today - start).days + 1))
    return out


def latest_costs(ingredient_ids=None):
    """Đơn giá nhập gần nhất của mỗi nguyên liệu, dùng định giá lô không có đơn giá (tồn đầu kỳ, dư kiểm kê)."""
    rows = StockLot.objects.filter(unit_cost__isnull=False)
    if ingredient_ids is not None:
        rows = rows.filter(ingredient_id__in=ingredient_ids)
    out = {}
    for ing, cost in rows.order_by("ingredient_id", "-received_at", "-id").values_list("ingredient_id", "unit_cost"):
        out.setdefault(ing, cost)
    return out


class LotView:
    """Lô kèm trạng thái, thứ tự lấy, dự kiến dùng hết và phần có nguy cơ quá hạn."""

    def __init__(self, lot, rank, state, days_left, used_up, waste, cost, start=None):
        self.lot, self.rank, self.state, self.days_left = lot, rank, state, days_left
        self.used_up, self.waste, self.cost, self.start = used_up, waste, cost, start

    def __getattr__(self, name):
        return getattr(self.lot, name)

    @property
    def state_label(self):
        if self.state == UNKNOWN and not self.lot.ingredient.shelf_life_days:
            return "Không có hạn"  # hàng không hỏng theo thời gian (ly, ống hút...), không phải thiếu thông tin
        return STATUS_LABELS[self.state]

    @property
    def value(self):
        return int(float(self.lot.remaining) * (self.cost or 0))

    @property
    def waste_value(self):
        return int(self.waste * (self.cost or 0))

    @property
    def overdue(self):
        return -self.days_left if self.days_left is not None and self.days_left < 0 else 0

    @property
    def age_days(self):
        return (timezone.localdate() - timezone.localdate(self.lot.received_at)).days


def overview(ingredients, today=None):
    """Mỗi nguyên liệu: danh sách LotView theo thứ tự lấy, lô nên lấy trước và các tổng.

    Trả về {ingredient.pk: {"lots", "pick", "expired", "near", "unknown", "at_risk", "at_risk_value", "value",
    "rate", "cover_days"}}."""
    today = today or timezone.localdate()
    ingredients = list(ingredients)
    ids = [i.pk for i in ingredients]
    by_ing = {}
    for lot in StockLot.objects.filter(ingredient_id__in=ids, remaining__gt=0).select_related("supplier"):
        by_ing.setdefault(lot.ingredient_id, []).append(lot)
    rates = daily_usage(ids, today)
    costs = latest_costs(ids)
    days_param, pct_param = params.get("lot_near_expiry_days"), params.get("lot_near_expiry_percent")
    out = {}
    for ing in ingredients:
        for lot in by_ing.get(ing.pk, []):
            lot.ingredient = ing  # dùng lại đối tượng đã có, khỏi truy vấn từng lô
        lots = issue_order(by_ing.get(ing.pk, []), ing.rule, today)
        rate = rates.get(ing.pk, 0.0)
        proj = project([l for l in lots if not is_expired(l, today)], rate, today)
        near = near_days(ing.shelf_life_days, days_param, pct_param)
        views = []
        for rank, lot in enumerate(lots, start=1):
            st = status(lot, today, near)
            p = proj.get(lot.pk, {"used_up": None, "waste": float(lot.remaining) if st == EXPIRED else 0.0,
                                  "start": None})
            views.append(LotView(lot, rank, st, (lot.expiry_date - today).days if lot.expiry_date else None,
                                 p["used_up"], p["waste"], lot.unit_cost or costs.get(ing.pk), p["start"]))
        usable = [v for v in views if v.state != EXPIRED]
        total = sum(float(v.lot.remaining) for v in views)
        out[ing.pk] = {
            "lots": views, "pick": usable[0] if usable else None,
            "expired": [v for v in views if v.state == EXPIRED],
            "near": [v for v in views if v.state == NEAR],
            "unknown": [v for v in views if v.state == UNKNOWN],
            "at_risk": sum(v.waste for v in usable), "at_risk_value": sum(v.waste_value for v in usable),
            "expired_qty": sum(float(v.lot.remaining) for v in views if v.state == EXPIRED),
            "expired_value": sum(v.value for v in views if v.state == EXPIRED),
            "value": sum(v.value for v in views), "rate": rate, "total": total,
            "cover_days": (total / rate) if rate > 0 else None, "near_days": near,
        }
    return out


def problems():
    """Kiểm tra toàn vẹn lô: còn lại = tổng LotDraw; tổng còn lại = max(tồn vật lý, 0)."""
    from .models import IngredientStock

    out = []
    draws = dict(LotDraw.objects.values("lot_id").annotate(s=Sum("quantity")).values_list("lot_id", "s"))
    sums = {}
    for lot in StockLot.objects.select_related("ingredient"):
        if Decimal(draws.get(lot.pk) or 0) != lot.remaining:
            out.append(f"Lô {lot.code} ({lot.ingredient.name}): còn {lot.remaining} khác tổng xuất nhập lô "
                       f"{draws.get(lot.pk) or 0}")
        sums[lot.ingredient_id] = sums.get(lot.ingredient_id, Decimal(0)) + lot.remaining
    for row in IngredientStock.objects.select_related("ingredient"):
        expected = max(row.physical, Decimal(0))
        if sums.get(row.ingredient_id, Decimal(0)) != expected:
            out.append(f"{row.ingredient.name}: tổng còn lại các lô {sums.get(row.ingredient_id, 0)} khác tồn vật lý "
                       f"{expected}")
    return out
