"""Phân trang dùng chung cho các danh sách tra cứu."""

from django.core.paginator import Paginator

PER_PAGE = 30


def paginate(request, queryset, per_page=PER_PAGE):
    """Trả (trang hiện tại, chuỗi tham số lọc không có số trang) để giữ bộ lọc khi chuyển trang."""
    page = Paginator(queryset, per_page).get_page(request.GET.get("trang"))
    params = request.GET.copy()
    params.pop("trang", None)
    return page, params.urlencode()
