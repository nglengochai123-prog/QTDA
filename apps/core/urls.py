from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("", views.home, name="home"),
    path("healthz/", views.healthz, name="healthz"),
    path("manifest.webmanifest", views.manifest, name="manifest"),
    path("sw.js", views.service_worker, name="service_worker"),
    path("offline/", views.offline, name="offline"),
    path("thong-bao/dang-ky/", views.push_subscribe, name="push_subscribe"),
    path("thong-bao/trang-thai/", views.push_status, name="push_status"),
    path("thong-bao/thu/", views.push_test, name="push_test"),
    path("thong-bao/nhat-ky/", views.push_log, name="push_log"),
    path("thong-bao/<uuid:message_id>/<str:stage>/", views.push_receipt, name="push_receipt"),
]
