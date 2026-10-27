"""Câu báo lỗi hiện cho người dùng."""

from django.core.exceptions import ValidationError


def messages_of(error):
    """Lỗi nghiệp vụ giữ nguyên câu chữ; lỗi đọc dữ liệu của Python (tiếng Anh, ví dụ "invalid literal for int()")
    đổi thành một câu chung thay vì hiện nguyên văn."""
    if isinstance(error, ValidationError):
        return error.messages
    text = str(error)
    if isinstance(error, ValueError) and text.isascii():
        return ["Dữ liệu nhập không hợp lệ; kiểm tra lại các ô số và ngày giờ."]
    return [text]
