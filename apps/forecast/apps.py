from django.apps import AppConfig


class ForecastConfig(AppConfig):
    name = "apps.forecast"
    verbose_name = "Dự báo nhu cầu"

    def ready(self):
        from django.db.models.signals import post_save

        from apps.inventory.models import StockMovement

        from .planning import on_movement

        # Giám sát sau biến động (mục 8.4): tính lại kế hoạch mua của nguyên liệu khi giao dịch ghi tồn đã hoàn tất.
        post_save.connect(on_movement, sender=StockMovement, dispatch_uid="ke_hoach_mua_sau_bien_dong")
