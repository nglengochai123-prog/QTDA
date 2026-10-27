"""Tham số quản trị sửa được trên ứng dụng (NFR-14), có lịch sử và thời điểm hiệu lực.

Mỗi tham số có giá trị mặc định ở đây; Chủ quán đặt giá trị mới ở Kiểm soát › Tham số.
Mỗi giá trị là một dòng ParameterValue có "hiệu lực từ"; đọc tham số luôn đọc theo một thời điểm.

Tham số của mô hình (dự báo, kế hoạch mua, gợi ý số người: MODEL_KEYS) không hiện trên giao diện và không đặt được
trên ứng dụng. Muốn đổi thì sửa giá trị mặc định ngay trong file này rồi khởi động lại ứng dụng.

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
    "approval_level_minutes": (3, "phút", "Thời hạn duyệt yêu cầu điều chỉnh", "BRU-09"),
    "shift_report_hours": (2, "giờ", "Thời hạn gửi báo cáo cuối ca sau giờ kết thúc ca", "BRU-07"),
    "cash_threshold": (50000, "đồng", "Ngưỡng cảnh báo chênh lệch tiền mặt mỗi ca", "BRU-10"),
    "transfer_threshold": (50000, "đồng", "Ngưỡng cảnh báo chênh lệch chuyển khoản mỗi ca", "BRU-10"),
    "accumulated_manager_threshold": (100000, "đồng", "Ngưỡng tích lũy thiếu tiền trong tháng của một người phụ trách ca", "BRU-11"),
    "accumulated_store_threshold": (300000, "đồng", "Ngưỡng cảnh báo thiếu tiền tích lũy trong tháng của toàn quán "
                                                    "(khác mục tiêu BO-01 dưới 200.000 đ)", "BRU-11"),
    "adjust_count_limit": (3, "yêu cầu", "Số yêu cầu điều chỉnh sau pha chế cho phép của một nhân viên trong ca", "BRU-12"),
    "post_prep_value_limit": (100000, "đồng", "Tổng giá trị món hủy sau pha chế cho phép trong ca", "BRU-12"),
    "backup_entry_hours": (1, "giờ", "Thời hạn nhập bù phiếu dự phòng sau khi có kết nối lại", "BRU-03"),
    "review_reminder_days": (3, "ngày", "Nhắc lại ngoại lệ chưa xem xét sau số ngày", "BRU-14"),
    "receipt_photo_threshold": (500000, "đồng", "Khoản chi từ mức này phải có ảnh chứng từ", "BRU-33"),
    "consumption_tolerance_percent": (5, "%", "Mức chênh lệch tiêu hao cho phép của nguyên liệu trọng yếu", "BRU-17"),
    "wait_standard_minutes": (10, "phút", "Chuẩn thời gian khách chờ món trong khung giờ", "BRU-27"),
    "bar_backlog_limit": (15, "ly", "Số ly tồn tại quầy cho phép cuối khung giờ", "BRU-27"),
    "alert_out_of_stock_minutes": (15, "phút", "Thời hạn xử lý cảnh báo Nguyên liệu Đã hết", "BRU-36"),
    "discrepancy_explain_hours": (24, "giờ", "Thời hạn giải trình chênh lệch tiền vượt ngưỡng", "BRU-36"),
    "discrepancy_decide_days": (3, "ngày", "Thời hạn Chủ quán quyết định chênh lệch đã giải trình", "BRU-36"),
    "consumption_check_hours": (24, "giờ", "Thời hạn Chủ quán kiểm tra chênh lệch tiêu hao", "BRU-36"),
    "purchase_late_days": (1, "ngày", "Thời hạn xử lý cảnh báo giao chậm", "BRU-36"),
    "count_confirm_days": (1, "ngày", "Thời hạn Chủ quán xác nhận chênh lệch kiểm kê vượt ngưỡng", "BRU-36"),
    "count_threshold_percent": (5, "%", "Ngưỡng chênh lệch kiểm kê từng lần cần Chủ quán xác nhận", "BRU-25"),
    "open_hour": (6, "giờ", "Giờ mở cửa (tính trường hợp thiếu nguyên liệu)", "BRU-26"),
    "close_hour": (22, "giờ", "Giờ đóng cửa (tính trường hợp thiếu nguyên liệu; đóng lúc nửa đêm thì ghi 24)", "BRU-26"),
    # Dự báo nhu cầu theo khung lý thuyết Bayes động của dự án (12/10/2026)
    "forecast_horizon_days": (14, "ngày", "Độ dài chân trời dự báo", "Khung dự báo 4.2"),
    "forecast_delta_level_percent": (95, "%", "Hệ số chiết khấu mức nền (càng nhỏ càng thích nghi nhanh)", "Khung dự báo 3.1"),
    "forecast_delta_season_percent": (99, "%", "Hệ số chiết khấu hiệu ứng thứ trong tuần", "Khung dự báo 3.1"),
    "forecast_prior_max_days": (7, "ngày", "Sức nặng tối đa của nhận định Chủ quán (số ngày quan sát tương đương)", "Khung dự báo 2.1"),
    "forecast_min_history_days": (56, "ngày", "Số ngày dữ liệu đủ điều kiện để bắt đầu đánh giá có ý nghĩa", "Khung dự báo 5.3"),
    "forecast_paths": (1000, "đường", "Số đường mô phỏng khi tính tổng nhu cầu nhiều ngày", "Khung dự báo 4.2"),
    # Kế hoạch mua nguyên liệu (docs/THIET_KE_MUA_NGUYEN_LIEU.md)
    "plan_csl_critical_percent": (95, "%", "Mức phục vụ chu kỳ mặc định của nguyên liệu trọng yếu", "Thiết kế mua 6.4"),
    "plan_csl_normal_percent": (95, "%", "Mức phục vụ chu kỳ mặc định của nguyên liệu khác", "Thiết kế mua 6.4"),
    "plan_csl_long_life_percent": (98, "%", "Mức phục vụ chu kỳ tối thiểu của hàng để lâu (nhóm B)", "BO-02"),
    "plan_group_a_shelf_days": (14, "ngày", "Hạn dùng từ mức này trở xuống thì mặc định là nhóm A (dễ hỏng)", "Thiết kế mua 7.2"),
    "plan_a_review_days": (1, "ngày", "Nhóm A: chu kỳ kiểm tra R", "Thiết kế mua 7.2"),
    "plan_a_target_days": (2, "ngày", "Nhóm A: khoảng cách mua mong muốn T", "Thiết kế mua 7.2"),
    "plan_b_review_days": (7, "ngày", "Nhóm B: chu kỳ kiểm tra R", "Thiết kế mua 7.2"),
    "plan_b_review_weekday": (8, "thứ", "Nhóm B: ngày kiểm tra trong tuần (2 là thứ Hai … 8 là Chủ nhật)", "Thiết kế mua 7.2"),
    "plan_horizon_days": (35, "ngày", "Tầm hiển thị của dự báo nguyên liệu", "Thiết kế mua 4.3"),
    "plan_switch_gain_percent": (5, "%", "Chỉ đổi phương pháp dự báo khi sai số thấp hơn ít nhất mức này", "Thiết kế mua 4.4"),
    "plan_switch_weeks": (4, "tuần", "Khoảng gốc dự báo dùng để so khi đổi phương pháp", "Thiết kế mua 4.4"),
    "plan_bias_limit_percent": (50, "% của σ", "Độ chệch vượt mức này thì không dùng phương pháp đó", "Thiết kế mua 6.2"),
    "plan_blocked_limit_percent": (20, "%", "Tỷ lệ ngày bị chặn do hết hàng trong 8 tuần để cảnh báo dự báo thấp", "Thiết kế mua 5.5"),
    "plan_indirect_share_percent": (20, "%", "Món bị ngừng bán chiếm từ mức này tiêu hao của nguyên liệu thì ngày bị chặn gián tiếp", "Thiết kế mua 5.5"),
    "plan_reconcile_gap_permille": (10, "‰", "Lệch đối soát tiêu hao với sổ kho vượt mức này thì báo lỗi dữ liệu", "Thiết kế mua 5.3"),
    "plan_quantile_band_points": (3, "điểm %", "Cách phân vị chỉ bật khi độ phủ nằm trong CSL cộng trừ mức này", "Thiết kế mua 6.3"),
    # Đăng ký ca và lập lịch (FR-38, FR-39)
    "schedule_deadline_weekday": (5, "thứ", "Hạn đăng ký ca tuần sau: thứ trong tuần (2 là thứ Hai … 8 là Chủ nhật)", "BRU-29"),
    "schedule_deadline_hour": (12, "giờ", "Hạn đăng ký ca tuần sau: giờ trong ngày", "BRU-29"),
    "late_minutes": (5, "phút", "Vào ca sau giờ bắt đầu ca trong lịch quá số phút này thì Chấm công ghi là đi trễ", "FR-35"),
    "schedule_min_per_role": (1, "người", "Số người tối thiểu mỗi vị trí trong mỗi giờ quán mở", "BRU-28"),
    "schedule_productivity_pha_che": (0, "tải/người/giờ", "Sức làm của một pha chế khi bận liên tục (0: tự đo từ giờ gửi và "
                                                          "giờ pha xong)", "BRU-28"),
    "schedule_productivity_phuc_vu": (0, "tải/người/giờ", "Sức làm của một phục vụ khi bận liên tục (0: ước lượng thận trọng từ "
                                                          "các giờ không quá tải)", "BRU-28"),
    "schedule_productivity_thu_ngan": (0, "tải/người/giờ", "Sức làm của một thu ngân khi bận liên tục (0: ước lượng thận trọng "
                                                           "từ các giờ không quá tải)", "BRU-28"),
    "schedule_wait_target_minutes": (4, "phút", "Gợi ý số người: việc phải chờ trong hàng không quá số phút này trước khi có "
                                                "người làm", "BRU-27, BRU-28"),
    "schedule_service_percent": (70, "%", "Gợi ý số người: tỷ lệ việc mỗi giờ được bắt đầu trong số phút trên", "BRU-27, BRU-28"),
    # Kho theo lô (inventory/lots.py)
    "lot_near_expiry_days": (2, "ngày", "Báo lô Sắp hết hạn khi còn từ số ngày này trở xuống", "Kho theo lô"),
    "lot_near_expiry_percent": (20, "% hạn dùng", "Hoặc khi thời gian còn lại dưới phần này của thời hạn sử dụng "
                                                 "(lấy mức báo sớm hơn)", "Kho theo lô"),
}

# Tham số của mô hình: chỉ sửa trong file này (người dùng chỉ thấy kết quả, không thấy cách tính).
MODEL_KEYS = frozenset(k for k in DEFAULTS if k.startswith(("forecast_", "plan_"))) | {
    "schedule_productivity_pha_che", "schedule_productivity_phuc_vu", "schedule_productivity_thu_ngan",
    "schedule_wait_target_minutes", "schedule_service_percent"}


# Khoảng hợp lệ của tham số nghiệp vụ: chặn gõ nhầm (giờ 25, thứ 9, 500%) làm hỏng các phép tính theo giờ, theo thứ.
BOUNDS = {
    "approval_level_minutes": (1, 240), "shift_report_hours": (1, 72),
    "cash_threshold": (0, 10_000_000), "transfer_threshold": (0, 10_000_000),
    "accumulated_manager_threshold": (0, 100_000_000), "accumulated_store_threshold": (0, 100_000_000),
    "adjust_count_limit": (0, 100), "post_prep_value_limit": (0, 100_000_000), "backup_entry_hours": (1, 168),
    "review_reminder_days": (1, 60), "receipt_photo_threshold": (0, 100_000_000),
    "consumption_tolerance_percent": (0, 100), "wait_standard_minutes": (1, 120), "bar_backlog_limit": (1, 500),
    "alert_out_of_stock_minutes": (1, 1440), "discrepancy_explain_hours": (1, 720), "discrepancy_decide_days": (1, 60),
    "consumption_check_hours": (1, 720), "purchase_late_days": (1, 60), "count_confirm_days": (1, 60),
    "count_threshold_percent": (0, 100), "open_hour": (0, 23), "close_hour": (1, 24),
    "schedule_deadline_weekday": (2, 8), "schedule_deadline_hour": (0, 23), "late_minutes": (0, 240),
    "schedule_min_per_role": (0, 20), "lot_near_expiry_days": (0, 60), "lot_near_expiry_percent": (0, 100),
}


def business_keys():
    """Các tham số nghiệp vụ Chủ quán đặt trên ứng dụng, theo thứ tự khai báo."""
    return [k for k in DEFAULTS if k not in MODEL_KEYS]


# Căn cứ của giá trị mặc định: BRD nêu rõ, lấy từ ví dụ trong tiêu chí nghiệm thu, hay dự án tự đặt.
BRD, AC_EXAMPLE, ASSUMPTION = "Theo BRD", "Theo ví dụ trong tiêu chí nghiệm thu", "Giả định chờ Chủ quán xác nhận"
FRAMEWORK = "Theo khung lý thuyết dự báo"
BASIS = {
    "approval_level_minutes": (BRD, "Bảng 5.2: mặc định 3 phút"),
    "shift_report_hours": (BRD, "Bảng 5.2: mặc định 2 giờ"),
    "cash_threshold": (AC_EXAMPLE, "AC-25 dùng ngưỡng tiền mặt 50.000 đ"),
    "transfer_threshold": (ASSUMPTION, "BRD chưa nêu ngưỡng chuyển khoản; tạm lấy bằng ngưỡng tiền mặt"),
    "accumulated_manager_threshold": (AC_EXAMPLE, "AC-28 dùng 100.000 đ mỗi người phụ trách ca mỗi tháng"),
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
    "forecast_horizon_days": (FRAMEWORK, "Mục 4.2: dự báo từng ngày trong 14 ngày tới, cho phép cấu hình"),
    "forecast_delta_level_percent": (ASSUMPTION, "Mục 3.1: phải chọn qua đánh giá theo thời gian; tạm dùng 95% (mức thường dùng "
                                                 "trong West và Harrison 1997) đến khi đánh giá cuốn chiếu chọn lại"),
    "forecast_delta_season_percent": (ASSUMPTION, "Tạm dùng 99% để hiệu ứng thứ thay đổi chậm; chọn lại qua đánh giá"),
    "forecast_prior_max_days": (ASSUMPTION, "Mục 2.1: không tạo độ chắc chắn giả từ một ước lượng; tạm giới hạn 7 ngày, "
                                            "cần kiểm tra độ nhạy"),
    "forecast_min_history_days": (FRAMEWORK, "Mục 5.3: 8 đến 12 tuần dữ liệu ngày làm mốc khởi đầu đánh giá thử"),
    "forecast_paths": (ASSUMPTION, "Số đường mô phỏng đủ ổn định phân vị; chỉ ảnh hưởng độ mượt, không đổi phương pháp"),
    "plan_csl_critical_percent": (ASSUMPTION, "GD3: 95% cho nguyên liệu trọng yếu, k = 1,645"),
    "plan_csl_normal_percent": (ASSUMPTION, "GD3 đặt 90%; mô phỏng một năm cho thấy 90% để khoảng 1,2 lần thiếu mỗi tháng trên 18 "
                                            "nguyên liệu, vượt BO-02 khi đủ 60 nguyên liệu; 95% (k = 1,645) cùng hàng để lâu 98% "
                                            "đạt (docs/KET_QUA_MO_PHONG.md)"),
    "plan_csl_long_life_percent": (ASSUMPTION, "Chọn qua mô phỏng: hàng để lâu giữ thêm gần như không hỏng, nên dồn phần thiếu cho "
                                               "phép của BO-02 sang hàng tươi (cách phân bổ tổng số lần thiếu của Silver, Pyke "
                                               "và Thomas)"),
    "plan_group_a_shelf_days": (ASSUMPTION, "Mục 7.2: hạn dùng từ 14 ngày trở xuống là nhóm A"),
    "plan_a_review_days": (ASSUMPTION, "GD2: nhóm A kiểm tra mỗi tối lúc chốt ngày"),
    "plan_a_target_days": (ASSUMPTION, "GD2: nhóm A mua cách nhau khoảng 2 ngày"),
    "plan_b_review_days": (ASSUMPTION, "GD2: nhóm B kiểm tra mỗi tuần"),
    "plan_b_review_weekday": (ASSUMPTION, "GD2: nhóm B kiểm tra tối Chủ nhật"),
    "plan_horizon_days": (FRAMEWORK, "Mục 4.3: đủ cho tuần này, tuần sau và tháng này"),
    "plan_switch_gain_percent": (ASSUMPTION, "Mục 4.4, BRU-37: thấp hơn ít nhất 5% mới đổi phương pháp"),
    "plan_switch_weeks": (ASSUMPTION, "Mục 4.4: trên ít nhất 4 tuần gốc dự báo"),
    "plan_bias_limit_percent": (FRAMEWORK, "Mục 6.2: độ chệch vượt 0,5 σ h thì không dùng phương pháp"),
    "plan_blocked_limit_percent": (FRAMEWORK, "Mục 5.5: bị chặn trên 20% số ngày trong 8 tuần"),
    "plan_indirect_share_percent": (FRAMEWORK, "Mục 5.5: món bị ngừng bán chiếm từ 20% tiêu hao"),
    "plan_reconcile_gap_permille": (FRAMEWORK, "Mục 5.3: lệch trên 1% thì báo lỗi dữ liệu"),
    "plan_quantile_band_points": (FRAMEWORK, "Mục 6.3: độ phủ trong CSL cộng trừ 3 điểm phần trăm"),
    "schedule_deadline_weekday": (AC_EXAMPLE, "AC-85: hạn là 12 giờ trưa thứ Năm"),
    "schedule_deadline_hour": (AC_EXAMPLE, "AC-85: hạn là 12 giờ trưa thứ Năm"),
    "late_minutes": (ASSUMPTION, "BRD chưa nêu mức tính đi trễ; tạm 5 phút"),
    "schedule_min_per_role": (ASSUMPTION, "BRU-28 có mức tối thiểu mỗi vai trò nhưng chưa nêu số; tạm 1 người"),
    "schedule_productivity_pha_che": (BRD, "BRU-28: năng suất ban đầu do Chủ quán đặt. Để 0 thì hệ thống đo sức làm lúc mọi pha "
                                           "chế đều bận, không lấy trung vị cả giờ rảnh (xem docs/KET_QUA_MO_PHONG.md)"),
    "schedule_productivity_phuc_vu": (BRD, "BRU-28: năng suất do Chủ quán đặt; để 0 thì lấy giờ đông nhất đã làm kịp (phân vị 98 tải "
                                           "mỗi người ở giờ không quá tải), thường thấp hơn sức làm thật nên gợi ý dư người"),
    "schedule_productivity_thu_ngan": (BRD, "BRU-28: như phục vụ"),
    "schedule_wait_target_minutes": (ASSUMPTION, "Chọn qua mô phỏng hàng đợi: chờ trong hàng 4 phút cộng thời gian pha và mang ra "
                                                 "vẫn dưới chuẩn 10 phút của AC-79"),
    "schedule_service_percent": (ASSUMPTION, "Chọn qua mô phỏng: 70% cho khoảng 96% số giờ đạt chuẩn chờ (BO-03 đòi 90%), giờ "
                                             "công chỉ hơn lịch cũ khoảng 5% khi đã đặt sức làm; 80% thêm khoảng 7% giờ công"),
    "lot_near_expiry_days": (ASSUMPTION, "Sữa tươi hạn 7 ngày: báo trước 2 ngày đủ để đẩy món dùng sữa hoặc chuyển sang làm "
                                         "đồ uống khác"),
    "lot_near_expiry_percent": (ASSUMPTION, "Hàng hạn dài (siro 1 năm) cần báo sớm hơn 2 ngày: 20% hạn dùng là khoảng 2 tháng, "
                                            "đủ một vòng mua hàng nhóm B để giảm đặt thêm"),
}


def _rows(key):
    from .models import ParameterValue

    return ParameterValue.objects.filter(key=key)


def get(key, at=None):
    """Giá trị đang áp dụng tại thời điểm `at` (mặc định: bây giờ). Tham số mô hình luôn lấy giá trị trong file."""
    default = DEFAULTS[key][0]
    if key in MODEL_KEYS:
        return default
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
    if key in MODEL_KEYS:
        raise ValidationError("Tham số của mô hình chỉ sửa trong file apps/core/params.py.")
    if not actor.is_owner:
        raise ValidationError("Chỉ Chủ quán thay đổi tham số.")
    from .numbers import whole

    number = whole(value)
    now = timezone.now()
    effective_from = effective_from or now
    if effective_from < now - timezone.timedelta(minutes=1):
        raise ValidationError("Không đặt hiệu lực lùi về quá khứ; kết quả đã chốt phải giữ nguyên.")
    low, high = BOUNDS.get(key, (0, 10**15))
    if not low <= number <= high:
        from .numbers import fmt

        unit = DEFAULTS[key][1]
        if unit == "thứ":
            span = f"{low} (thứ Hai) đến {high} (Chủ nhật)"
        elif unit.startswith("%"):
            span = f"{low}% đến {high}%"
        else:
            span = f"{fmt(low, 0)} đến {fmt(high, 0)} {unit}"
        raise ValidationError(f"{DEFAULTS[key][2]}: nhập từ {span}.")
    if key in ("open_hour", "close_hour"):
        other = "close_hour" if key == "open_hour" else "open_hour"
        opening, closing = (number, get(other, at=effective_from)) if key == "open_hour" else (
            get(other, at=effective_from), number)
        if opening >= closing:
            raise ValidationError(f"Giờ mở cửa ({opening} giờ) phải trước giờ đóng cửa ({closing} giờ).")
    before = get(key, at=effective_from)
    row = ParameterValue.objects.create(key=key, value=number, effective_from=effective_from, set_by=actor,
                                        reason=reason[:255])
    record(Action.UPDATE, actor=actor, obj=row, object_type="core.ParameterValue",
           before={key: before}, after={key: number, "hieu_luc_tu": timezone.localtime(effective_from).isoformat()},
           reason=reason or DEFAULTS[key][2])
    return row
