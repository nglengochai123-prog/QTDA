"""Chấm công vào ca, ra ca theo vai trò (FR-35, BRU-31, AC-76 đến AC-78).

Chưa có lịch ca trên hệ thống (lập lịch FR-39 thuộc Giai đoạn 2), nên giờ công tính theo giờ vào và ra.
Lượt thiếu giờ ra không được tính giờ cho đến khi Chủ quán bổ sung kèm lý do.
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

WORK_ROLES = [Role.THU_NGAN, Role.PHUC_VU, Role.PHA_CHE]
MAX_SHIFT_HOURS = 18  # lượt làm dài hơn mức này thường là quên bấm Ra ca hoặc chọn nhầm ngày


def open_attendance(user):
    return Attendance.objects.filter(user=user, clock_out__isnull=True).order_by("-clock_in").first()


def clock_in(user, operation_key, role):
    payload = {"role": role}

    def action():
        if role not in WORK_ROLES or not user.has_role(role):
            raise ValidationError("Chọn vai trò bạn đảm nhận được.")
        current = open_attendance(user)
        if current is not None:
            since = timezone.localtime(current.clock_in)
            if is_forgotten(current):
                raise ValidationError(f"Lượt vào ca lúc {since:%H:%M %d/%m} chưa có giờ ra; báo Chủ quán bổ sung giờ "
                                      f"ra rồi mới vào ca mới.")
            raise ValidationError(f"Bạn đang trong ca từ {since:%H:%M}; ra ca trước rồi mới vào ca mới.")
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
        if (timezone.now() - att.clock_in).total_seconds() > MAX_SHIFT_HOURS * 3600:
            # Trang mở từ hôm trước: ra ca bây giờ sẽ tính cả đêm vào giờ công.
            raise ValidationError(f"Lượt vào ca lúc {timezone.localtime(att.clock_in):%H:%M %d/%m} đã quá "
                                  f"{MAX_SHIFT_HOURS} giờ nên không ra ca được; báo Chủ quán bổ sung giờ ra đúng.")
        att.clock_out = timezone.now()
        att.save(update_fields=["clock_out", "updated_at"])
        record(Action.UPDATE, actor=user, obj=att, object_type="staff.Attendance",
               after={"ra_ca": timezone.localtime(att.clock_out).isoformat()})
        return {"attendance": att.pk}

    return run_once(operation_key, "clock_out", {}, action, actor=user)



@transaction.atomic
def supplement_clock_out(manager, attendance_id, when, reason):
    """Chủ quán bổ sung giờ ra bị thiếu kèm lý do (AC-78)."""
    from apps.accounts.permissions import Cap, user_can

    if not user_can(manager, Cap.TIMEKEEPING_ADJUST):
        raise ValidationError("Chỉ Chủ quán bổ sung giờ ra ca.")
    att = Attendance.objects.select_for_update().get(pk=attendance_id)
    if att.clock_out is not None:
        raise ValidationError("Lượt chấm công này đã có giờ ra.")
    if not str(reason or "").strip():
        raise ValidationError("Ghi lý do bổ sung giờ ra.")
    if len(reason.strip()) > 255:
        raise ValidationError("Lý do tối đa 255 ký tự.")
    if timezone.is_naive(when):
        when = timezone.make_aware(when)
    if when <= att.clock_in or when > timezone.now():
        raise ValidationError("Giờ ra phải sau giờ vào và không ở tương lai.")
    if (when - att.clock_in).total_seconds() > MAX_SHIFT_HOURS * 3600:
        raise ValidationError(f"Lượt làm dài hơn {MAX_SHIFT_HOURS} giờ (vào ca "
                              f"{timezone.localtime(att.clock_in):%H:%M %d/%m}); kiểm tra lại ngày giờ ra.")
    att.clock_out, att.out_supplemented_by, att.out_reason = when, manager, reason.strip()
    att.save(update_fields=["clock_out", "out_supplemented_by", "out_reason", "updated_at"])
    record(Action.UPDATE, actor=manager, obj=att, object_type="staff.Attendance",
           after={"ra_ca_bo_sung": timezone.localtime(when).isoformat(), "nhan_vien": str(att.user)}, reason=reason)
    return att


def _forgotten_before(now):
    """Lượt mở trước mốc này coi là quên bấm Ra ca (AC-77).

    Ca tối có thể kéo qua nửa đêm, nên lượt của hôm qua chỉ bị coi là quên khi đã tới giờ mở cửa hôm nay;
    trước giờ mở cửa thì chỉ lượt dài hơn MAX_SHIFT_HOURS mới bị coi là quên.
    """
    from apps.core import params

    start_of_today = timezone.make_aware(datetime.combine(timezone.localdate(now), time.min))
    if timezone.localtime(now).hour >= params.get("open_hour"):
        return start_of_today
    return min(start_of_today, now - timedelta(hours=MAX_SHIFT_HOURS))


def is_forgotten(att, now=None):
    return att.clock_out is None and att.clock_in < _forgotten_before(now or timezone.now())


def missing_clock_out(now=None):
    """Lượt vào ca của ngày trước mà chưa ra ca: Thiếu giờ ra (AC-77)."""
    now = now or timezone.now()
    return Attendance.objects.filter(clock_out__isnull=True, clock_in__lt=_forgotten_before(now)).select_related("user")


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
    """Tác vụ định kỳ: ghi nhắc Chủ quán một lần cho mỗi lượt thiếu giờ ra."""
    from apps.audit.models import AuditLog

    reminded = []
    for att in missing_clock_out(now):
        if AuditLog.objects.filter(object_type="staff.Attendance", object_id=str(att.pk), reason=MISSING_OUT).exists():
            continue
        record(Action.STATUS_CHANGE, obj=att, object_type="staff.Attendance", actor_label="hệ thống",
               after={"trang_thai": "Thiếu giờ ra", "nhan_vien": str(att.user)}, reason=MISSING_OUT)
        reminded.append(att.pk)
    return reminded


MISSING_OUT = "Thiếu giờ ra: nhắc Chủ quán bổ sung"
