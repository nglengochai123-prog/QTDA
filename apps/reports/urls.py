from django.urls import path

from . import views

app_name = "reports"

urlpatterns = [
    path("bang-dieu-khien/", views.dashboard, name="dashboard"),
    path("bao-cao/doanh-thu/", views.revenue, name="revenue"),
    path("bao-cao/kiem-soat/", views.revenue_control, name="revenue_control"),
    path("bao-cao/nguyen-lieu/", views.materials, name="materials"),
]
