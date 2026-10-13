"""Các kiểm tra quá hạn chạy định kỳ, tách khỏi thao tác mở màn hình.

Màn hình luôn tính trạng thái đúng khi đọc (cấp duyệt hiện hành, lần đặt giao chậm, ngoại lệ cần nhắc,
ca trễ dữ liệu); tác vụ này chỉ ghi các thay đổi trạng thái kèm nhật ký đúng thời điểm và là nơi
gắn thêm thông báo đẩy về sau (FR-51, NFR-23). Chạy bằng lệnh `manage.py chay_dinh_ky`.
"""

from django.utils import timezone


def run_all(now=None):
    from apps.inventory import operations as inventory_ops
    from apps.orders import adjustments

    now = now or timezone.now()
    return {
        "chuyen_cap_yeu_cau": adjustments.escalate_due(now),
        "dat_hang_giao_cham": [po.pk for po in inventory_ops.refresh_late(timezone.localdate(now))],
        "nhac_thieu_gio_ra": _remind_missing_out(now),
        "du_bao": _daily_forecast(now),
        "ke_hoach_mua": _purchase_plans(now),
        "canh_bao": _sync_alerts(now),
    }


def _daily_forecast(now):
    """Mỗi ngày phát hành dự báo một lần sau khi dữ liệu ngày trước đã chốt (mục 6.1 khung dự báo)."""
    from apps.forecast.services import ensure_today_release

    rel = ensure_today_release(now)
    return rel.pk if rel else None


def _purchase_plans(now):
    """Tính toàn bộ kế hoạch mua nguyên liệu một lần sau mỗi giờ đóng cửa (mục 5.1 thiết kế mua nguyên liệu)."""
    from apps.forecast.planning import ensure_daily

    return ensure_daily(now)


def _sync_alerts(now):
    from apps.control import alerts

    return alerts.sync(now)


def _remind_missing_out(now):
    from apps.staff.timekeeping import remind_missing

    return remind_missing(now)
