from django.urls import path

from . import views

app_name = "forecast"

urlpatterns = [
    path("du-bao/", views.overview, name="overview"),
    path("du-bao/mon/<int:pk>/", views.series_detail, name="series"),
    path("du-bao/dat-hang/", views.ordering, name="ordering"),
    path("du-bao/danh-gia/", views.evaluation, name="evaluation"),
    path("du-bao/cach-tinh/<int:size_id>/", views.choose_method, name="choose_method"),
]
