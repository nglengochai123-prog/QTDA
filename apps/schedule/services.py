"""Đăng ký ca, gợi ý số người cần, gợi ý xếp lịch, thiếu dư và công bố (FR-38, FR-39, BRU-28 đến BRU-30).

Quy tắc:
- Nhân viên chỉ đăng ký vị trí mình đảm nhận được và trước hạn (mặc định 12 giờ trưa thứ Năm của tuần trước, AC-85).
  Sau hạn chỉ Chủ quán xếp, có nhật ký.
- Không xếp một người vào hai ca trùng giờ (AC-87).
- Thiếu, dư tính riêng từng vị trí của mỗi ca (AC-86): đủ tổng người vẫn có thể thiếu một vị trí.
- Gợi ý số người cần (BRU-28): tải dự kiến từng giờ = số ly dự báo của ngày × tỷ lệ bán theo giờ trong lịch sử ×
  hệ số tải bình quân mỗi ly. Số người từng giờ theo mô hình hàng đợi Erlang C thay cho làm tròn lên tải ÷ năng suất,
  vì người làm tới 100% công suất thì hàng chờ dài không giới hạn (xem staffing.py và docs/KET_QUA_MO_PHONG.md);
  không thấp hơn mức tối thiểu khi quán mở. Số người từng giờ được chia vào các ca của ngày bằng bài toán phủ, nên ca
  chồng giờ không bị tính hai lần. Sức làm do Chủ quán đặt; để 0 thì pha chế được đo lúc mọi người đều bận, vị trí
  khác lấy ước lượng thận trọng. Đây là gợi ý (BRU-37); Chủ quán sửa số áp dụng, khác gợi ý thì ghi lý do.
- Gợi ý xếp lịch: ô khan hiếm (ít người đăng ký so với nhu cầu) được xếp trước; trong ô, ưu tiên người có ít giờ
  đã xếp trong tuần, rồi người đăng ký sớm. Ô Chủ quán đã xếp tay được giữ nguyên.
"""

from collections import defaultdict
from datetime import datetime, time, timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Role
from apps.audit.models import Action
from apps.audit.services import record
from apps.core import params

from . import staffing
from .models import Assignment, Registration, RoleNeed, WeekPublish, WorkShift

ROLES = [Role.PHA_CHE, Role.PHUC_VU, Role.THU_NGAN]
ROLE_LABEL = dict(Role.choices)


def week_start(day):
    return day - timedelta(days=day.weekday())


def next_week(today=None):
    return week_start(today or timezone.localdate()) + timedelta(days=7)


def deadline_for(week):
    """Hạn đăng ký cho tuần bắt đầu `week`: thứ và giờ theo tham số, trong tuần liền trước."""
    weekday = params.get("schedule_deadline_weekday") - 2  # 2 là thứ Hai → 0
    day = week - timedelta(days=7) + timedelta(days=max(0, min(weekday, 6)))
    return timezone.make_aware(datetime.combine(day, time(params.get("schedule_deadline_hour"))))


def week_shifts(week):
    return (WorkShift.objects.filter(date__gte=week, date__lt=week + timedelta(days=7))
            .prefetch_related("needs", "registrations", "assignments").order_by("date", "start"))


def user_roles(user):
    from apps.staff.models import Employee

    emp = Employee.objects.filter(user=user).first()
    roles = set(emp.roles if emp and emp.is_working else [])
    if not emp and user.role in ROLES:
        roles.add(user.role)
    return [r for r in ROLES if r in roles]


# ---------------- đăng ký (FR-38) ----------------

