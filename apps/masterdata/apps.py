from django.apps import AppConfig


class MasterdataConfig(AppConfig):
    name = "apps.masterdata"
    verbose_name = "Dữ liệu nền"

    def ready(self):
        from . import resources  # noqa: F401  (đăng ký các loại dữ liệu)
