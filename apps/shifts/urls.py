from django.urls import path

from . import views

app_name = "shifts"

urlpatterns = [
    path("ca/", views.my_shift, name="my_shift"),
    path("ca/<int:shift_id>/", views.my_shift, name="my_shift_detail"),
    path("ca/<int:shift_id>/quy/", views.cash_entry, name="cash_entry"),
    path("ca/<int:shift_id>/ket-ca/", views.close, name="close"),
    path("ca/<int:shift_id>/chuyen-don/", views.carry, name="carry"),
    path("ca/<int:shift_id>/bao-cao/", views.report, name="report"),
    path("ca/nhan-tien/<int:entry_id>/", views.confirm_handover, name="confirm_handover"),
    path("ca/chenh-lech/<int:discrepancy_id>/giai-trinh/", views.explain, name="explain"),
    path("ca/chenh-lech/<int:discrepancy_id>/quyet-dinh/", views.decide, name="decide"),
    path("ca/tinh-trang/", views.status, name="status"),
]
