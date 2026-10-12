from django.contrib.auth.decorators import login_required
from django.urls import path

from . import framework, views

app_name = "masterdata"

urlpatterns = [
    path("du-lieu/nhat-ky/", views.audit_log, name="audit_log"),
    path("du-lieu/<slug:key>/", login_required(framework.list_view), name="list"),
    path("du-lieu/<slug:key>/moi/", login_required(framework.edit_view), name="create"),
    path("du-lieu/<slug:key>/<int:pk>/", login_required(framework.edit_view), name="edit"),
    path("du-lieu/<slug:key>/<int:pk>/<slug:action>/", login_required(framework.action_view), name="action"),
]
