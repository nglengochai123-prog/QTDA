from django import forms
from django.contrib.auth.forms import AuthenticationForm


class LoginForm(AuthenticationForm):
    error_messages = {
        "invalid_login": "Sai tên đăng nhập hoặc mật khẩu, hoặc tài khoản đang bị khóa. "
                         "Sai nhiều lần liên tiếp sẽ bị tạm khóa; cần mở khóa thì báo Chủ quán.",
        "inactive": "Tài khoản này đã bị khóa. Hãy báo Chủ quán.",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].widget.attrs.update(
            {"autocomplete": "username", "autocapitalize": "none", "autocorrect": "off", "spellcheck": "false"})
        self.fields["password"].widget.attrs.update({"autocomplete": "current-password"})
