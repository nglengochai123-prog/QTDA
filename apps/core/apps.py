from django.apps import AppConfig
from django.contrib.admin import apps as admin_apps


class CoreConfig(AppConfig):
    default = True
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.core"
    label = "core"
    verbose_name = "Nền tảng chung"


class OwnerAdminConfig(admin_apps.AdminConfig):
    default = False
    default_site = "apps.core.admin_site.OwnerAdminSite"
