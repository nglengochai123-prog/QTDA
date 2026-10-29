"""Lịch làm tuần cho Chủ quán; đăng ký ca và lịch của tôi cho nhân viên (FR-38, FR-39)."""

from datetime import date, datetime, time, timedelta

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from apps.accounts.models import User
from apps.accounts.permissions import Cap, capability_required
from apps.audit.models import Action
from apps.audit.services import record
from apps.core import errors
from apps.core.dates import parse_day

from . import services as sv
from .models import Assignment, WorkShift

def _week(request):
    value = request.POST.get("tuan") if request.method == "POST" else request.GET.get("tuan")
    day = parse_day(value)
    return sv.week_start(day) if day else sv.next_week()


def _back(week, shift=None, tab=None):
    url = f"{reverse('schedule:board')}?tuan={week.isoformat()}"
    if shift:
        url += f"&mo={shift}"
    if tab:
        url += f"&xem={tab}"
    return redirect(url)


def _time(value):
    value = (value or "").strip()
    if value in ("24:00", "24:0"):
        return time(0, 0)  # hết ngày: ca kết thúc lúc nửa đêm
    try:
        return datetime.strptime(value, "%H:%M").time()
    except ValueError:
        raise ValidationError("Nhập giờ bắt đầu và giờ kết thúc của ca, ví dụ 06:30.") from None


def _needs_from(post):
    values = {}
    for role in sv.ROLES:
        raw = post.get(f"need_{role}", "").strip()
        if raw == "":
            continue
        if not raw.isdigit():
            raise ValidationError("Số người cần phải là số nguyên từ 0 trở lên.")
        values[role] = int(raw)
    return values


