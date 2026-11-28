"""Ca quỹ lấy từ lịch làm tuần đã công bố, để Chủ quán không phải nhập lại giờ ca ở Quản trị.

Quy tắc:
- Chỉ ca trong lịch có vị trí thu ngân (có người được xếp, hoặc số người cần lớn hơn 0) mới thành ca quỹ: ca chỉ có
  pha chế hay phục vụ không giữ tiền.
- Công bố lịch (cả công bố lại) tạo ca quỹ còn thiếu và cập nhật ca quỹ chưa bắt đầu theo giờ, tên và thu ngân mới
  trong lịch. Ca quỹ đã bắt đầu thì giữ nguyên, vì tiền và đơn đã gắn vào đó.
- Người phụ trách ca (người duyệt yêu cầu, chấp nhận chênh lệch) là Chủ quán đã công bố lịch. Người được ủy quyền thu
  tiền theo món thực nhận là thu ngân được xếp vào ca.
- Thu ngân mở được đúng một ca trong lịch đã công bố khi tới giờ mà ca quỹ còn thiếu, không sửa được giờ hay người
  phụ trách; Chủ quán được báo, nhật ký ghi người mở. Ca tạo tay ở Quản trị vẫn dùng như cũ.
"""

from datetime import datetime, timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import ProtectedError
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.audit.models import Action
from apps.audit.services import record

from .models import Shift

OPEN_EARLY_MINUTES = 30  # thu ngân mở ca sớm tối đa ngần này phút trước giờ bắt đầu trong lịch


def window(work_shift):
    """(lúc bắt đầu, lúc kết thúc) có múi giờ của ca trong lịch; ca kết thúc lúc 0 giờ là 0 giờ hôm sau."""
    start = timezone.make_aware(datetime.combine(work_shift.date, work_shift.start))
    return start, timezone.make_aware(work_shift.end_datetime)


def cashier_of(work_shift):
    a = (work_shift.assignments.filter(removed_at__isnull=True, role=Role.THU_NGAN).select_related("user")
         .order_by("created_at").first())
    return a.user if a else None


def holds_cash(work_shift):
    """Ca trong lịch có vị trí thu ngân thì là ca giữ quỹ."""
    return (work_shift.assignments.filter(removed_at__isnull=True, role=Role.THU_NGAN).exists()
            or work_shift.needs.filter(role=Role.THU_NGAN, needed__gt=0).exists())


def _linked(work_shift):
    return Shift.objects.filter(work_shift=work_shift).first()


def _drop(shift, now):
    """Bỏ ca quỹ chưa bắt đầu và chưa có gì gắn vào; có đơn, tiền hay phiếu thì giữ lại."""
    if shift.status != Shift.Status.OPEN or shift.starts_at <= now:
        return False
    try:
        with transaction.atomic():
            shift.delete()
    except ProtectedError:
        return False
    return True


@transaction.atomic
def sync_week(owner, week, now=None):
    """Tạo, cập nhật hoặc bỏ ca quỹ theo các ca trong lịch của tuần `week` (thứ Hai). Trả số ca theo từng việc."""
    from apps.schedule.models import WorkShift

    now = now or timezone.now()
    done = {"created": 0, "updated": 0, "removed": 0}
    shifts = WorkShift.objects.filter(date__gte=week, date__lt=week + timedelta(days=7)).order_by("date", "start")
    for ws in shifts:
        cash = _linked(ws)
        if not holds_cash(ws):
            if cash is not None and _drop(cash, now):
                done["removed"] += 1
            continue
        start, end = window(ws)
        cashier = cashier_of(ws)
        if cash is not None:
            if cash.status == Shift.Status.OPEN and cash.starts_at > now:
                new = {"name": ws.name, "starts_at": start, "ends_at": end, "payment_authorizer": cashier}
                changed = {k: v for k, v in new.items() if getattr(cash, k) != v}
                if changed:
                    for k, v in changed.items():
                        setattr(cash, k, v)
                    cash.save(update_fields=[*changed, "updated_at"])
                    done["updated"] += 1
            continue
        if end <= now:
            continue  # ca đã qua: không tạo ngược ca quỹ cho quá khứ
        manual = Shift.objects.filter(work_shift__isnull=True, name=ws.name, starts_at=start).first()
        if manual is not None:  # Chủ quán đã tạo tay đúng ca này: gắn lại, không tạo trùng
            manual.work_shift = ws
            manual.save(update_fields=["work_shift", "updated_at"])
            continue
        Shift.objects.create(store=ws.store, name=ws.name, starts_at=start, ends_at=end, approver=owner,
                             payment_authorizer=cashier, work_shift=ws)
        done["created"] += 1
    if any(done.values()):
        record(Action.UPDATE, actor=owner, object_type="shifts.Shift",
               after={"tuan": str(week), "ca_quy_tao": done["created"], "ca_quy_cap_nhat": done["updated"],
                      "ca_quy_bo": done["removed"]}, reason="Theo lịch làm tuần đã công bố")
    return done