@transaction.atomic
def register(user, choices, now=None):
    """choices: {shift_id: role hoặc ''}. Thay toàn bộ đăng ký của người này trong tuần của các ca được gửi."""
    now = now or timezone.now()
    shifts = {s.pk: s for s in WorkShift.objects.filter(pk__in=choices)}
    if not shifts:
        raise ValidationError("Chưa chọn ca nào.")
    weeks = {week_start(s.date) for s in shifts.values()}
    for w in weeks:
        if now > deadline_for(w):
            raise ValidationError(f"Đã quá hạn đăng ký ({deadline_for(w):%H:%M %d/%m}). Liên hệ Chủ quán để được xếp ca.")
    allowed = set(user_roles(user))
    for shift_id, role in choices.items():
        if role and role not in allowed:
            raise ValidationError(f"Bạn không đảm nhận được vị trí {ROLE_LABEL.get(role, role)}.")
    changed = []
    for shift_id, role in choices.items():
        shift = shifts[shift_id]
        current = Registration.objects.filter(shift=shift, user=user, cancelled_at__isnull=True).first()
        if current and current.role == role:
            continue
        if current:
            current.cancelled_at = now
            current.save(update_fields=["cancelled_at", "updated_at"])
        if role:
            Registration.objects.create(shift=shift, user=user, role=role)
        changed.append((str(shift), ROLE_LABEL.get(role, "bỏ đăng ký")))
    if changed:
        record(Action.UPDATE, actor=user, object_type="schedule.Registration",
               after={"dang_ky": [f"{s}: {r}" for s, r in changed]}, reason="Nhân viên đăng ký ca")
    return changed


# ---------------- gợi ý số người cần (BRU-28) ----------------

SERVICE_SCV = 0.25  # c²s của thời gian pha mỗi ly: giả định lệch quanh trung bình khoảng ±50% (Gamma k = 4)
MIN_BUSY_HOURS = 3  # số giờ-người bận tối thiểu để tin sức làm đo được
FORGOTTEN_MINUTES = 60  # dòng món từ gửi tới pha xong lâu hơn mức này coi như quên bấm "Xong", không dùng để đo


def _hourly_profile(today, window=56):
    """Tỷ lệ số ly theo giờ trong ngày cho ngày thường và cuối tuần, và hệ số tải bình quân mỗi ly."""
    from apps.orders.models import OrderLine

    tz = timezone.get_current_timezone()
    lo = timezone.make_aware(datetime.combine(today - timedelta(days=window), time.min), tz)
    hi = timezone.make_aware(datetime.combine(today, time.min), tz)
    cups = {False: defaultdict(float), True: defaultdict(float)}
    load = cups_total = 0.0
    for line in OrderLine.objects.filter(order__created_at__gte=lo, order__created_at__lt=hi).select_related(
            "order", "item__group"):
        n = line.quantity - line.cancelled_quantity
        if n <= 0:
            continue
        t = timezone.localtime(line.order.created_at)
        cups[t.weekday() >= 5][t.hour] += n
        load += n * float(line.item.group.load_factor)
        cups_total += n
    profile = {}
    for weekend, by_hour in cups.items():
        total = sum(by_hour.values())
        profile[weekend] = {h: v / total for h, v in by_hour.items()} if total else {}
    return profile, (load / cups_total if cups_total else 1.0)


def _window(today, window):
    tz = timezone.get_current_timezone()
    return (timezone.make_aware(datetime.combine(today - timedelta(days=window), time.min), tz),
            timezone.make_aware(datetime.combine(today, time.min), tz))


def _bar_events(today, window=56):
    """Sự kiện quầy pha chế cho staffing.saturated_rate: gửi pha chế và pha xong từng dòng món, kèm số pha chế có mặt.

    Bỏ đơn nhập bù (không có giờ gửi thật), dòng chưa pha xong, dòng pha xong trước khi gửi (dữ liệu lỗi) và dòng quá
    FORGOTTEN_MINUTES phút (quên bấm), vì một dòng treo làm cả quầy trông như đang bận."""
    from apps.orders.models import OrderLine
    from apps.staff.models import Attendance

    lo, hi = _window(today, window)
    shifts = [(a.clock_in, a.clock_out) for a in Attendance.objects.filter(
        role=Role.PHA_CHE, clock_in__lt=hi, clock_out__gt=lo)]

    def present(moment):
        return sum(1 for a, b in shifts if a <= moment < b)

    raw = []
    for line in (OrderLine.objects.filter(order__created_at__gte=lo, order__created_at__lt=hi, done_at__isnull=False,
                                          order__backup_slip__isnull=True).select_related("order", "item__group")):
        n = line.quantity - line.cancelled_quantity
        took = (line.done_at - line.order.created_at).total_seconds() / 60
        if n <= 0 or not 0 <= took <= FORGOTTEN_MINUTES:
            continue
        load = n * float(line.item.group.load_factor)
        raw.append((line.order.created_at, 1, "gui", load, n))
        raw.append((line.done_at, 0, "xong", load, n))
    raw.sort(key=lambda e: (e[0], e[1]))
    events = []
    for moment, _order, kind, load, n in raw:
        events.append(((moment - lo).total_seconds() / 3600, kind, load, present(moment), n))
    return events


