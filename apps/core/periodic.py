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
        "nhac_ca_thieu_du_phong": remind_missing_backup(now),
        "nhac_thieu_gio_ra": _remind_missing_out(now),
    }


def _remind_missing_out(now):
    from apps.staff.timekeeping import remind_missing

    return remind_missing(now)


def remind_missing_backup(now=None):
    """GD-08: ghi nhắc Chủ quán một lần cho mỗi ca chưa có người duyệt dự phòng (màn hình Trang chủ luôn hiện)."""
    from apps.audit.models import Action, AuditLog
    from apps.audit.services import record
    from apps.shifts.services import shifts_missing_backup

    reminded = []
    for shift in shifts_missing_backup(now):
        if AuditLog.objects.filter(object_type="shifts.Shift", object_id=str(shift.pk),
                                   reason=MISSING_BACKUP_REASON).exists():
            continue
        record(Action.STATUS_CHANGE, obj=shift, object_type="shifts.Shift", actor_label="hệ thống",
               after={"con_thieu": "người duyệt dự phòng"}, reason=MISSING_BACKUP_REASON)
        reminded.append(shift.pk)
    return reminded


MISSING_BACKUP_REASON = "Nhắc Chủ quán bổ sung người duyệt dự phòng trước giờ ca"
