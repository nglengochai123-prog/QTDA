"""Bộ nhớ đệm trong phạm vi một yêu cầu GET.

Một trang báo cáo đọc cùng tham số hoặc cùng sổ phân bổ doanh thu nhiều lần (bảng điều khiển đọc tham số hàng trăm lần,
báo cáo doanh thu đọc sổ thu của cùng kỳ hai lần). Trong một yêu cầu GET dữ liệu không đổi nên đọc một lần là đủ.
Ngoài yêu cầu (lệnh quản trị, tác vụ định kỳ, test gọi thẳng hàm) và trong yêu cầu ghi (POST) thì không đệm gì.
"""

from contextvars import ContextVar

_store = ContextVar("lam_request_cache", default=None)
_MISSING = object()


def get_or_set(key, compute):
    store = _store.get()
    if store is None:
        return compute()
    value = store.get(key, _MISSING)
    if value is _MISSING:
        value = store[key] = compute()
    return value


def clear():
    store = _store.get()
    if store is not None:
        store.clear()


class RequestCacheMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        token = _store.set({} if request.method in ("GET", "HEAD") else None)
        try:
            return self.get_response(request)
        finally:
            _store.reset(token)
