"""Hiển thị chữ do hệ thống tự ghi cho người dùng đọc: bỏ mã yêu cầu nội bộ (BRU-12, AC-36…) còn trong dữ liệu
đã lưu trước đây, đổi số phần trăm "8.33%" sang cách viết Việt Nam "8,33%", "tháng 2026-10" thành "tháng 10/2026"."""

import re
from datetime import date

from django import template

register = template.Library()

CODES = re.compile(r"\s*\((?:(?:BRU|AC|FR|NFR|UC)-\d+[a-z]?(?:,\s*)?)+\)")
PERCENT = re.compile(r"(\d+)\.(\d+)%")
MONTH = re.compile(r"tháng (\d{4})-(\d{2})\b")


def _percent(match):
    frac = match[2].rstrip("0")
    return f"{match[1]},{frac}%" if frac else f"{match[1]}%"


@register.filter
def loi_thuong(text):
    text = CODES.sub("", str(text or ""))
    return MONTH.sub(r"tháng \2/\1", PERCENT.sub(_percent, text))


THU = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"]


@register.filter
def ngay_thu(value):
    """Ngày lưu dạng "2026-10-26" (trong dữ liệu JSON) hay kiểu date thành "T2 26/10"."""
    if isinstance(value, str):
        try:
            value = date.fromisoformat(value[:10])
        except ValueError:
            return value
    if not isinstance(value, date):
        return value
    return f"{THU[value.weekday()]} {value:%d/%m}"


@register.filter
def ngay_iso(value):
    """"2026-10-12" thành "12/10/2026"."""
    try:
        return f"{date.fromisoformat(str(value)[:10]):%d/%m/%Y}"
    except ValueError:
        return value


@register.filter
def phut(minutes):
    """Số phút để người đọc: 45 -> "45 phút", 546 -> "9 giờ 6 phút", 3000 -> "2 ngày 2 giờ"."""
    try:
        minutes = int(minutes)
    except (TypeError, ValueError):
        return minutes
    if minutes < 60:
        return f"{minutes} phút"
    hours, rest = divmod(minutes, 60)
    if hours < 24:
        return f"{hours} giờ {rest} phút" if rest else f"{hours} giờ"
    days, hours = divmod(hours, 24)
    return f"{days} ngày {hours} giờ" if hours else f"{days} ngày"


@register.filter
def nhan(field, label):
    """Ô nhập kèm aria-label, cho bảng nhập nhiều dòng nơi tiêu đề cột thay cho nhãn."""
    return field.as_widget(attrs={"aria-label": label})
