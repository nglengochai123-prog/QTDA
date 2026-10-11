from django.urls import path

from . import views

app_name = "inventory"

urlpatterns = [
    path("kho/", views.stock_list, name="stock"),
    path("kho/bao-nhanh/", views.quick_report, name="quick_report"),
    path("kho/bao-nhanh/so-luong/", views.quick_report_count, name="quick_report_count"),
    path("kho/bao-nhanh/<int:report_id>/xu-ly/", views.acknowledge, name="acknowledge"),
    path("kho/kiem-ke/", views.count, name="count"),
    path("kho/hao-hut/", views.waste, name="waste"),
    path("kho/phieu-nhap/", views.receipt, name="receipt"),
    path("kho/dat-hang/", views.purchase_orders, name="purchase_orders"),
    path("kho/phai-tra/", views.payables, name="payables"),
    path("kho/bao-cao/", views.report, name="report"),
]
