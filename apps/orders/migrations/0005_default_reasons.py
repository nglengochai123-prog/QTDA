"""Danh mục lý do điều chỉnh mặc định (Chủ quán sửa được ở Dữ liệu nền)."""

from django.conf import settings
from django.db import migrations

REASONS = ["Khách đổi ý", "Nhập sai món", "Nhập sai bàn", "Pha hỏng", "Hết nguyên liệu", "Khách gộp bàn", "Khác"]


def seed(apps, schema_editor):
    Store = apps.get_model("core", "Store")
    Reason = apps.get_model("orders", "AdjustmentReason")
    store, _ = Store.objects.get_or_create(code=settings.LAM_STORE_CODE, defaults={"name": settings.LAM_STORE_NAME})
    for order, name in enumerate(REASONS):
        Reason.objects.get_or_create(store=store, name=name, defaults={"sort_order": order})


class Migration(migrations.Migration):
    dependencies = [("orders", "0004_order_shift_orderline_voided_done_quantity_and_more"), ("core", "0001_initial")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
