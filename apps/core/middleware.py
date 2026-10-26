"""Lưới an toàn cho thao tác gửi biểu mẫu (POST).

Dữ liệu gửi lên sai dạng, thiếu ô chọn, hoặc trỏ tới bản ghi không còn (trang mở đã lâu, bấm lại nút cũ)
không được biến thành trang lỗi máy chủ. Giao dịch của yêu cầu đã được hủy trước khi tới đây
(ATOMIC_REQUESTS), nên không có dữ liệu nào được ghi dở. Người dùng quay lại trang trước kèm thông báo;
lỗi vẫn được ghi vào nhật ký máy chủ để lập trình viên xem.
"""

import logging
from decimal import InvalidOperation

from django.contrib import messages
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.http import JsonResponse
from django.shortcuts import redirect
from django.utils.http import url_has_allowed_host_and_scheme

from .idempotency import OperationKeyError

logger = logging.getLogger("lam.form_errors")

BAD_INPUT = (ValueError, TypeError, InvalidOperation, KeyError, OperationKeyError, ValidationError)


def _message(exception):
    if isinstance(exception, ObjectDoesNotExist):
        return "Không tìm thấy dữ liệu cần xử lý; có thể trang đã cũ. Tải lại trang rồi thử lại."
    if isinstance(exception, OperationKeyError):
        return str(exception) + " Tải lại trang rồi thử lại."
    if isinstance(exception, ValidationError):
        return " ".join(exception.messages)
    return "Dữ liệu gửi lên chưa hợp lệ (thiếu ô chọn hoặc sai định dạng). Kiểm tra lại rồi gửi lại."


class FormErrorMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        if request.method != "POST" or not isinstance(exception, (ObjectDoesNotExist,) + BAD_INPUT):
            return None
        if getattr(exception, "lam_denied", None) is not None:
            return None
        logger.warning("Dữ liệu gửi lên không xử lý được tại %s", request.path, exc_info=exception)
        text = _message(exception)
        wants_json = (request.content_type == "application/json"
                      or "application/json" in request.headers.get("Accept", "")
                      or request.headers.get("HX-Request") or request.headers.get("X-Requested-With"))
        if wants_json:
            return JsonResponse({"ok": False, "error": text, "errors": [text]}, status=400)
        messages.error(request, text)
        back = request.headers.get("Referer", "")
        if back and url_has_allowed_host_and_scheme(back, allowed_hosts={request.get_host()},
                                                    require_https=request.is_secure()):
            return redirect(back)
        return redirect("core:home")  # đường dẫn hiện tại thường chỉ nhận POST
