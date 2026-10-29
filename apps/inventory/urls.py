from django.urls import path

from . import views, views_ledger, views_lots

app_name = "inventory"

urlpatterns = [
    path("kho/", views.stock_list, name="stock"),
    path("kho/bao-nhanh/", views.quick_report, name="quick_report"),
    path("kho/bao-nhanh/so-luong/", views.quick_report_count, name="quick_report_count"),
    path("kho/bao-nhanh/<int:report_id>/xu-ly/", views.acknowledge, name="acknowledge"),
    path("kho/kiem-ke/", views.count, name="count"),
    path("kho/hao-hut/", views.waste, name="waste"),
    path("kho/ban-thanh-pham/", views.semi, name="semi"),
    path("kho/phieu-nhap/", views.receipt, name="receipt"),
    path("kho/dat-hang/", views.purchase_orders, name="purchase_orders"),
    path("kho/phai-tra/", views.payables, name="payables"),
    path("kho/so-kho/", views_ledger.ledger, name="ledger"),
    path("kho/bao-cao/", views.report, name="report"),
    path("kho/lo/", views_lots.lot_list, name="lots"),
    path("kho/lo/nguyen-lieu/<int:ingredient_id>/", views_lots.lot_detail, name="lot_detail"),
    path("kho/lo/<int:lot_id>/huy/", views_lots.dispose, name="lot_dispose"),
    path("kho/lo/<int:lot_id>/sua/", views_lots.update, name="lot_update"),
    path("kho/lay-hang/", views_lots.pick_list, name="pick_list"),
]
