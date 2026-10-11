"""Tham số quản trị sửa được trên ứng dụng (NFR-14), có lịch sử và thời điểm hiệu lực.

Mỗi tham số có giá trị mặc định ở đây; Chủ quán đặt giá trị mới ở Kiểm soát › Tham số.
Mỗi giá trị là một dòng ParameterValue có "hiệu lực từ"; đọc tham số luôn đọc theo một thời điểm.

Quy ước áp dụng cho nghiệp vụ đang dở (giả định GD-10, chờ Chủ quán xác nhận):
- Yêu cầu điều chỉnh giữ thời hạn mỗi cấp tại lúc tạo yêu cầu.
- Đối soát ca dùng ngưỡng có hiệu lực lúc kết ca và lưu ngưỡng đã dùng vào khoản chênh lệch.
- Kiểm kê lưu ngưỡng phần trăm đã dùng lúc gửi kết quả.
- Thời hạn báo cáo cuối ca tính theo giá trị có hiệu lực lúc ca kết thúc.
- Các kiểm tra còn lại (giới hạn điều chỉnh, ngưỡng tích lũy, ngày nhắc, giờ mở cửa) dùng giá trị
  tại thời điểm phát sinh sự kiện; ngoại lệ đã tạo không bị tính lại.
- Không cho đặt hiệu lực lùi về quá khứ để không làm đổi kết quả đã chốt.
"""

from django.core.exceptions import ValidationError
from django.utils import timezone

DEFAULTS = {
    # key: (giá trị mặc định, đơn vị, mô tả, nguồn)
    "approval_level_minutes": (3, "phút", "Thời hạn mỗi cấp duyệt yêu cầu điều chỉnh", "BRU-09"),
    "shift_report_hours": (2, "giờ", "Thời hạn gửi báo cáo cuối ca sau giờ kết thúc ca", "BRU-07"),
    "cash_threshold": (50000, "đồng", "Ngưỡng cảnh báo chênh lệch tiền mặt mỗi ca", "BRU-10"),
    "transfer_threshold": (50000, "đồng", "Ngưỡng cảnh báo chênh lệch chuyển khoản mỗi ca", "BRU-10"),
    "accumulated_manager_threshold": (100000, "đồng", "Ngưỡng tích lũy thiếu tiền trong tháng của một Quản lý ca", "BRU-11"),
    "accumulated_store_threshold": (300000, "đồng", "Ngưỡng cảnh báo thiếu tiền tích lũy trong tháng của toàn quán "
                                                    "(khác mục tiêu BO-01 dưới 200.000 đ)", "BRU-11"),
    "adjust_count_limit": (3, "yêu cầu", "Số yêu cầu điều chỉnh sau pha chế cho phép của một nhân viên trong ca", "BRU-12"),
    "post_prep_value_limit": (100000, "đồng", "Tổng giá trị món hủy sau pha chế cho phép trong ca", "BRU-12"),
    "backup_entry_hours": (1, "giờ", "Thời hạn nhập bù phiếu dự phòng sau khi có kết nối lại", "BRU-03"),
    "review_reminder_days": (3, "ngày", "Nhắc lại ngoại lệ chưa xem xét sau số ngày", "BRU-14"),
    "receipt_photo_threshold": (500000, "đồng", "Khoản chi từ mức này phải có ảnh chứng từ", "BRU-33"),
    "consumption_tolerance_percent": (5, "%", "Mức chênh lệch tiêu hao cho phép của nguyên liệu trọng yếu", "BRU-17"),
    "wait_standard_minutes": (10, "phút", "Chuẩn thời gian chờ trung vị của khung giờ", "BRU-27"),
    "bar_backlog_limit": (15, "ly", "Số ly tồn tại quầy cho phép cuối khung giờ", "BRU-27"),
    "alert_out_of_stock_minutes": (15, "phút", "Thời hạn xử lý cảnh báo Nguyên liệu Đã hết", "BRU-36"),
    "discrepancy_explain_hours": (24, "giờ", "Thời hạn Quản lý ca giải trình chênh lệch tiền vượt ngưỡng", "BRU-36"),
    "discrepancy_decide_days": (3, "ngày", "Thời hạn Chủ quán quyết định chênh lệch đã giải trình", "BRU-36"),
    "consumption_check_hours": (24, "giờ", "Thời hạn Quản lý ca kiểm tra chênh lệch tiêu hao", "BRU-36"),
    "purchase_late_days": (1, "ngày", "Thời hạn xử lý cảnh báo giao chậm", "BRU-36"),
    "count_confirm_days": (1, "ngày", "Thời hạn Chủ quán xác nhận chênh lệch kiểm kê vượt ngưỡng", "BRU-36"),
    "count_threshold_percent": (5, "%", "Ngưỡng chênh lệch kiểm kê từng lần cần Chủ quán xác nhận", "BRU-25"),
    "open_hour": (6, "giờ", "Giờ mở cửa (tính trường hợp thiếu nguyên liệu)", "BRU-26"),
    "close_hour": (22, "giờ", "Giờ đóng cửa (tính trường hợp thiếu nguyên liệu)", "BRU-26"),
}


