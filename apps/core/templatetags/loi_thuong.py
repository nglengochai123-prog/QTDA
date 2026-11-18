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

@register.filter
def chenh_tien(value):
    """Số chênh lệch tiền để người đọc: -70000 -> "Thiếu 70.000 đ", 20000 -> "Dư 20.000 đ", 0 -> "Khớp"."""
    try:
        value = int(value)
    except (TypeError, ValueError):
        return value
    if not value:
        return "Khớp"
    amount = f"{abs(value):,}".replace(",", ".")
    return f"Thiếu {amount} đ" if value < 0 else f"Dư {amount} đ"


@register.filter
def so_ngay_truoc(value):
    """Số ngày từ thời điểm `value` đến hôm nay theo giờ quán (0 là hôm nay); dùng để báo số liệu đã cũ."""
    if not value:
        return None
    from django.utils import timezone

    return (timezone.localdate() - timezone.localtime(value).date()).days


@register.filter
def gia_tri(bound_field):
    """Giá trị một ô biểu mẫu viết thành chữ cho trang chỉ xem: tên mục đã chọn thay cho ô chọn bị khóa, ngày giờ và số
    theo cách viết Việt Nam, "—" khi để trống."""
    from datetime import datetime, time
    from decimal import Decimal

    from django import forms
    from django.template.defaultfilters import date as date_filter, floatformat
    from django.utils import timezone

    field, value = bound_field.field, bound_field.value()
    if isinstance(field, forms.BooleanField):
        return "Có" if value else "Không"
    if value is None or value == "" or value == []:
        return "—"
    chosen = [str(v) for v in value] if isinstance(value, (list, tuple, set)) else [str(value)]
    if isinstance(field, forms.ModelChoiceField):
        # Hỏi thẳng theo khóa: danh sách chọn có thể đã lọc bỏ mục cũ (món ngừng bán) mà bản ghi vẫn trỏ tới.
        objs = field.queryset.model._default_manager.filter(pk__in=chosen)
        return ", ".join(field.label_from_instance(o) for o in objs) or "—"
    if hasattr(field, "choices"):
        labels = []
        for key, label in field.choices:
            if isinstance(label, (list, tuple)):  # nhóm lựa chọn
                labels += [str(lb) for k, lb in label if str(k) in chosen]
            elif str(key) in chosen:
                labels.append(str(label))
        return ", ".join(labels) or "—"
    if isinstance(value, datetime):
        return date_filter(timezone.localtime(value) if timezone.is_aware(value) else value, "H:i d/m/Y")
    if isinstance(value, date):
        return date_filter(value, "d/m/Y")
    if isinstance(value, time):
        return date_filter(value, "H:i")
    if isinstance(value, (Decimal, float)) or (isinstance(value, int) and not isinstance(value, bool)):
        return floatformat(value, "-3g")
    return value


@register.filter
def la_so(bound_field):
    """Ô số (lượng, giá, số phút) để canh phải cột trong bảng chỉ xem."""
    from django import forms

    return isinstance(bound_field.field, (forms.IntegerField, forms.DecimalField, forms.FloatField))
