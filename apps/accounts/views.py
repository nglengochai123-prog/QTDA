"""Người dùng tự đổi mật khẩu của mình (Chủ quán vẫn đặt lại được ở Quản trị › Nhân viên)."""

from django.contrib import messages
from django.contrib.auth import views as auth_views
from django.urls import reverse_lazy

from apps.audit.models import Action
from apps.audit.services import record


class PasswordChangeView(auth_views.PasswordChangeView):
    template_name = "registration/password_change.html"
    success_url = reverse_lazy("core:home")

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        form.fields["old_password"].label = "Mật khẩu đang dùng"
        form.fields["new_password1"].label = "Mật khẩu mới"
        form.fields["new_password1"].help_text = "Ít nhất 8 ký tự, không quá dễ đoán và không giống tên đăng nhập."
        form.fields["new_password2"].label = "Nhập lại mật khẩu mới"
        form.fields["new_password2"].help_text = ""
        for name, field in form.fields.items():
            field.widget.attrs.update({"class": "input",
                                       "autocomplete": "current-password" if name == "old_password" else "new-password"})
        return form

    def form_valid(self, form):
        response = super().form_valid(form)  # giữ phiên đăng nhập hiện tại
        record(Action.UPDATE, request=self.request, obj=self.request.user, after={"mat_khau": "tự đổi"})
        messages.success(self.request, "Đã đổi mật khẩu. Lần đăng nhập sau dùng mật khẩu mới.")
        return response
