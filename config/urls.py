from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path


urlpatterns = [
    path("quan-tri/", admin.site.urls),
    path("tai-khoan/", include("apps.accounts.urls")),
    path("", include("apps.orders.urls")),
    path("", include("apps.shifts.urls")),
    path("", include("apps.control.urls")),
    path("", include("apps.staff.urls")),
    path("", include("apps.inventory.urls")),
    path("", include("apps.core.urls")),
]

# Ảnh chứng từ khi chạy thử; triển khai thật do Nginx phục vụ.
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
