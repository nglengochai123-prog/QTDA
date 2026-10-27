"""Đọc số người dùng gõ theo kiểu Việt Nam, dùng chung cho mọi màn hình nhập tiền và số lượng."""

import re
from decimal import Decimal, InvalidOperation

from django import forms
from django.core.exceptions import ValidationError
from django.db import models

MAX_NUMBER = Decimal(10) ** 10


def vnd(value, label, allow_zero=False):
    """Số tiền đồng gõ theo kiểu Việt Nam: "2.982.000", "2,982,000", "2 982 000 đ" đều là 2982000.

    Dấu chấm hay phẩy theo sau đúng ba chữ số là phân cách hàng nghìn; theo sau một hai chữ số là phần lẻ
    (đơn giá theo gram có thể lẻ, ví dụ "31,5") và được làm tròn về đồng."""
    raw = str(value if value is not None else "").replace("đ", "").replace(" ", "").strip()
    if re.fullmatch(r"\d{1,3}([.,]\d{3})+|\d+", raw):
        number = int(re.sub(r"[.,]", "", raw))
    elif re.fullmatch(r"\d+[.,]\d{1,2}", raw):
        number = int(Decimal(raw.replace(",", ".")).to_integral_value())
    else:
        raise ValidationError(f"{label} không hợp lệ.")
    if number == 0 and not allow_zero:
        raise ValidationError(f"{label} phải lớn hơn 0.")
    if number >= MAX_NUMBER:
        raise ValidationError(f"{label} quá lớn.")
    return number


def qty(value, label, allow_zero=False):
    """Số lượng gõ theo kiểu Việt Nam như màn hình hiển thị: "1.866" là 1866, "1,5" là 1,5."""
    raw = str(value).strip().replace(" ", "")
    if re.fullmatch(r"\d{1,3}(\.\d{3})+(,\d+)?", raw):
        raw = raw.replace(".", "")
    try:
        number = Decimal(raw.replace(",", "."))
    except (InvalidOperation, TypeError):
        raise ValidationError(f"{label} không hợp lệ.")
    if not number.is_finite():
        raise ValidationError(f"{label} không hợp lệ.")
    if number >= MAX_NUMBER:  # cột số lượng trong CSDL giữ tối đa 10 chữ số phần nguyên
        raise ValidationError(f"{label} quá lớn.")
    if number < 0 or (number == 0 and not allow_zero):
        raise ValidationError(f"{label} phải lớn hơn 0.")
    return number


def whole(value, label=None):
    """Số nguyên không âm: "50.000", "50,000", "50 000" là 50000; "2,5" hay "2.5" không hợp lệ (không đoán)."""
    raw = str(value if value is not None else "").replace("đ", "").replace(" ", "").strip()
    if re.fullmatch(r"\d{1,3}([.,]\d{3})+", raw):
        raw = re.sub(r"[.,]", "", raw)
    if not re.fullmatch(r"\d{1,15}", raw):
        raise ValidationError(f"{label or 'Giá trị'} phải là số nguyên không âm, ví dụ 50.000.")
    return int(raw)


def fmt(value, places=2):
    """Số để người đọc: dấu chấm ngăn nghìn, dấu phẩy phần lẻ, bỏ số 0 thừa: 1094.50 -> "1.094,5"."""
    whole, _, frac = f"{Decimal(value):,.{places}f}".partition(".")
    frac = frac.rstrip("0")
    whole = whole.replace(",", ".")
    return f"{whole},{frac}" if frac else whole


# ---------------- Ô số trong form: ô chữ, gõ và hiện theo kiểu Việt Nam ----------------
# Ô <input type="number"> của trình duyệt không nhận dấu chấm ngăn nghìn, còn ô số mặc định của Django đọc "25.000"
# thành 25. Mọi ô số trong form Dữ liệu nền dùng hai lớp dưới đây.

class SoNguyenField(forms.IntegerField):
    """Số nguyên: "25.000", "25,000", "25000" đều là 25000."""

    widget = forms.TextInput
    default_error_messages = {"invalid": "Nhập số nguyên, ví dụ 25.000.",
                              "min_value": "Nhập số từ %(limit_value)s trở lên.",
                              "max_value": "Nhập số không quá %(limit_value)s."}

    def widget_attrs(self, widget):
        return {**super().widget_attrs(widget), "inputmode": "numeric", "autocomplete": "off"}

    def to_python(self, value):
        if value in self.empty_values:
            return None
        raw = str(value).replace("đ", "").replace(" ", "").strip()
        sign, body = ("-", raw[1:]) if raw.startswith("-") else ("", raw)
        if re.fullmatch(r"\d{1,3}([.,]\d{3})+", body):
            body = re.sub(r"[.,]", "", body)
        if not re.fullmatch(r"\d{1,15}", body):
            raise ValidationError(self.error_messages["invalid"], code="invalid")
        return int(sign + body)

    def prepare_value(self, value):
        if isinstance(value, int) and not isinstance(value, bool):
            return fmt(value, 0)
        return value


class SoThapPhanField(forms.DecimalField):
    """Số lượng: "1.000" là 1000, "1,5" là 1,5, "1.000,5" là 1000,5 (như cách màn hình hiển thị)."""

    widget = forms.TextInput
    default_error_messages = {"invalid": "Nhập một số, ví dụ 1.000 hoặc 1,5.",
                              "min_value": "Nhập số từ %(limit_value)s trở lên.",
                              "max_value": "Nhập số không quá %(limit_value)s.",
                              "max_digits": "Số quá lớn; kiểm tra lại số đã gõ.",
                              "max_whole_digits": "Số quá lớn; kiểm tra lại số đã gõ.",
                              "max_decimal_places": "Chỉ ghi tối đa %(max)s chữ số sau dấu phẩy."}

    def widget_attrs(self, widget):
        return {**super().widget_attrs(widget), "inputmode": "decimal", "autocomplete": "off"}

    def to_python(self, value):
        if value in self.empty_values:
            return None
        raw = str(value).replace(" ", "").strip()
        if re.fullmatch(r"-?\d{1,3}(\.\d{3})+(,\d+)?", raw):
            raw = raw.replace(".", "")
        return super().to_python(raw.replace(",", "."))

    def prepare_value(self, value):
        if isinstance(value, Decimal) and value.is_finite():
            return fmt(value, self.decimal_places if self.decimal_places is not None else 2)
        return value


def formfield(db_field, **kwargs):
    """formfield_callback cho ModelForm: ô số dùng hai lớp trên, các ô khác giữ mặc định."""
    if db_field.choices or db_field.primary_key or db_field.is_relation:
        return db_field.formfield(**kwargs)
    if isinstance(db_field, models.DecimalField):
        return db_field.formfield(**{"form_class": SoThapPhanField, "widget": forms.TextInput, **kwargs})
    if isinstance(db_field, models.IntegerField):
        return db_field.formfield(**{"form_class": SoNguyenField, "widget": forms.TextInput, **kwargs})
    return db_field.formfield(**kwargs)
