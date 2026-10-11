from django.urls import path

from . import views

app_name = "control"

urlpatterns = [
    path("kiem-soat/ngoai-le/", views.exception_list, name="exceptions"),
    path("kiem-soat/ngoai-le/<int:pk>/", views.exception_detail, name="exception_detail"),
    path("kiem-soat/vu-viec/", views.case_list, name="cases"),
    path("kiem-soat/vu-viec/<int:pk>/", views.case_detail, name="case_detail"),
    path("kiem-soat/dieu-chinh/<int:shift_id>/", views.adjustment_report, name="adjustment_report"),
    path("tham-so/", views.parameters, name="parameters"),
    path("canh-bao/", views.alert_center, name="alerts"),
]
