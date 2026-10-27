"""Đọc ngày từ tham số trang (?tu=, ?den=, ?ngay=, ?tuan=, ?thang=)."""

from datetime import date

EARLIEST, LATEST = date(2000, 1, 1), date(2099, 12, 31)


def parse_day(value):
    """Ngày dạng YYYY-MM-DD; sai định dạng hoặc ngoài khoảng 2000–2099 thì trả None để trang dùng ngày mặc định.

    Giới hạn khoảng để ngày như 9999-12-31 không làm phép cộng thêm một ngày bị tràn."""
    try:
        day = date.fromisoformat(str(value or ""))
    except ValueError:
        return None
    return day if EARLIEST <= day <= LATEST else None


def parse_month(value):
    """Ngày đầu tháng từ chuỗi YYYY-MM, hoặc None."""
    return parse_day(f"{value or ''}-01")