def drop_for(work_shift, now=None):
    """Ca trong lịch bị xóa: bỏ ca quỹ đi kèm nếu chưa bắt đầu và chưa có gì gắn vào."""
    cash = _linked(work_shift)
    return cash is not None and _drop(cash, now or timezone.now())


def openable(now=None):
    """Ca trong lịch đã công bố mà thu ngân mở được lúc này: tới giờ (sớm tối đa OPEN_EARLY_MINUTES phút), chưa hết giờ,
    giữ quỹ, chưa có ca quỹ, và không có ca quỹ nào đang trong khung giờ."""
    from apps.schedule.models import WorkShift
    from apps.schedule.services import is_published, week_start

    now = now or timezone.now()
    if Shift.objects.current(now) is not None:
        return []
    today = timezone.localdate(now)
    out = []
    for ws in WorkShift.objects.filter(date__in=[today - timedelta(days=1), today], cash_shift__isnull=True):
        start, end = window(ws)
        if start - timedelta(minutes=OPEN_EARLY_MINUTES) <= now < end and is_published(week_start(ws.date)) \
                and holds_cash(ws):
            out.append(ws)
    return sorted(out, key=lambda w: window(w)[0])


def _approver(work_shift):
    """Chủ quán chịu trách nhiệm ca: người đã công bố lịch tuần đó, nếu còn là Chủ quán; không thì Chủ quán đang làm."""
    from apps.schedule.models import WeekPublish
    from apps.schedule.services import week_start

    pub = WeekPublish.objects.filter(week_start=week_start(work_shift.date)).select_related("published_by").first()
    if pub is not None and pub.published_by.is_active and pub.published_by.is_owner:
        return pub.published_by
    owners = [u for u in User.objects.filter(is_active=True).order_by("pk") if u.is_owner]
    return owners[0] if owners else None


