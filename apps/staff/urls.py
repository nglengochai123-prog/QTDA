from django.urls import path

from . import views

app_name = "staff"

urlpatterns = [
    path("cham-cong/", views.attendance, name="attendance"),
    path("tai/", views.workload, name="workload"),
]