# Căn cứ của giá trị mặc định: BRD nêu rõ, lấy từ ví dụ trong tiêu chí nghiệm thu, hay dự án tự đặt.
BRD, AC_EXAMPLE, ASSUMPTION = "Theo BRD", "Theo ví dụ trong tiêu chí nghiệm thu", "Giả định chờ Chủ quán xác nhận"
BASIS = {
    "approval_level_minutes": (BRD, "Bảng 5.2: mặc định 3 phút"),
    "shift_report_hours": (BRD, "Bảng 5.2: mặc định 2 giờ"),
    "cash_threshold": (AC_EXAMPLE, "AC-25 dùng ngưỡng tiền mặt 50.000 đ"),
    "transfer_threshold": (ASSUMPTION, "BRD chưa nêu ngưỡng chuyển khoản; tạm lấy bằng ngưỡng tiền mặt"),
    "accumulated_manager_threshold": (AC_EXAMPLE, "AC-28 dùng 100.000 đ mỗi Quản lý ca mỗi tháng"),
    "accumulated_store_threshold": (ASSUMPTION, "BRD chưa nêu ngưỡng toàn quán; tạm đặt 300.000 đ"),
    "adjust_count_limit": (AC_EXAMPLE, "AC-31 dùng 3 yêu cầu mỗi ca"),
    "post_prep_value_limit": (ASSUMPTION, "BRD chưa nêu mức giá trị hủy sau pha chế; tạm đặt 100.000 đ"),
    "review_reminder_days": (BRD, "Bảng 5.2: mặc định 3 ngày"),
    "backup_entry_hours": (BRD, "Bảng 5.2: mặc định 1 giờ"),
    "receipt_photo_threshold": (BRD, "BRU-33: 500.000 đ, áp dụng cho khoản chi tiền mặt; phiếu nhập luôn cần ảnh (AC-55)"),
    "count_threshold_percent": (AC_EXAMPLE, "AC-56 dùng ngưỡng 5%"),
    "alert_out_of_stock_minutes": (BRD, "Bảng 5.4: 15 phút"),
    "discrepancy_explain_hours": (BRD, "Bảng 5.4: giải trình trong 24 giờ"),
    "discrepancy_decide_days": (BRD, "Bảng 5.4: quyết định trong 3 ngày"),
    "consumption_check_hours": (BRD, "Bảng 5.4: kiểm tra trong 1 ngày"),
    "purchase_late_days": (BRD, "Bảng 5.4: 1 ngày"),
    "count_confirm_days": (BRD, "Bảng 5.4: 1 ngày"),
    "wait_standard_minutes": (AC_EXAMPLE, "AC-79 dùng chuẩn 10 phút"),
    "bar_backlog_limit": (ASSUMPTION, "BRD chưa nêu mức món tồn; tạm đặt 15 ly"),
    "consumption_tolerance_percent": (AC_EXAMPLE, "AC-32 dùng mức cho phép 5%"),
    "open_hour": (ASSUMPTION, "BRD chưa nêu giờ mở cửa; tạm đặt 6 giờ"),
    "close_hour": (AC_EXAMPLE, "AC-62: quán đóng cửa lúc 22 giờ"),
}


def _rows(key):
    from .models import ParameterValue

    return ParameterValue.objects.filter(key=key)


def get(key, at=None):
    """Giá trị đang áp dụng tại thời điểm `at` (mặc định: bây giờ)."""
    default = DEFAULTS[key][0]
    value = (_rows(key).filter(effective_from__lte=at or timezone.now())
             .order_by("-effective_from", "-id").values_list("value", flat=True).first())
    return default if value is None else type(default)(value)


def history(key):
    """Các lần đặt giá trị, mới nhất trước, kèm giá trị sắp có hiệu lực nếu có."""
    return _rows(key).select_related("set_by").order_by("-effective_from", "-id")


def set_value(key, value, actor, effective_from=None, reason=""):
    """Chủ quán đặt giá trị mới. Hiệu lực ngay hoặc từ một thời điểm trong tương lai; không lùi về quá khứ."""
    from apps.audit.models import Action
    from apps.audit.services import record

    from .models import ParameterValue

    if key not in DEFAULTS:
        raise ValidationError("Tham số không tồn tại.")
    if not actor.is_owner:
        raise ValidationError("Chỉ Chủ quán thay đổi tham số.")
    try:
        number = int(str(value).replace(".", "").strip())
    except ValueError:
        raise ValidationError("Giá trị phải là số nguyên không âm.")
    if number < 0:
        raise ValidationError("Giá trị phải là số nguyên không âm.")
    now = timezone.now()
    effective_from = effective_from or now
    if effective_from < now - timezone.timedelta(minutes=1):
        raise ValidationError("Không đặt hiệu lực lùi về quá khứ; kết quả đã chốt phải giữ nguyên.")
    before = get(key, at=effective_from)
    row = ParameterValue.objects.create(key=key, value=number, effective_from=effective_from, set_by=actor,
                                        reason=reason[:255])
    record(Action.UPDATE, actor=actor, obj=row, object_type="core.ParameterValue",
           before={key: before}, after={key: number, "hieu_luc_tu": timezone.localtime(effective_from).isoformat()},
           reason=reason or DEFAULTS[key][2])
    return row