def _calm_hour_quantile(today, roles, window=56, q=0.98):
    """Phân vị q của tải mỗi người trong các giờ không quá tải (BRU-28: không học từ giờ quá tải)."""
    from apps.orders.workload import day_frames

    samples = defaultdict(list)
    for k in range(1, window + 1):
        for f in day_frames(today - timedelta(days=k))["frames"]:
            if f["overloaded"]:
                continue
            for r in roles:
                present = f["presence"].get(r, 0)
                if present:
                    samples[r].append(float(f["load"]) / present)
    out = {}
    for r in roles:
        v = sorted(samples[r])
        out[r] = (v[min(int(q * len(v)), len(v) - 1)], len(v)) if len(v) >= 5 else (None, len(v))
    return out


def rates(today, window=56):
    """Sức làm mỗi người mỗi giờ khi bận liên tục, theo vị trí, cùng đơn vị với tải.

    Thứ tự: số đặt trong file tham số (apps/core/params.py); với pha chế, đo thông lượng lúc mọi pha chế đều bận (cần ít nhất 3 giờ-người bận);
    còn lại lấy giờ đông nhất mà vị trí đó vẫn làm kịp: phân vị 98 của tải mỗi người ở giờ không quá tải (bỏ 2% cao
    nhất phòng chấm công sai). Người chưa từng phải làm hết sức thì số này thấp hơn sức làm thật, nên gợi ý dư người
    (an toàn) cho tới khi đo được và đặt số trong file."""
    out, auto = {}, []
    for r in ROLES:
        value = params.get(f"schedule_productivity_{r}")
        if value:
            out[r] = {"value": float(value), "source": "Đặt trong file tham số", "kind": "owner"}
        else:
            auto.append(r)
    if Role.PHA_CHE in auto:
        rate, busy = staffing.saturated_rate(_bar_events(today, window))
        if rate and busy >= MIN_BUSY_HOURS:
            out[Role.PHA_CHE] = {"value": round(rate, 1), "kind": "measured",
                                 "source": f"Đo lúc mọi pha chế đều bận ({busy:.0f} giờ-người trong {window // 7} tuần)"}
            auto.remove(Role.PHA_CHE)
    if auto:
        for r, (value, n) in _calm_hour_quantile(today, auto, window).items():
            out[r] = ({"value": round(value, 1), "kind": "conservative",
                       "source": f"Giờ đông nhất đã làm kịp trong {n} giờ không quá tải; thường thấp hơn sức làm "
                                 "thật nên gợi ý dư người"}
                      if value else None)
    return out


def arrival_scv(today, window=56):
    """Độ biến động của dòng ly theo Allen–Cunneen: (c²a + c²s) / 2, với c²a = E[B²]/E[B] của số ly mỗi đơn."""
    from django.db.models import F, Sum

    from apps.orders.models import OrderLine

    lo, hi = _window(today, window)
    sizes = defaultdict(int)
    for row in (OrderLine.objects.filter(order__created_at__gte=lo, order__created_at__lt=hi)
                .values("order_id").annotate(n=Sum(F("quantity") - F("cancelled_quantity")))):
        if row["n"] > 0:
            sizes[row["n"]] += 1
    ca2 = staffing.batch_scv(sizes) if sizes else 1.0
    return round((ca2 + SERVICE_SCV) / 2, 3)


def staffing_inputs(today=None, window=56):
    """Những gì gợi ý số người cần đọc từ dữ liệu, tính một lần cho cả tuần."""
    today = today or timezone.localdate()
    return {"today": today, "profile": _hourly_profile(today, window), "rates": rates(today, window),
            "scv": arrival_scv(today, window)}


