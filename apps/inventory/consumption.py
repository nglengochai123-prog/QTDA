"""Đối chiếu tiêu hao nguyên liệu trọng yếu giữa hai lần kiểm kê (FR-16, BRU-17, AC-32 đến AC-34).

Tiêu hao thực tế = tồn kiểm kê kỳ trước + nhập trong kỳ − tồn kiểm kê kỳ này − hao hụt xuất kho.
Tiêu hao theo đơn = tổng tiêu hao ghi khi pha chế trong kỳ (theo định mức đã chụp ở từng dòng món),
gồm cả ly sau đó bị hủy sau pha chế: hủy sau pha chế không sinh biến động kho nên không bị tính lần hai.
"""

from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone

from apps.audit.models import Action
from apps.audit.services import record
from apps.core import params

from .models import ConsumptionCheck, StockCount, StockMovement
from .stock import fmt_vn


def _sum(ingredient, kind, start, end):
    total = (StockMovement.objects.filter(ingredient=ingredient, kind=kind, created_at__gte=start, created_at__lt=end)
             .aggregate(s=Sum("quantity"))["s"])
    return Decimal(total or 0)


def check_after_count(count, actor=None):
    """Gọi khi một lần kiểm kê được áp dụng. Chỉ nguyên liệu trọng yếu, cần có lần kiểm kê áp dụng trước đó."""
    ingredient = count.ingredient
    if not ingredient.is_critical or count.status != StockCount.Status.APPLIED:
        return None
    if ConsumptionCheck.objects.filter(to_count=count).exists():
        return ConsumptionCheck.objects.get(to_count=count)
    previous = (StockCount.objects.filter(ingredient=ingredient, status=StockCount.Status.APPLIED,
                                          created_at__lt=count.created_at).exclude(pk=count.pk)
                .order_by("-created_at", "-id").first())
    if previous is None:
        return None  # lần kiểm kê đầu tiên chỉ làm mốc
    start, end = previous.created_at, count.created_at
    receipts = _sum(ingredient, StockMovement.Kind.RECEIPT, start, end)
    waste = -_sum(ingredient, StockMovement.Kind.WASTE, start, end)
    by_orders = -_sum(ingredient, StockMovement.Kind.CONSUME, start, end)
    actual = previous.counted + receipts - count.counted - waste
    excess = actual - by_orders
    percent = (excess / by_orders * 100) if by_orders else (Decimal(100) if excess > 0 else Decimal(0))
    tolerance = params.get("consumption_tolerance_percent")
    check = ConsumptionCheck.objects.create(
        store=count.store, ingredient=ingredient, from_count=previous, to_count=count, opening=previous.counted,
        receipts=receipts, closing=count.counted, waste=waste, actual=actual, by_orders=by_orders, excess=excess,
        percent=percent.quantize(Decimal("0.01")), tolerance_percent=tolerance, over=percent > tolerance)
    record(Action.CREATE, actor=actor, obj=check, object_type="inventory.ConsumptionCheck",
           actor_label=None if actor else "hệ thống",
           after={"nguyen_lieu": ingredient.name, "thuc_te": str(actual), "theo_don": str(by_orders),
                  "vuot": str(excess), "ty_le": f"{percent:.2f}%", "muc_cho_phep": f"{tolerance}%"})
    if check.over:
        from apps.control.models import ExceptionCase
        from apps.control.services import open_exception

        unit = ingredient.get_unit_display()
        open_exception(ExceptionCase.Kind.CONSUMPTION_OVER, ingredient=ingredient, store=count.store,
                       one_per_scope=False,
                       rule=f"Tiêu hao thực tế {ingredient.name} vượt tiêu hao theo đơn quá {fmt_vn(tolerance)}%",
                       detail=(f"Từ {timezone.localtime(start):%H:%M %d/%m} đến {timezone.localtime(end):%H:%M %d/%m}: "
                               f"thực tế dùng {fmt_vn(actual)} {unit}, theo đơn {fmt_vn(by_orders)} {unit}, "
                               f"vượt {fmt_vn(excess)} {unit} ({fmt_vn(percent, 1)}%). "
                               "Kiểm tra món pha không qua đơn hoặc định mức chưa đúng."))
    return check
