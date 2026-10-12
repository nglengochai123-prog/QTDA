from django.urls import path

from . import views, views_backup, views_control

app_name = "orders"

urlpatterns = [
    path("don/moi/", views.create, name="create"),
    path("don/con-dap-ung/", views.availability, name="availability"),
    path("don/gui/", views.submit, name="submit"),
    path("don/khach-doi-mon/", views.customer_switched, name="customer_switched"),
    path("don/de-nghi-kiem-ke/", views.recount, name="recount"),
    path("quay/", views.bar, name="bar"),
    path("quay/danh-sach/", views.bar_queue, name="bar_queue"),
    path("quay/xong/", views.bar_complete, name="bar_complete"),
    path("quay/phieu/<int:order_id>/", views.print_ticket, name="print_ticket"),
    path("don/san-sang/", views.ready, name="ready"),
    path("don/san-sang/danh-sach/", views.ready_queue, name="ready_queue"),
    path("don/san-sang/so-luong/", views.ready_count, name="ready_count"),
    path("don/mang-ra/", views.serve, name="serve"),
    path("don/dang-mo/", views_control.open_orders, name="open_orders"),
    path("don/<int:order_id>/dieu-chinh/", views_control.request_adjustment, name="request_adjustment"),
    path("duyet/", views_control.approvals, name="approvals"),
    path("duyet/so-luong/", views_control.approvals_count, name="approvals_count"),
    path("duyet/<int:request_id>/", views_control.decide, name="decide"),
    path("thu-ngan/", views_control.cashier, name="cashier"),
    path("thu-ngan/ban/<int:table_id>/", views_control.pay, name="pay"),
    path("du-phong/", views_backup.backup_slips, name="backup_slips"),
]