def _daily_cups(day, today):
    """Số ly dự kiến của ngày: từ lần phát hành dự báo gần nhất; ngoài chân trời thì bình quân 4 ngày cùng thứ."""
    from apps.forecast.services import latest_release

    rel = latest_release()
    if rel:
        idx = (day - rel.first_day).days
        total, ok = 0.0, False
        for s in rel.series.all():
            if 0 <= idx < len(s.daily):
                total += s.daily[idx]["mean"]
                ok = True
        if ok:
            return total, "Dự báo phát hành " + timezone.localtime(rel.issued_at).strftime("%d/%m")
    from apps.forecast.services import cups_by_day

    days = [day - timedelta(days=7 * k) for k in range(1, 5) if day - timedelta(days=7 * k) < today]
    if not days:
        return None, ""
    by = cups_by_day(min(days), max(days))
    totals = [sum(series.get(d, 0) for series in by.values()) for d in days]
    return sum(totals) / len(totals), "Bình quân 4 ngày cùng thứ gần nhất"


def _span(shift):
    """(giờ bắt đầu, giờ kết thúc) dạng số thập phân; ca kết thúc lúc 0 giờ tính là 24."""
    a = shift.start.hour + shift.start.minute / 60
    b = shift.end.hour + shift.end.minute / 60
    return a, (b if b > a else 24.0)


def suggest_day(day, shifts, inputs=None):
    """{ca.pk: {vị trí: (số người gợi ý, căn cứ)}} cho các ca của một ngày.

    1. Tải từng giờ mở cửa = số ly dự kiến của ngày × tỷ lệ bán theo giờ × hệ số tải bình quân mỗi ly.
    2. Số người từng giờ theo Erlang C (staffing.hourly_needs): nhỏ nhất để ít nhất `schedule_service_percent`% việc
       chờ không quá `schedule_wait_target_minutes` phút; không dưới mức tối thiểu khi quán mở.
    3. Chia vào các ca của ngày bằng bài toán phủ (staffing.cover_shifts): đủ người mọi giờ, ít giờ công nhất."""
    inputs = inputs or staffing_inputs()
    (shares, load_per_cup), rate_by, scv = inputs["profile"], inputs["rates"], inputs["scv"]
    cups, source = _daily_cups(day, inputs["today"])
    share = shares.get(day.weekday() >= 5, {})
    minimum = params.get("schedule_min_per_role")
    wait_min = params.get("schedule_wait_target_minutes")
    target = params.get("schedule_service_percent") / 100
    hours = list(range(params.get("open_hour"), params.get("close_hour")))
    spans = [_span(s) for s in shifts]
    out = {s.pk: {} for s in shifts}
    loads = {h: (cups or 0) * share.get(h, 0) * load_per_cup for h in hours}
    for r in ROLES:
        rate = rate_by.get(r)
        if cups is None or not share or rate is None or rate["value"] <= 0:
            for s in shifts:
                out[s.pk][r] = (None, {"missing": "Chưa đủ dữ liệu bán theo giờ hoặc sức làm; nhập số người cần."})
            continue
        x, need, uncovered = staffing.staff_shifts(loads, rate["value"], wait_min, target, scv, minimum, hours, spans)
        for s, span, n in zip(shifts, spans, x):
            mine = [h for h in hours if staffing.covers(span, h)]
            out[s.pk][r] = (n, {
                "cups": round(cups, 1), "cups_source": source, "rate": rate["value"], "rate_source": rate["source"],
                "rate_kind": rate["kind"], "wait_minutes": wait_min, "service_percent": round(target * 100),
                "scv": scv, "minimum": minimum,
                "hours": [[h, round(loads[h], 1), need[h]] for h in mine],
                "peak_load": round(max((loads[h] for h in mine), default=0), 1),
                "uncovered": uncovered})
    return out