@capability_required(Cap.SCHEDULE_MANAGE)
@require_http_methods(["GET", "POST"])
def board(request):
    week = _week(request)
    if request.method == "POST":
        p, user = request.POST, request.user
        action = p.get("action")
        reopen = p.get("shift") if action in ("set_needs", "assign", "unassign") else None
        try:
            if action == "add_shift":
                from apps.core.models import Store

                days = p.getlist("days") or [p.get("date")]
                days = [d for d in days if d]
                if not days:
                    raise ValidationError("Chọn ít nhất một ngày.")
                name = p.get("name", "").strip() or "Ca"
                if len(name) > 40:
                    raise ValidationError("Tên ca tối đa 40 ký tự.")
                start, end = _time(p.get("start")), _time(p.get("end"))
                if end <= start and end != time(0, 0):
                    raise ValidationError("Giờ kết thúc phải sau giờ bắt đầu (ca kết thúc lúc nửa đêm thì ghi 00:00).")
                needs = _needs_from(p)
                made, skipped = [], 0
                for d in days:
                    day = date.fromisoformat(d)
                    s, created = WorkShift.objects.get_or_create(
                        date=day, name=name, defaults={"start": start, "end": end,
                                                       "store": user.store or Store.get_default()})
                    if created:
                        made.append(s)
                        record(Action.CREATE, request=request, obj=s, object_type="schedule.WorkShift",
                               after={"ca": str(s)})
                    else:
                        skipped += 1
                if needs and made:
                    sv.set_needs(user, made, needs)
                messages.success(request, f"Đã thêm {len(made)} ca {name}." + (
                    f" {skipped} ngày đã có ca cùng tên nên bỏ qua." if skipped else ""))
            elif action == "delete_shift":
                s = get_object_or_404(WorkShift, pk=p.get("shift"))
                if s.assignments.filter(removed_at__isnull=True).exists():
                    reopen = s.pk
                    raise ValidationError("Ca đã có người được xếp; bỏ người ra trước khi xóa ca.")
                registrants = sorted({r.user_id for r in s.registrations.filter(cancelled_at__isnull=True)})
                record(Action.DELETE, request=request, obj=s, object_type="schedule.WorkShift", before={"ca": str(s)},
                       after={"nguoi_da_dang_ky": len(registrants)})
                label = f"{s.name} {s.date:%d/%m} {s.start:%H:%M}–{s.end:%H:%M}"
                upcoming = s.date >= timezone.localdate()
                s.delete()
                if registrants and upcoming:
                    from apps.core.push import notify_later

                    # Đăng ký bị xóa theo ca: báo người đã đăng ký để họ chọn ca khác, không chờ một ca không còn.
                    notify_later(registrants, f"Ca {label} đã bị bỏ khỏi lịch",
                                 "Đăng ký của bạn cho ca này không còn; chọn ca khác nếu cần.", "/lich/dang-ky/")
                messages.success(request, "Đã xóa ca." + (f" Đã báo {len(registrants)} người đã đăng ký ca này."
                                                         if registrants and upcoming else ""))
            elif action == "set_needs":
                s = get_object_or_404(WorkShift, pk=p.get("shift"))
                targets = [s]
                if p.get("same_name"):
                    targets = list(WorkShift.objects.filter(name=s.name, date__gte=week,
                                                            date__lt=week + timedelta(days=7)))
                sv.set_needs(user, targets, _needs_from(p), p.get("reason", ""))
                messages.success(request, f"Đã lưu số người cần cho {s.name} "
                                          + ("cả tuần." if len(targets) > 1 else f"{s.date:%d/%m}."))
            elif action == "suggest_needs":
                sv.apply_suggested_needs(week, user)
                messages.success(request, "Đã điền số người cần theo gợi ý; ô bạn đã sửa có lý do được giữ.")
            elif action == "auto_assign":
                made = sv.auto_assign(user, week)
                messages.success(request, (f"Đã xếp thêm {made} lượt theo đăng ký." if made else
                                           "Không có lượt mới theo đăng ký.") + " Ô bạn xếp tay được giữ nguyên.")
            elif action == "assign":
                s = get_object_or_404(WorkShift, pk=p.get("shift"))
                person = get_object_or_404(User, pk=p.get("user"))
                sv.assign(user, s, person, p.get("role"))
                messages.success(request, f"Đã xếp {person} vào {s.name} {s.date:%d/%m}.")
            elif action == "unassign":
                a = get_object_or_404(Assignment, pk=p.get("assignment"), removed_at__isnull=True)
                reopen = a.shift_id
                sv.unassign(user, a, p.get("reason", ""))
                messages.success(request, f"Đã bỏ {a.user} khỏi {a.shift.name} {a.shift.date:%d/%m}.")
            elif action == "copy_prev":
                made = sv.copy_week(user, week - timedelta(days=7), week)
                messages.success(request, f"Đã chép {made} ca từ tuần trước.")
            elif action == "publish":
                if not p.get("confirm"):
                    raise ValidationError("Đánh dấu xác nhận trước khi công bố.")
                sv.publish(user, week)
                messages.success(request, "Đã công bố lịch; mỗi nhân viên nhận lịch của mình trên điện thoại.")
        except (ValidationError, ValueError) as error:
            for m in errors.messages_of(error):
                messages.error(request, m)
        return _back(week, reopen, p.get("xem"))
    from . import board as view_model

    context = view_model.build(week)
    context["tab"] = request.GET.get("xem") if request.GET.get("xem") in ("nguoi", "gio") else "ca"
    context["open_shift"] = request.GET.get("mo", "")
    context["roles"] = [(r, sv.ROLE_LABEL[r]) for r in sv.ROLES]
    return render(request, "schedule/board.html", context)


@capability_required(Cap.SHIFT_REGISTER)
@require_http_methods(["GET", "POST"])
def register(request):
    week = _week(request)
    if request.method == "POST":
        choices = {}
        for key, value in request.POST.items():
            if key.startswith("ca_") and key[3:].isdigit():
                choices[int(key[3:])] = value
        gone = len(set(choices) - set(WorkShift.objects.filter(pk__in=choices).values_list("pk", flat=True)))
        try:
            changed = sv.register(request.user, choices)
            messages.success(request, "Đã gửi đăng ký." if changed else "Không có thay đổi.")
        except ValidationError as error:
            for m in error.messages:
                messages.error(request, m)
        if gone:
            messages.warning(request, f"{gone} ca vừa bị Chủ quán xóa nên lựa chọn ở ca đó không được lưu. "
                                      "Xem lại danh sách ca bên dưới.")
        return redirect(f"{reverse('schedule:register')}?tuan={week.isoformat()}")
    from .pages import register_page

    return render(request, "schedule/register.html", register_page(request.user, week))


@capability_required(Cap.SHIFT_REGISTER)
def mine(request):
    from .pages import my_page

    return render(request, "schedule/mine.html", my_page(request.user))
