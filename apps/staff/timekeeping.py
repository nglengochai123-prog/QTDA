"""Chấm công vào ca, ra ca theo vai trò (FR-35, BRU-31, AC-76 đến AC-78).

Chưa có lịch ca trên hệ thống (lập lịch FR-39 thuộc Giai đoạn 2), nên giờ công tính theo giờ vào và ra.
Lượt thiếu giờ ra không được tính giờ cho đến khi Quản lý ca bổ sung kèm lý do.
Một người được tính có mặt trong khung giờ một tiếng khi làm ít nhất nửa khung đó (giả định GD-20).
"""

from datetime import datetime, time, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Role
from apps.audit.models import Action
from apps.audit.services import record
from apps.core.idempotency import run_once
from apps.core.models import Store

from .models import Attendance

WORK_ROLES = [Role.QUAN_LY_CA, Role.THU_NGAN, Role.PHUC_VU, Role.PHA_CHE]


def open_attendance(user):
    return Attendance.objects.filter(user=user, clock_out__isnull=True).order_by("-clock_in").first()


def clock_in(user, operation_key, role):
    payload = {"role": role}

    def action():
        if role not in WORK_ROLES or not user.has_role(role):
            raise ValidationError("Chọn vai trò bạn đảm nhận được.")
        current = open_attendance(user)
        if current is not None:
            raise ValidationError(f"Bạn đang trong ca từ {timezone.localtime(current.clock_in):%H:%M}; ra ca trước "
                                  f"rồi mới vào ca mới.")
        att = Attendance.objects.create(store=user.store or Store.get_default(), user=user, role=role, clock_in=timezone.now())
        record(Action.CREATE, actor=user, obj=att, object_type="staff.Attendance",
               after={"vao_ca": timezone.localtime(att.clock_in).isoformat(), "vai_tro": att.get_role_display()})
        return {"attendance": att.pk}

    return run_once(operation_key, "clock_in", payload, action, actor=user)


def clock_out(user, operation_key):
    def action():
        att = open_attendance(user)
        if att is None:
            raise ValidationError("Bạn chưa vào ca.")
        att.clock_out = timezone.now()
        att.save(update_fields=["clock_out", "updated_at"])
        record(Action.UPDATE, actor=user, obj=att, object_type="staff.Attendance",
               after={"ra_ca": timezone.localtime(att.clock_out).isoformat()})
        return {"attendance": att.pk}

    return run_once(operation_key, "clock_out", {}, action, actor=user)


@transaction.atomic
def supplement_clock_out(manager, attendance_id, when, reason):
    """Quản lý ca bổ sung giờ ra bị thiếu kèm lý do (AC-78)."""
    from apps.accounts.permissions import Cap, user_can

    if not user_can(manager, Cap.TIMEKEEPING_ADJUST):
        raise ValidationError("Chỉ Quản lý ca hoặc Chủ quán bổ sung giờ ra ca.")
    att = Attendance.objects.select_for_update().get(pk=attendance_id)
    if att.clock_out is not None:
        raise ValidationError("Lượt chấm công này đã có giờ ra.")
    if not str(reason or "").strip():
        raise ValidationError("Ghi lý do bổ sung giờ ra.")
    if timezone.is_naive(when):
        when = timezone.make_aware(when)
    if when <= att.clock_in or when > timezone.now():
        raise ValidationError("Giờ ra phải sau giờ vào và không ở tương lai.")
    att.clock_out, att.out_supplemented_by, att.out_reason = when, manager, reason.strip()
    att.save(update_fields=["clock_out", "out_supplemented_by", "out_reason", "updated_at"])
    record(Action.UPDATE, actor=manager, obj=att, object_type="staff.Attendance",
           after={"ra_ca_bo_sung": timezone.localtime(when).isoformat(), "nhan_vien": str(att.user)}, reason=reason)
    return att


def missing_clock_out(now=None):
    """Lượt vào ca của ngày trước mà chưa ra ca: Thiếu giờ ra (AC-77)."""
    now = now or timezone.now()
    start_of_today = timezone.make_aware(datetime.combine(timezone.localdate(now), time.min))
    return Attendance.objects.filter(clock_out__isnull=True, clock_in__lt=start_of_today).select_related("user")


def valid_hours(att):
    if att.clock_out is None:
        return Decimal(0)
    seconds = (att.clock_out - att.clock_in).total_seconds()
    return (Decimal(seconds) / 3600).quantize(Decimal("0.01"))


def presence(start, end):
    """Số người có mặt theo vai trò trong khung [start, end): làm ít nhất nửa khung (GD-20)."""
    half = (end - start) / 2
    counts = {r: 0 for r in WORK_ROLES}
    for att in Attendance.objects.filter(clock_in__lt=end).exclude(clock_out__lte=start).exclude(clock_out=None):
        overlap = min(att.clock_out, end) - max(att.clock_in, start)
        if overlap >= half:
            counts[att.role] = counts.get(att.role, 0) + 1
    return counts


def remind_missing(now=None):
    """Tác vụ định kỳ: ghi nhắc Quản lý ca một lần cho mỗi lượt thiếu giờ ra."""
    from apps.audit.models import AuditLog

    reminded = []
    for att in missing_clock_out(now):
        if AuditLog.objects.filter(object_type="staff.Attendance", object_id=str(att.pk), reason=MISSING_OUT).exists():
            continue
        record(Action.STATUS_CHANGE, obj=att, object_type="staff.Attendance", actor_label="hệ thống",
               after={"trang_thai": "Thiếu giờ ra", "nhan_vien": str(att.user)}, reason=MISSING_OUT)
        reminded.append(att.pk)
    return reminded


MISSING_OUT = "Thiếu giờ ra: nhắc Quản lý ca bổ sung"
_ = timedelta