def suggest_needs(shift, today=None, inputs=None):
    """{vị trí: (số người gợi ý, căn cứ)} cho một ca; tính cùng các ca khác của ngày vì ca chồng giờ chia nhau tải."""
    inputs = inputs or staffing_inputs(today)
    shifts = list(WorkShift.objects.filter(date=shift.date).order_by("start", "name"))
    return suggest_day(shift.date, shifts, inputs)[shift.pk]


@transaction.atomic
def apply_suggested_needs(week, user):
    """Ghi số gợi ý cho mọi ô của tuần; ô Chủ quán đã đặt khác gợi ý (có lý do) giữ số của Chủ quán."""
    inputs = staffing_inputs()
    by_day = defaultdict(list)
    for shift in week_shifts(week):
        by_day[shift.date].append(shift)
    changed = 0
    for day, shifts in by_day.items():
        for shift_id, per_role in suggest_day(day, shifts, inputs).items():
            for role, (n, basis) in per_role.items():
                need, _ = RoleNeed.objects.get_or_create(shift_id=shift_id, role=role, defaults={"needed": n or 0})
                need.suggested, need.basis = n, basis
                if n is not None and not need.reason:
                    need.needed = n
                need.save()
                changed += 1
    record(Action.UPDATE, actor=user, object_type="schedule.RoleNeed", after={"tuan": str(week), "so_o": changed},
           reason="Áp dụng gợi ý số người cần")
    return changed


def basis_by_day(rows):
    """Căn cứ gợi ý gom theo ngày cho màn lịch tuần: số ly, sức làm từng vị trí, số người cần từng giờ, giờ không có ca."""
    days = {}
    for row in rows:
        s = row["shift"]
        for cell in row["cells"]:
            b = cell["need"].basis if cell["need"] else {}
            if not b or "hours" not in b:
                continue
            day = days.setdefault(s.date, {"date": s.date, "cups": b["cups"], "cups_source": b["cups_source"],
                                           "uncovered": b["uncovered"], "roles": {}})
            role = day["roles"].setdefault(cell["role"], {"label": cell["label"], "rate": b["rate"],
                                                          "rate_source": b["rate_source"], "rate_kind": b["rate_kind"],
                                                          "need": {}})
            for h, _load, n in b["hours"]:
                role["need"][h] = n
    out = []
    for day in sorted(days.values(), key=lambda d: d["date"]):
        hours = sorted({h for r in day["roles"].values() for h in r["need"]})
        roles = []
        for code in ROLES:
            r = day["roles"].get(code)
            if r:
                r["cells"] = [r["need"].get(h) for h in hours]
                r["peak"] = max(r["need"].values(), default=0)
                roles.append(r)
        out.append({**day, "hours": hours, "roles": roles})
    return out


def set_need(user, shift, role, needed, reason=""):
    need, _ = RoleNeed.objects.get_or_create(shift=shift, role=role, defaults={"needed": needed})
    if need.suggested is not None and needed != need.suggested and not reason.strip():
        raise ValidationError(f"{ROLE_LABEL[role]} {shift}: khác số gợi ý {need.suggested}, ghi lý do (BRU-28).")
    before = need.needed
    need.needed, need.reason = needed, reason.strip()[:255]
    need.save()
    if before != needed:
        record(Action.UPDATE, actor=user, obj=need, object_type="schedule.RoleNeed", before={"can": before},
               after={"can": needed, "ca": str(shift), "vi_tri": ROLE_LABEL[role]}, reason=need.reason)
    return need


# ---------------- xếp lịch (FR-39) ----------------

def _active_assignments(week):
    return list(Assignment.objects.filter(shift__date__gte=week, shift__date__lt=week + timedelta(days=7),
                                          removed_at__isnull=True).select_related("shift", "user"))


def conflicts(user, shift, exclude_shift=None):
    """Ca khác trùng giờ mà người này đã được xếp (AC-87)."""
    return [a.shift for a in Assignment.objects.filter(user=user, removed_at__isnull=True, shift__date=shift.date)
            .exclude(shift=exclude_shift or shift).select_related("shift") if a.shift.overlaps(shift)]


