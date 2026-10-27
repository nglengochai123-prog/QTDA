from django.urls import path

from . import views

app_name = "shifts"

urlpatterns = [
    path("ca/", views.my_shift, name="my_shift"),
    path("ca/<int:shift_id>/", views.my_shift, name="my_shift_detail"),
    path("ca/<int:shift_id>/quy/", views.cash_entry, name="cash_entry"),
    path("ca/<int:shift_id>/tien-dau-ca/", views.correct_opening, name="correct_opening"),
    path("ca/<int:shift_id>/ket-ca/", views.close, name="close"),
    path("ca/<int:shift_id>/chuyen-don/", views.carry, name="carry"),
    path("ca/<int:shift_id>/bao-cao/", views.report, name="report"),
    path("ca/nhan-tien/<int:entry_id>/", views.confirm_handover, name="confirm_handover"),
    path("ca/nhan-tien/<int:entry_id>/bo/", views.cancel_handover, name="cancel_handover"),
    path("ca/chenh-lech/<int:discrepancy_id>/giai-trinh/", views.explain, name="explain"),
    path("ca/chenh-lech/<int:discrepancy_id>/quyet-dinh/", views.decide, name="decide"),
    path("ca/tinh-trang/", views.status, name="status"),
    path("ca/hoan-tien/<int:refund_id>/", views.refund_paid, name="refund_paid"),
    path("ca/<int:shift_id>/dinh-chinh/", views.correction, name="correction"),
    path("ca/dinh-chinh/<int:correction_id>/duyet/", views.decide_correction, name="decide_correction"),
]
