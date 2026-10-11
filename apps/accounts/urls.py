from django.contrib.auth import views as auth_views
from django.urls import path

from .forms import LoginForm

app_name = "accounts"

urlpatterns = [
    path("dang-nhap/", auth_views.LoginView.as_view(redirect_authenticated_user=True, authentication_form=LoginForm),
         name="login"),
    path("dang-xuat/", auth_views.LogoutView.as_view(), name="logout"),
]
