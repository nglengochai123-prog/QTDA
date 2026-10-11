"""Tham số quản trị sửa được trên ứng dụng, có hiệu lực ngay khi lưu (NFR-14).

Mỗi tham số có giá trị mặc định ở đây; Chủ quán ghi đè ở Dữ liệu nền › Tham số.
"""

from decimal import Decimal

DEFAULTS = {
    # key: (giá trị mặc định, đơn vị, mô tả, nguồn)
    "approval_level_minutes": (3, "phút", "Thời hạn mỗi cấp duyệt yêu cầu điều chỉnh", "BRU-09"),
    "shift_report_hours": (2, "giờ", "Thời hạn gửi báo cáo cuối ca sau giờ kết thúc ca", "BRU-07"),
    "cash_threshold": (50000, "đồng", "Ngưỡng cảnh báo chênh lệch tiền mặt mỗi ca", "BRU-10"),
    "transfer_threshold": (50000, "đồng", "Ngưỡng cảnh báo chênh lệch chuyển khoản mỗi ca", "BRU-10"),
    "accumulated_manager_threshold": (100000, "đồng", "Ngưỡng tích lũy thiếu tiền trong tháng của một Quản lý ca", "BRU-11"),
    "accumulated_store_threshold": (300000, "đồng", "Ngưỡng tích lũy thiếu tiền trong tháng của toàn quán", "BRU-11"),
    "adjust_count_limit": (3, "yêu cầu", "Số yêu cầu điều chỉnh sau pha chế cho phép của một nhân viên trong ca", "BRU-12"),
    "post_prep_value_limit": (100000, "đồng", "Tổng giá trị món hủy sau pha chế cho phép trong ca", "BRU-12"),
    "review_reminder_days": (3, "ngày", "Nhắc lại ngoại lệ chưa xem xét sau số ngày", "BRU-14"),
    "receipt_photo_threshold": (500000, "đồng", "Khoản chi từ mức này phải có ảnh chứng từ", "BRU-33"),
    "count_threshold_percent": (5, "%", "Ngưỡng chênh lệch kiểm kê từng lần cần Chủ quán xác nhận", "BRU-25"),
    "open_hour": (6, "giờ", "Giờ mở cửa (tính trường hợp thiếu nguyên liệu)", "BRU-26"),
    "close_hour": (22, "giờ", "Giờ đóng cửa (tính trường hợp thiếu nguyên liệu)", "BRU-26"),
}


def get(key):
    from .models import Parameter

    default = DEFAULTS[key][0]
    row = Parameter.objects.filter(key=key).values_list("value", flat=True).first()
    if row is None:
        return default
    return type(default)(Decimal(row)) if isinstance(default, int) else row