@transaction.atomic
def open_from_schedule(user, work_shift_id, now=None):
    """Thu ngân (hoặc Chủ quán) mở ca quỹ đúng theo một ca trong lịch đã công bố. Kiểm tra lại mọi điều kiện ở đây,
    không dựa vào việc nút có hiện hay không."""
    from apps.accounts.permissions import Cap, user_can
    from apps.schedule.models import WorkShift

    if not user_can(user, Cap.CASH_FUND):
        raise ValidationError("Bạn không có quyền mở ca.")
    now = now or timezone.now()
    ws = WorkShift.objects.select_for_update().filter(pk=work_shift_id).first()
    if ws is None:
        raise ValidationError("Không tìm thấy ca trong lịch; tải lại trang.")
    existing = _linked(ws)
    if existing is not None:
        return existing, False  # bấm hai lần hoặc hai người cùng bấm: dùng ca đã mở
    if ws not in openable(now):
        start, _ = window(ws)
        if Shift.objects.current(now) is not None:
            raise ValidationError("Đang có ca quỹ trong khung giờ này; không mở thêm ca.")
        if now < start - timedelta(minutes=OPEN_EARLY_MINUTES):
            raise ValidationError(f"Chưa tới giờ: mở được từ {timezone.localtime(start - timedelta(minutes=OPEN_EARLY_MINUTES)):%H:%M}.")
        raise ValidationError("Ca này không mở được: lịch chưa công bố, ca đã hết giờ hoặc ca không có vị trí thu ngân.")
    approver = _approver(ws)
    if approver is None:
        raise ValidationError("Quán chưa có tài khoản Chủ quán đang làm để phụ trách ca; báo Chủ quán.")
    start, end = window(ws)
    cashier = cashier_of(ws)
    if cashier is None and user_can(user, Cap.PAYMENT):
        cashier = user
    shift = Shift.objects.create(store=ws.store, name=ws.name, starts_at=start, ends_at=end, approver=approver,
                                 payment_authorizer=cashier, work_shift=ws)
    record(Action.CREATE, actor=user, obj=shift, object_type="shifts.Shift",
           after={"ca": str(shift), "gio": f"{timezone.localtime(start):%H:%M}–{timezone.localtime(end):%H:%M}",
                  "phu_trach": str(approver)}, reason="Mở theo lịch làm tuần đã công bố")
    if approver.pk != user.pk:
        from apps.core.push import notify_later

        notify_later([approver.pk], f"{user} đã mở {shift.name.lower()} theo lịch",
                     f"{shift} {timezone.localtime(start):%H:%M}–{timezone.localtime(end):%H:%M}; bạn phụ trách ca này.",
                     "/ca/tinh-trang/")
    return shift, True


@transaction.atomic
def open_now(user, now=None):
    """Mở ca theo giờ hiện tại khi quán không có ca nào giữ quỹ lúc này và lịch cũng không có ca để mở (ví dụ ca
    trước quên kết, đã quá giờ; hoặc chưa lập lịch). Ca chạy từ bây giờ tới giờ đóng cửa (ít nhất 2 giờ). Ca cũ chưa
    kết vẫn giữ nguyên để kết và điều chỉnh sau. Chủ quán được báo."""
    from apps.accounts.permissions import Cap, user_can
    from apps.core import params
    from apps.core.models import Store

    if not user_can(user, Cap.CASH_FUND):
        raise ValidationError("Bạn không có quyền mở ca.")
    now = now or timezone.now()
    list(Store.objects.select_for_update().all())  # hai người cùng bấm: lần lượt, người sau thấy ca vừa mở
    current = Shift.objects.operating(now)
    if current is not None:
        return current, False
    if openable(now):
        raise ValidationError("Lịch đã công bố có ca cho giờ này; dùng nút Mở ca theo lịch.")
    owners = [u for u in User.objects.filter(is_active=True).order_by("pk") if u.is_owner]
    approver = user if user.is_owner else (owners[0] if owners else None)
    if approver is None:
        raise ValidationError("Quán chưa có tài khoản Chủ quán đang làm để phụ trách ca; báo Chủ quán.")
    start = timezone.localtime(now).replace(second=0, microsecond=0)
    close = start.replace(hour=0, minute=0) + timedelta(hours=params.get("close_hour"))
    end = close if close - start >= timedelta(hours=2) else start + timedelta(hours=2)
    shift = Shift.objects.create(store=user.store or Store.get_default(), name=f"Ca {start:%H:%M}", starts_at=start,
                                 ends_at=end, approver=approver,
                                 payment_authorizer=user if user_can(user, Cap.PAYMENT) else None)
    record(Action.CREATE, actor=user, obj=shift, object_type="shifts.Shift",
           after={"ca": str(shift), "gio": f"{start:%H:%M}–{timezone.localtime(end):%H:%M}", "phu_trach": str(approver),
                  "ca_cu_chua_ket": [str(s) for s in Shift.objects.stale(now)]},
           reason="Mở ca theo giờ hiện tại (không có ca nào giữ quỹ lúc này)")
    if approver.pk != user.pk:
        from apps.core.push import notify_later

        notify_later([approver.pk], f"{user} đã mở ca theo giờ hiện tại",
                     f"{shift} {start:%H:%M}–{timezone.localtime(end):%H:%M}. Ca cũ chưa kết (nếu có) kết sau.",
                     "/ca/tinh-trang/")
    return shift, True
