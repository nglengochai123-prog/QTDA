"""Nghiệp vụ tồn kho: tồn đầu kỳ, giữ, tiêu hao và trả lại nguyên liệu (BRU-18, BRU-20).

Mọi hàm ở đây phải chạy bên trong transaction.atomic() của người gọi; chúng khóa các dòng
IngredientStock theo thứ tự mã để hai giao dịch không giữ cùng một phần tồn (NFR-04).
"""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction

from .models import Ingredient, IngredientStock, StockMovement


def fmt_qty(value):
    """Số lượng gọn, không dùng dạng mũ: Decimal("2000.00") -> "2000", Decimal("12.50") -> "12.5"."""
    return format(Decimal(value).normalize(), "f")


class InsufficientStock(Exception):
    def __init__(self, shortages):
        self.shortages = shortages  # [{"ingredient": tên, "unit": đơn vị, "needed": x, "available": y}]
        super().__init__("; ".join(f"{s['ingredient']}: cần {s['needed']}, còn {s['available']}" for s in shortages))


def _lock(ingredient_ids):
    ids = sorted(set(ingredient_ids))
    for ingredient_id in ids:
        IngredientStock.objects.get_or_create(ingredient_id=ingredient_id)
    rows = IngredientStock.objects.select_for_update().select_related("ingredient").filter(ingredient_id__in=ids)
    return {row.ingredient_id: row for row in rows.order_by("ingredient_id")}


def _as_decimal(totals):
    return {int(k): Decimal(str(v)) for k, v in totals.items() if Decimal(str(v)) != 0}


@transaction.atomic
def record_opening(ingredient, quantity, actor, note=""):
    """Tồn đầu kỳ: chỉ ghi một lần, trước mọi biến động khác của nguyên liệu."""
    quantity = Decimal(str(quantity))
    if quantity < 0:
        raise ValidationError("Tồn đầu kỳ không được âm.")
    stock = _lock([ingredient.pk])[ingredient.pk]
    if StockMovement.objects.filter(ingredient=ingredient).exists():
        raise ValidationError(f"{ingredient.name} đã có tồn đầu kỳ hoặc biến động; hãy dùng kiểm kê để điều chỉnh.")
    stock.physical += quantity
    stock.save(update_fields=["physical", "updated_at"])
    return StockMovement.objects.create(
        store=ingredient.store, ingredient=ingredient, kind=StockMovement.Kind.OPENING, quantity=quantity,
        balance_after=stock.physical, source_type="ton_dau_ky", actor=actor, note=note)


def reserve(totals):
    """Giữ nguyên liệu cho cả đơn. Thiếu bất kỳ nguyên liệu nào thì không giữ gì và báo thiếu."""
    totals = _as_decimal(totals)
    if not totals:
        return
    stocks = _lock(totals)
    shortages = []
    for ingredient_id, needed in totals.items():
        stock = stocks[ingredient_id]
        if stock.available < needed:
            shortages.append({"ingredient_id": ingredient_id, "ingredient": stock.ingredient.name,
                              "unit": stock.ingredient.get_unit_display(),
                              "needed": fmt_qty(needed), "available": fmt_qty(max(stock.available, 0))})
    if shortages:
        raise InsufficientStock(shortages)
    for ingredient_id, needed in totals.items():
        stock = stocks[ingredient_id]
        stock.reserved += needed
        stock.save(update_fields=["reserved", "updated_at"])


def consume(totals, *, actor, store, source_type, source_id, note=""):
    """Món đã pha chế: trừ tồn vật lý và bỏ phần đang giữ tương ứng, ghi biến động."""
    totals = _as_decimal(totals)
    stocks = _lock(totals)
    movements = []
    for ingredient_id, used in totals.items():
        stock = stocks[ingredient_id]
        stock.physical -= used
        stock.reserved -= used
        stock.save(update_fields=["physical", "reserved", "updated_at"])
        movements.append(StockMovement.objects.create(
            store=store, ingredient_id=ingredient_id, kind=StockMovement.Kind.CONSUME, quantity=-used,
            balance_after=stock.physical, source_type=source_type, source_id=str(source_id), actor=actor, note=note))
    return movements


def release(totals):
    """Món chờ pha bị hủy: trả lại tồn có thể dùng (BRU-18)."""
    totals = _as_decimal(totals)
    stocks = _lock(totals)
    for ingredient_id, amount in totals.items():
        stock = stocks[ingredient_id]
        stock.reserved -= amount
        stock.save(update_fields=["reserved", "updated_at"])


def snapshot_for(ingredient_ids=None):
    """Tồn hiện tại theo nguyên liệu: {id: (vật lý, đang giữ, có thể dùng)}."""
    rows = IngredientStock.objects.all()
    if ingredient_ids is not None:
        rows = rows.filter(ingredient_id__in=ingredient_ids)
    return {r.ingredient_id: (r.physical, r.reserved, r.physical - r.reserved) for r in rows}


def ensure_stock_rows():
    existing = set(IngredientStock.objects.values_list("ingredient_id", flat=True))
    IngredientStock.objects.bulk_create(
        [IngredientStock(ingredient_id=i) for i in Ingredient.objects.values_list("pk", flat=True) if i not in existing])