@transaction.atomic
def assign(owner, shift, user, role, source=Assignment.Source.OWNER):
    if role not in user_roles(user):
        raise ValidationError(f"{user} không đảm nhận được vị trí {ROLE_LABEL.get(role, role)}.")
    clash = conflicts(user, shift)
    if clash:
        raise ValidationError(f"{user} đã có {clash[0]} trùng giờ.")
    current = Assignment.objects.filter(shift=shift, user=user, removed_at__isnull=True).first()
    if current:
        if current.role == role:
            return current
        current.removed_at, current.remove_reason = timezone.now(), "Đổi vị trí"
        current.save(update_fields=["removed_at", "remove_reason", "updated_at"])
    a = Assignment.objects.create(shift=shift, user=user, role=role, source=source, assigned_by=owner)
    late = timezone.now() > deadline_for(week_start(shift.date))
    if source == Assignment.Source.OWNER:
        record(Action.CREATE, actor=owner, obj=a, object_type="schedule.Assignment",
               after={"ca": str(shift), "nhan_vien": str(user), "vi_tri": ROLE_LABEL[role]},
               reason="Chủ quán xếp sau hạn đăng ký" if late else "Chủ quán xếp")
    return a


@transaction.atomic
def unassign(owner, assignment, reason=""):
    assignment.removed_at, assignment.remove_reason = timezone.now(), reason.strip()[:255] or "Chủ quán bỏ ra"
    assignment.save(update_fields=["removed_at", "remove_reason", "updated_at"])
    record(Action.DELETE, actor=owner, obj=assignment, object_type="schedule.Assignment",
           before={"ca": str(assignment.shift), "nhan_vien": str(assignment.user)}, reason=assignment.remove_reason)


@transaction.atomic
def auto_assign(owner, week):
    """Gợi ý xếp lịch theo đăng ký; giữ nguyên các ô Chủ quán đã xếp tay."""
    Assignment.objects.filter(shift__date__gte=week, shift__date__lt=week + timedelta(days=7),
                              source=Assignment.Source.SUGGESTED, removed_at__isnull=True).update(
        removed_at=timezone.now(), remove_reason="Xếp lại theo gợi ý")
    shifts = list(week_shifts(week))  # đọc sau khi bỏ các lượt gợi ý cũ để đếm đúng số đã xếp
    taken = defaultdict(list)  # user_id -> [shift]
    hours = defaultdict(float)
    for a in _active_assignments(week):
        taken[a.user_id].append(a.shift)
        hours[a.user_id] += a.shift.hours
    cells = []
    for s in shifts:
        needs = {n.role: n.needed for n in s.needs.all()}
        regs = [r for r in s.registrations.all() if r.cancelled_at is None]
        for role, need in needs.items():
            have = sum(1 for a in s.assignments.all() if a.removed_at is None and a.role == role)
            pool = [r for r in regs if r.role == role]
            if need > have:
                cells.append((len(pool) / max(need - have, 1), s, role, need - have, pool))
    cells.sort(key=lambda c: (c[0], c[1].date, c[1].start))
    made = 0
    for _, s, role, missing, pool in cells:
        pool = sorted(pool, key=lambda r: (hours[r.user_id], r.created_at))
        for reg in pool:
            if missing <= 0:
                break
            if any(sh.pk == s.pk or sh.overlaps(s) for sh in taken[reg.user_id]):
                continue
            if role not in user_roles(reg.user):
                continue
            Assignment.objects.create(shift=s, user=reg.user, role=role, source=Assignment.Source.SUGGESTED,
                                      assigned_by=owner)
            taken[reg.user_id].append(s)
            hours[reg.user_id] += s.hours
            missing -= 1
            made += 1
    record(Action.UPDATE, actor=owner, object_type="schedule.Assignment", after={"tuan": str(week), "xep": made},
           reason="Gợi ý xếp lịch theo đăng ký")
    return made


