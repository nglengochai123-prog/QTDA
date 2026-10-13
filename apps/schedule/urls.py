from django.urls import path

from . import views

app_name = "schedule"

urlpatterns = [
    path("lich/", views.board, name="board"),
    path("lich/dang-ky/", views.register, name="register"),
    path("lich/cua-toi/", views.mine, name="mine"),
]
