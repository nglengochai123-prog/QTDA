"""Lưới an toàn cho thao tác gửi biểu mẫu (POST).

Dữ liệu gửi lên sai dạng, thiếu ô chọn, hoặc trỏ tới bản ghi không còn (trang mở đã lâu, bấm lại nút cũ)
không được biến thành trang lỗi máy chủ. Giao dịch của yêu cầu đã được hủy trước khi tới đây
(ATOMIC_REQUESTS), nên không có dữ liệu nào được ghi dở. Người dùng quay lại trang trước kèm thông báo;
lỗi vẫn được ghi vào nhật ký máy chủ để lập trình viên xem.
"""

import logging
from decimal import InvalidOperation
from pathlib import Path

from django.contrib import messages
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db import DataError, OperationalError, ProgrammingError
from django.http import JsonResponse
from django.shortcuts import redirect
from django.template.loader import render_to_string
from django.utils.http import url_has_allowed_host_and_scheme

from .idempotency import OperationKeyError

logger = logging.getLogger("lam.form_errors")

# DataError, OverflowError: số quá lớn so với cột trong CSDL (PostgreSQL báo DataError, SQLite báo OverflowError).
BAD_INPUT = (ValueError, TypeError, InvalidOperation, KeyError, OperationKeyError, ValidationError, DataError, OverflowError)


def _message(exception):
    if isinstance(exception, ObjectDoesNotExist):
        return "Không tìm thấy dữ liệu cần xử lý; có thể trang đã cũ. Tải lại trang rồi thử lại."
    if isinstance(exception, OperationKeyError):
        return str(exception)
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


SESSION_EXPIRED = "Phiên đăng nhập đã hết hạn nên thao tác chưa được lưu. Đăng nhập lại rồi làm lại; nội dung đang soạn vẫn còn."
NOT_SAVED = "Thao tác trước chưa được lưu (thường do phiên đăng nhập hết hạn lúc bấm gửi). Kiểm tra rồi làm lại."
# Đường dẫn chỉ nhận POST → màn hình chứa nút gửi tương ứng, để quay về đúng chỗ thay vì trang trắng.
POST_ONLY_BACK = {
    "orders:submit": "orders:create", "orders:customer_switched": "orders:create", "orders:recount": "orders:create",
    "orders:bar_complete": "orders:bar", "orders:serve": "orders:ready", "orders:decide": "orders:approvals",
    "orders:pay": "orders:cashier", "inventory:lot_dispose": "inventory:lots", "inventory:lot_update": "inventory:lots",
    "inventory:acknowledge": "inventory:quick_report",
}


def is_fetch(request):
    """Yêu cầu do mã JavaScript của trang gửi (fetch), không phải người dùng mở trang."""
    if request.headers.get("Sec-Fetch-Mode") == "navigate":
        # Mở trang hay gửi biểu mẫu. Qua service worker (ứng dụng đã cài) trình duyệt ghi Sec-Fetch-Dest là "empty"
        # dù vẫn là mở trang, nên phải xét chế độ trước: không thì đăng xuất hiện ra một đoạn JSON.
        return False
    return (request.headers.get("Sec-Fetch-Dest") == "empty" or request.content_type == "application/json"
            or "application/json" in request.headers.get("Accept", "") or bool(request.headers.get("X-Requested-With")))


class SessionExpiryMiddleware:
    """Hết phiên đăng nhập giữa chừng: yêu cầu fetch nhận câu báo JSON thay vì trang đăng nhập (mã trang tưởng mất
    mạng và bảo gửi lại mãi); mở một đường dẫn chỉ nhận POST (thường là sau khi đăng nhập lại với next=đường dẫn đó)
    thì quay về màn hình tương ứng kèm lời nhắc, không để trang trắng."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from django.conf import settings
        from django.shortcuts import resolve_url
        from django.urls import Resolver404, resolve

        response = self.get_response(request)
        login = resolve_url(settings.LOGIN_URL)
        if response.status_code == 302 and response.get("Location", "").startswith(login) and is_fetch(request):
            back = request.headers.get("Referer", "")
            page = back if back and url_has_allowed_host_and_scheme(back, allowed_hosts={request.get_host()}) else "/"
            from urllib.parse import quote, urlsplit

            path = urlsplit(page).path or "/"
            return JsonResponse({"ok": False, "error": SESSION_EXPIRED, "errors": [SESSION_EXPIRED],
                                 "login": f"{login}?next={quote(path)}"}, status=401)
        if response.status_code == 405 and request.method == "GET" and not is_fetch(request):
            try:
                match = resolve(request.path_info)
            except Resolver404:
                return response
            if match.namespace == "accounts":
                return response  # đăng xuất chỉ nhận POST là chủ ý (chống đăng xuất ngoài ý muốn)
            messages.warning(request, NOT_SAVED)
            return redirect(POST_ONLY_BACK.get(match.view_name, "core:home"))
        return response


def csrf_failure(request, reason=""):
    """Mã bảo mật của biểu mẫu không còn hợp lệ (thường do đăng nhập lại ở thẻ khác): báo tiếng Việt, không lưu gì."""
    from django.shortcuts import render

    text = "Trang đã cũ nên thao tác chưa được lưu. Tải lại trang rồi làm lại."
    if is_fetch(request):
        return JsonResponse({"ok": False, "error": text, "errors": [text]}, status=403)
    return render(request, "403_csrf.html", {"text": text}, status=403)


# Lỗi CSDL thường gặp khi mã nguồn mới hơn CSDL (chưa chạy migrate): SQLite "no such column/table", PostgreSQL
# "column ... does not exist".
SCHEMA_WORDS = ("no such column", "no such table", "has no column named", "does not exist")


def pending_migrations():
    """Các bước cập nhật CSDL chưa chạy, dạng "ung_dung.ten_buoc"; rỗng khi CSDL khớp mã nguồn."""
    from django.db import connection
    from django.db.migrations.executor import MigrationExecutor

    executor = MigrationExecutor(connection)
    plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
    return [f"{m.app_label}.{m.name}" for m, _ in plan]


class SchemaOutdatedMiddleware:
    """Mã nguồn đã cập nhật mà CSDL chưa chạy migrate: thay trang lỗi bằng trang chỉ đúng hai lệnh cần chạy (sao lưu
    rồi cập nhật), thay vì hiện dấu vết lỗi khó hiểu. Chỉ xét khi đã có lỗi CSDL dạng thiếu cột, thiếu bảng."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        if not isinstance(exception, (OperationalError, ProgrammingError)):
            return None
        if not any(w in str(exception).lower() for w in SCHEMA_WORDS):
            return None
        try:
            pending = pending_migrations()
        except Exception:  # noqa: BLE001 - không đọc được trạng thái cập nhật: để trang lỗi thường xử lý
            return None
        if not pending:
            return None
        logging.getLogger("lam.schema").error("CSDL chưa cập nhật (%s) tại %s", ", ".join(pending), request.path,
                                              exc_info=exception)
        from django.conf import settings
        from django.http import HttpResponse

        db = settings.DATABASES["default"]
        sqlite = "sqlite" in db["ENGINE"]
        name = Path(str(db["NAME"]))
        try:
            name = name.relative_to(settings.BASE_DIR)  # SQLITE_NAME tính từ thư mục phần mềm
        except ValueError:
            pass
        custom = sqlite and str(name) != "db.sqlite3"
        html = render_to_string("errors/csdl_chua_cap_nhat.html", {
            "pending": pending, "sqlite_name": str(name) if custom else None, "sqlite": sqlite})
        return HttpResponse(html, status=503)
