"""Hiện cột Trước/Sau của nhật ký cho người đọc: tên trường bằng chữ, số có dấu chấm ngăn nghìn, mã liên kết thành tên."""

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from django.apps import apps
from django.core.exceptions import FieldDoesNotExist
from django.db import models
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from apps.core import numbers, params

# Khóa tự đặt khi ghi nhật ký (không phải tên trường của bảng).
LABELS = {
    "ban": "Bàn", "ban_luc": "Bán lúc", "bang_chung": "Bằng chứng", "bo_sung": "Bổ sung", "ca": "Ca",
    "canh_bao": "Cảnh báo", "cap": "Người xử lý", "chenh_lech": "Chênh lệch", "ck_hoan": "Chuyển khoản hoàn",
    "ck_nhan": "Chuyển khoản nhận", "con_lai": "Còn lại", "con_thieu": "Còn thiếu", "cung_giao_dich": "Cùng giao dịch",
    "da_tra": "Đã trả", "da_xac_minh": "Đã xác minh", "dang_ky": "Đăng ký", "danh_muc": "Danh mục",
    "day_so": "Dãy số", "dem_duoc": "Đếm được", "dinh_chinh": "Đính chính", "don": "Đơn", "done": "Đã làm",
    "dong": "Số dòng", "doanh_thu_chuyen_khoan": "Doanh thu chuyển khoản", "doanh_thu_tien_mat": "Doanh thu tiền mặt",
    "gia_tri": "Giá trị", "giao": "Giao cho", "han": "Hạn", "ket_qua": "Kết quả", "lien_ket_don_cu": "Gắn với đơn cũ",
    "lo": "Lô", "loai": "Loại", "ly_do": "Lý do", "ma": "Mã", "muc_cho_phep": "Mức cho phép", "ngay_giao": "Ngày giao",
    "nguoi_nhan": "Người nhận", "nguon": "Nguồn", "nguong": "Ngưỡng", "nguyen_lieu": "Nguyên liệu",
    "nha_cung_cap": "Nhà cung cấp", "nhac_lai": "Số lần nhắc", "noi_dung": "Nội dung", "phai_co": "Phải có",
    "phieu_du_phong": "Phiếu dự phòng", "phuong_thuc": "Phương thức", "qua_han": "Quá hạn", "quy_tac": "Quy tắc",
    "so_cuoi_da_dung": "Số cuối đã dùng", "so_luong": "Số lượng", "so_o": "Số người cần", "so_phieu": "Số phiếu",
    "so_tien": "Số tiền", "su_co": "Sự cố", "summary": "Nội dung", "table": "Bàn", "tien_mat_dem": "Tiền mặt đếm được",
    "thanh_toan": "Thanh toán", "thanh_toan_goc": "Thanh toán gốc", "theo_don": "Theo đơn bán",
    "thoi_gian_xu_ly_phut": "Thời gian xử lý (phút)", "thu_hoi": "Thu hồi", "thuc_te": "Thực tế",
    "tieu_de": "Tiêu đề", "ton_vat_ly": "Tồn theo hệ thống", "total": "Tổng tiền", "trang_thai": "Trạng thái",
    "tuan": "Tuần", "ty_le": "Tỉ lệ", "vuot": "Vượt", "vuot_nguong": "Vượt ngưỡng", "xep": "Xếp ca",
    "cach_tinh": "Cách tính", "can": "Cần", "chep_tu": "Chép từ", "code": "Mã", "da_kiem_ke": "Đã kiểm kê",
    "dang_dung": "Đang dùng", "effective_from": "Hiệu lực từ", "gia_xac_nhan": "Giá xác nhận",
    "giai_trinh": "Giải trình", "han_uoc_tinh": "Hạn ước tính", "hieu_luc": "Hiệu lực", "hieu_luc_tu": "Hiệu lực từ",
    "ingredient": "Nguyên liệu", "kind": "Loại", "level": "Cấp duyệt", "lines": "Món", "mat_khau": "Mật khẩu",
    "mon": "Món", "muc": "Mức", "nhan_vien": "Nhân viên", "phien_ban": "Phiên bản",
    "phien_ban_du_lieu": "Phiên bản dữ liệu", "quantity": "Số lượng", "quyet_dinh": "Quyết định", "ra_ca": "Ra ca",
    "ra_ca_bo_sung": "Ra ca bổ sung", "sang": "Chuyển sang", "so_lo": "Số lô", "status": "Trạng thái",
    "tam_khoa": "Tạm khóa", "ton_that_tien": "Tổn thất tiền", "vai_tro": "Vai trò", "vao_ca": "Vào ca",
    "vi_tri": "Vị trí", "xac_nhan_nhan": "Xác nhận nhận hàng",
}
SKIP = {"id", "store", "created_at", "updated_at", "password"}
MAX_ITEMS = 8
DECIMAL_TEXT = re.compile(r"-?\d+\.\d+")
PERCENT_TEXT = re.compile(r"(-?\d+(?:\.\d+)?)%")