def coverage(week):
    """Từng ô (ca, vị trí): cần, đã xếp, đã đăng ký, thiếu, dư (AC-86); kèm tổng hợp chỗ thiếu."""
    rows, gaps = [], []
    for s in week_shifts(week):
        needs = {n.role: n for n in s.needs.all()}
        active = [a for a in s.assignments.all() if a.removed_at is None]
        regs = [r for r in s.registrations.all() if r.cancelled_at is None]
        cells = []
        for role in ROLES:
            need = needs.get(role)
            n = need.needed if need else 0
            assigned = [a for a in active if a.role == role]
            registered = [r for r in regs if r.role == role]
            cell = {"role": role, "label": ROLE_LABEL[role], "need": need, "needed": n, "assigned": assigned,
                    "registered": registered, "unassigned_regs": [r for r in registered
                                                                   if r.user_id not in {a.user_id for a in active}],
                    "short": max(n - len(assigned), 0), "surplus": max(len(assigned) - n, 0),
                    "reg_short": max(n - len(registered), 0)}
            if cell["short"]:
                gaps.append(f"{s} thiếu {cell['short']} {ROLE_LABEL[role].lower()}")
            cells.append(cell)
        rows.append({"shift": s, "cells": cells})
    return rows, gaps


def replacements(shift, role):
    """Người thay thế: có kỹ năng vị trí, đang làm, chưa có ca trùng giờ; người đã đăng ký ca này trước (AC-87)."""
    from apps.staff.models import Employee

    registered = {r.user_id for r in shift.registrations.filter(cancelled_at__isnull=True)}
    assigned = set(shift.assignments.filter(removed_at__isnull=True).values_list("user_id", flat=True))
    week = week_start(shift.date)
    hours = defaultdict(float)
    for a in _active_assignments(week):
        hours[a.user_id] += a.shift.hours
    out = []
    for emp in Employee.objects.filter(status="dang_lam").select_related("user"):
        if role not in (emp.roles or []) or emp.user_id in assigned or conflicts(emp.user, shift):
            continue
        out.append({"user": emp.user, "registered": emp.user_id in registered, "hours": hours[emp.user_id]})
    out.sort(key=lambda x: (not x["registered"], x["hours"], str(x["user"])))
    return out


@transaction.atomic
def publish(owner, week):
    rows, gaps = coverage(week)
    pub = WeekPublish.objects.create(week_start=week, published_by=owner, gaps=gaps)
    record(Action.STATUS_CHANGE, actor=owner, obj=pub, object_type="schedule.WeekPublish",
           after={"tuan": str(week), "con_thieu": len(gaps)})
    from apps.core.push import notify_later

    per_user = defaultdict(list)
    for a in _active_assignments(week):
        per_user[a.user_id].append(a)
    for user_id, items in per_user.items():
        items.sort(key=lambda a: (a.shift.date, a.shift.start))
        body = "; ".join(f"{a.shift.date:%d/%m} {a.shift.start:%H:%M}–{a.shift.end:%H:%M} {ROLE_LABEL[a.role]}"
                         for a in items[:6]) + ("…" if len(items) > 6 else "")
        notify_later([user_id], f"Lịch làm tuần {week:%d/%m}", body, "/lich/cua-toi/")
    return pub


def is_published(week):
    return WeekPublish.objects.filter(week_start=week).exists()


@transaction.atomic
def copy_week(owner, source, target):
    """Chép các ca và số người cần của tuần nguồn sang tuần đích (ca đã có cùng tên trong ngày thì bỏ qua)."""
    from apps.core.models import Store

    made = 0
    for s in week_shifts(source):
        day = target + timedelta(days=(s.date - source).days)
        new, created = WorkShift.objects.get_or_create(
            date=day, name=s.name, defaults={"start": s.start, "end": s.end, "store": s.store or Store.get_default()})
        if created:
            for n in s.needs.all():
                RoleNeed.objects.create(shift=new, role=n.role, needed=n.needed)
            made += 1
    record(Action.CREATE, actor=owner, object_type="schedule.WorkShift", after={"chep_tu": str(source), "sang": str(target),
                                                                                  "so_ca": made})
    return made


def my_schedule(user, today=None):
    today = today or timezone.localdate()
    published = set(WeekPublish.objects.values_list("week_start", flat=True))
    return [a for a in Assignment.objects.filter(user=user, removed_at__isnull=True, shift__date__gte=today)
            .select_related("shift").order_by("shift__date", "shift__start") if week_start(a.shift.date) in published]
