"""Việc làm bán thành phẩm trong ngày (Hai, 28/11/2026).

Chủ quán đặt kế hoạch mẻ cho từng ngày (SemiTask): bán thành phẩm nào, bao nhiêu mẻ. Pha chế bấm Đã làm xong ở màn
Mẻ hôm nay; Chủ quán thấy trên bảng điều khiển và được báo trên chuông khi mẻ được ghi. Ngày chưa có kế hoạch thì mọi
bán thành phẩm đang dùng đều coi là cần làm một mẻ (như trước khi có kế hoạch).

"Đã làm" suy ra từ các mẻ đã ghi trong ngày (ghi mẻ là trừ nguyên liệu gốc và cộng bán thành phẩm vào kho), không có
bước đánh dấu riêng, để số kho luôn khớp với việc đã làm.
"""

from decimal import Decimal

from django.utils import timezone


def today_status(day=None):
    """Mỗi việc làm mẻ trong ngày: cần bao nhiêu mẻ, đã làm bao nhiêu, xong chưa, lần cuối ai làm lúc nào.
    Mẻ làm thêm ngoài kế hoạch cũng hiện (planned = 0)."""
    from .models import Ingredient, IngredientKind, SemiBatch, SemiTask

    day = day or timezone.localdate()
    tasks = list(SemiTask.objects.filter(day=day, product__is_active=True).select_related("product__semi_recipe"))
    planned = bool(tasks)
    if planned:
        wanted = {t.product_id: (t.product, t.batches, t.note) for t in tasks}
    else:
        products = (Ingredient.objects.filter(is_active=True, kind=IngredientKind.SEMI, semi_recipe__isnull=False)
                    .select_related("semi_recipe"))
        wanted = {p.pk: (p, Decimal(1), "") for p in products}
    made = {}
    for b in (SemiBatch.objects.filter(created_at__date=day).select_related("actor", "lot", "product__semi_recipe")
              .order_by("created_at")):
        made.setdefault(b.product_id, []).append(b)
        if b.product_id not in wanted:
            wanted[b.product_id] = (b.product, Decimal(0), "")
    rows = []
    for pk, (product, need, note) in sorted(wanted.items(), key=lambda kv: kv[1][0].name):
        batches = made.get(pk, [])
        done_batches = sum((b.batches for b in batches), Decimal(0))
        left = max(need - done_batches, Decimal(0))
        rows.append({"ingredient": product, "recipe": getattr(product, "semi_recipe", None), "planned": need,
                     "note": note, "done": bool(batches) and left == 0, "count": len(batches),
                     "batches": done_batches, "left": left, "output": sum(b.actual_output for b in batches),
                     "last": batches[-1] if batches else None, "has_plan": planned})
    return rows


def missing_today(day=None):
    """Tên các bán thành phẩm hôm nay còn thiếu mẻ so với kế hoạch."""
    return [r["ingredient"].name for r in today_status(day) if r["planned"] and not r["done"]]
