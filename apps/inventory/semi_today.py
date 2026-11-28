"""Việc làm bán thành phẩm trong ngày (Hai, 28/11/2026).

Mỗi ngày pha chế tự làm mẻ mới cho từng bán thành phẩm (cà phê cốt, nước đường, foam...). Màn Làm mẻ và Quầy pha chế
cho pha chế đánh dấu đã làm xong từng mẻ; Chủ quán thấy ngay trên bảng điều khiển và được báo trên chuông khi mẻ
được ghi. "Đã làm" nghĩa là hôm nay có ít nhất một mẻ được ghi (ghi mẻ là trừ nguyên liệu gốc và cộng bán thành phẩm
vào kho, không có bước đánh dấu riêng để số kho luôn khớp với việc đã làm).
"""

from django.utils import timezone


def today_status(day=None):
    """Mỗi bán thành phẩm có định mức mẻ: hôm nay đã làm chưa, bao nhiêu mẻ, lần cuối ai làm lúc nào."""
    from .models import Ingredient, IngredientKind, SemiBatch

    day = day or timezone.localdate()
    products = (Ingredient.objects.filter(is_active=True, kind=IngredientKind.SEMI, semi_recipe__isnull=False)
                .select_related("semi_recipe").order_by("name"))
    batches = {}
    for b in (SemiBatch.objects.filter(created_at__date=day, product__in=products)
              .select_related("actor", "lot").order_by("created_at")):
        batches.setdefault(b.product_id, []).append(b)
    rows = []
    for p in products:
        made = batches.get(p.pk, [])
        rows.append({"ingredient": p, "recipe": p.semi_recipe, "done": bool(made), "count": len(made),
                     "batches": sum(b.batches for b in made), "output": sum(b.actual_output for b in made),
                     "last": made[-1] if made else None})
    return rows


def missing_today(day=None):
    """Tên các bán thành phẩm hôm nay chưa có mẻ nào."""
    return [r["ingredient"].name for r in today_status(day) if not r["done"]]

