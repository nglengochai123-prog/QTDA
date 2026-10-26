"""Chuyển tồn hiện có sang lô.

Mỗi dòng phiếu nhập cũ thành một lô (mã: mã phiếu/số thứ tự dòng). Tồn vật lý hiện tại được chia cho các lô theo nhập
trước xuất trước, tức là đi ngược từ phiếu mới nhất; phần đã dùng của lô ghi một dòng trừ "Đã dùng trước khi theo dõi
lô". Phần tồn không khớp phiếu nhập nào (tồn đầu kỳ, dư kiểm kê) thành lô "Tồn trước khi theo dõi lô", chưa rõ hạn.
"""

from datetime import timedelta
from decimal import Decimal

from django.db import migrations
from django.utils import timezone


def backfill(apps, schema_editor):
    Ingredient = apps.get_model("inventory", "Ingredient")
    IngredientStock = apps.get_model("inventory", "IngredientStock")
    Receipt = apps.get_model("inventory", "Receipt")
    ReceiptLine = apps.get_model("inventory", "ReceiptLine")
    StockMovement = apps.get_model("inventory", "StockMovement")
    StockLot = apps.get_model("inventory", "StockLot")
    LotDraw = apps.get_model("inventory", "LotDraw")
    now = timezone.now()
    position = {}
    for receipt in Receipt.objects.all():
        for n, pk in enumerate(ReceiptLine.objects.filter(receipt=receipt).order_by("pk").values_list("pk", flat=True), 1):
            position[pk] = n
    for ing in Ingredient.objects.all():
        physical = IngredientStock.objects.filter(ingredient=ing).values_list("physical", flat=True).first()
        left = max(physical or Decimal(0), Decimal(0))
        lines = list(ReceiptLine.objects.filter(ingredient=ing, quantity__gt=0).select_related("receipt")
                     .order_by("receipt__created_at", "pk"))
        remaining = {}
        for line in reversed(lines):
            remaining[line.pk] = min(line.quantity, left)
            left -= remaining[line.pk]
        moves = {}
        for m in StockMovement.objects.filter(ingredient=ing, kind="nhap_hang").order_by("created_at", "pk"):
            moves.setdefault(m.source_id, []).append(m)
        for line in lines:
            received = line.receipt.created_at
            expiry, estimated = line.expiry_date, False
            if expiry is None and ing.shelf_life_days:
                expiry, estimated = timezone.localdate(received) + timedelta(days=ing.shelf_life_days - 1), True
            lot = StockLot.objects.create(
                store_id=ing.store_id, ingredient=ing, code=f"{line.receipt.code}/{position[line.pk]}",
                source="phieu_nhap", receipt_line=line, supplier_id=line.receipt.supplier_id, received_at=received,
                expiry_date=expiry, expiry_estimated=estimated, quantity=line.quantity, remaining=remaining[line.pk],
                unit_cost=line.unit_price)
            queue = moves.get(line.receipt.code) or []
            LotDraw.objects.create(lot=lot, movement=queue.pop(0) if queue else None, quantity=line.quantity,
                                   created_at=received)
            used = line.quantity - remaining[line.pk]
            if used > 0:
                LotDraw.objects.create(lot=lot, quantity=-used, created_at=now, note="Đã dùng trước khi theo dõi lô")
        if left > 0:
            first = StockMovement.objects.filter(ingredient=ing).order_by("created_at", "pk").first()
            lot = StockLot.objects.create(
                store_id=ing.store_id, ingredient=ing, code=f"TON-{ing.pk}", source="truoc_lo",
                received_at=first.created_at if first else now, quantity=left, remaining=left)
            LotDraw.objects.create(lot=lot, quantity=left, created_at=now,
                                   note="Tồn chưa khớp phiếu nhập nào khi bắt đầu theo dõi lô")


def undo(apps, schema_editor):
    apps.get_model("inventory", "LotDraw").objects.all().delete()
    apps.get_model("inventory", "StockLot").objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0010_stock_lots"),
    ]

    operations = [migrations.RunPython(backfill, undo)]