def model_of(object_type):
    try:
        return apps.get_model(object_type) if object_type else None
    except (LookupError, ValueError):
        return None


def type_label(object_type):
    model = model_of(object_type)
    return str(model._meta.verbose_name).capitalize() if model else object_type


def _field(model, key):
    try:
        field = model._meta.get_field(key) if model else None
    except FieldDoesNotExist:
        return None
    return None if field is not None and field.auto_created and not field.concrete else field  # bỏ quan hệ ngược


def _plain(value):
    if value is None or value == "" or value == []:
        return "trống"
    if isinstance(value, bool):
        return "Có" if value else "Không"
    if isinstance(value, int):
        return numbers.fmt(value, 0)
    if isinstance(value, float):
        return numbers.fmt(Decimal(str(value)))
    if isinstance(value, str):
        if DECIMAL_TEXT.fullmatch(value):
            return numbers.fmt(Decimal(value))
        percent = PERCENT_TEXT.fullmatch(value)
        if percent:
            return numbers.fmt(Decimal(percent.group(1))) + "%"
        moment = parse_datetime(value) if "T" in value else None
        if moment is not None:
            return timezone.localtime(moment).strftime("%H:%M %d/%m/%Y") if timezone.is_aware(moment) \
                else moment.strftime("%H:%M %d/%m/%Y")
        day = parse_date(value) if len(value) == 10 else None
        if day is not None:
            return day.strftime("%d/%m/%Y")
        return value if len(value) <= 160 else value[:157] + "…"
    if isinstance(value, (list, tuple)):
        return ", ".join(_plain(v) for v in value)
    if isinstance(value, dict):
        return "; ".join(f"{LABELS.get(k, k)}: {_plain(v)}" for k, v in value.items())
    if isinstance(value, (date, datetime)):
        return value.strftime("%d/%m/%Y")
    return str(value)


def _ids(value):
    """Mã bản ghi liên kết; None nếu giá trị là chữ (có nơi ghi tên thay cho mã)."""
    values = value if isinstance(value, list) else [value]
    return values if values and all(isinstance(v, int) and not isinstance(v, bool) for v in values) else None


def _text(field, value, names):
    if field is not None and value not in (None, "", []):
        if field.is_relation and _ids(value):
            target = field.related_model
            return ", ".join(names.get((target, v), f"#{v}") for v in _ids(value))
        if field.choices:
            return str(dict(field.flatchoices).get(value, value))
        if isinstance(field, models.DecimalField) and isinstance(value, (str, int, float)):
            try:
                return numbers.fmt(Decimal(str(value)))
            except InvalidOperation:
                pass
    return _plain(value)


def describe(logs):
    """Gắn cho mỗi dòng nhật ký `changes`: [(nhãn, trước, sau)], `more`: số mục bị ẩn và `type_label`."""
    logs = list(logs)
    wanted = {}
    for log in logs:
        model = model_of(log.object_type)
        for data in (log.before, log.after):
            if not isinstance(data, dict):
                continue
            for key, value in data.items():
                field = _field(model, key)
                if field is not None and field.is_relation and _ids(value):
                    wanted.setdefault(field.related_model, set()).update(_ids(value))
    names = {}
    for target, pks in wanted.items():
        for obj in target._default_manager.filter(pk__in=pks):
            names[(target, obj.pk)] = str(obj)
    for log in logs:
        model = model_of(log.object_type)
        log.type_label = type_label(log.object_type)
        before = log.before if isinstance(log.before, dict) else {}
        after = log.after if isinstance(log.after, dict) else {}
        keys = [k for k in after if k not in SKIP] + [k for k in before if k not in after and k not in SKIP]
        changes = []
        for key in keys:
            field = _field(model, key)
            if field is not None and hasattr(field, "verbose_name"):
                label = str(field.verbose_name).capitalize()
            elif key in params.DEFAULTS:
                label = params.DEFAULTS[key][2]
            else:
                label = LABELS.get(key, key.replace("_", " ").capitalize())
            old = _text(field, before[key], names) if key in before else None
            new = _text(field, after[key], names) if key in after else None
            if old is not None and old == new:
                continue
            changes.append((label, old, new))
        log.changes = changes[:MAX_ITEMS]
        log.more = max(0, len(changes) - MAX_ITEMS)
        log.raw = None if isinstance(log.before, (dict, type(None))) and isinstance(log.after, (dict, type(None))) \
            else (_plain(log.before), _plain(log.after))
    return logs
