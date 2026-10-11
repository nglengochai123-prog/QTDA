from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def copy_overrides(apps, schema_editor):
    Parameter = apps.get_model("core", "Parameter")
    ParameterValue = apps.get_model("core", "ParameterValue")
    for row in Parameter.objects.all():
        ParameterValue.objects.create(key=row.key, value=int(row.value), effective_from=row.updated_at,
                                      reason="Chuyển từ bảng tham số cũ")


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0003_parameter"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ParameterValue",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("key", models.CharField(max_length=60, verbose_name="Tham số")),
                ("value", models.BigIntegerField(verbose_name="Giá trị")),
                ("effective_from", models.DateTimeField(verbose_name="Hiệu lực từ")),
                ("reason", models.CharField(blank=True, max_length=255, verbose_name="Lý do")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Ghi lúc")),
                ("set_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                                             related_name="+", to=settings.AUTH_USER_MODEL, verbose_name="Người đặt")),
            ],
            options={"verbose_name": "Giá trị tham số", "verbose_name_plural": "Lịch sử tham số",
                     "ordering": ["key", "-effective_from", "-id"],
                     "indexes": [models.Index(fields=["key", "effective_from"], name="core_parame_key_19e1d6_idx")]},
        ),
        migrations.RunPython(copy_overrides, migrations.RunPython.noop),
        migrations.DeleteModel(name="Parameter"),
    ]
