"""Quay lại trang người dùng đang xem sau khi gửi biểu mẫu."""

from django.shortcuts import redirect
from django.utils.http import url_has_allowed_host_and_scheme


def back(request, default, *args):
    """Về ô `next` nếu đó là một đường dẫn của chính trang web này, không thì về `default`.

    Không nhận địa chỉ trang ngoài (tránh bị dẫn sang trang lừa đảo) và không nhận chữ lạ như "-5".
    """
    target = (request.POST.get("next") or "").strip()
    if target.startswith("/") and url_has_allowed_host_and_scheme(
            target, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return redirect(target)
    return redirect(default, *args)
