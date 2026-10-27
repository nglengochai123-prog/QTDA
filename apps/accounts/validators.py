"""Kiểm tra mật khẩu: bản dịch tiếng Việt của Django thiếu câu báo mật khẩu quá ngắn."""

from django.contrib.auth import password_validation
from django.core.exceptions import ValidationError


class MinimumLengthValidator(password_validation.MinimumLengthValidator):
    def validate(self, password, user=None):
        if len(password) < self.min_length:
            raise ValidationError(f"Mật khẩu quá ngắn, cần ít nhất {self.min_length} ký tự.",
                                  code="password_too_short", params={"min_length": self.min_length})

    def get_help_text(self):
        return f"Mật khẩu cần ít nhất {self.min_length} ký tự."
