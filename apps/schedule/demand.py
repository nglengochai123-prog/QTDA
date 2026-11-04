"""Khối việc riêng của từng vị trí để dự báo số người cần theo ca (FR-37, BRU-28).

Mỗi vị trí bận vì một loại việc khác nhau, nên không thể dùng chung "số ly" cho cả ba (Ernst và cộng sự 2004: bước
dự báo nhu cầu phải theo đúng đơn vị việc của từng nhóm nhân viên):

- Pha chế: tải pha chế = số ly × hệ số tải của nhóm món (món đá xay nặng hơn cà phê phin).
- Phục vụ: lượt phục vụ = đơn nhận tại bàn (người tạo đơn là phục vụ) + lượt mang món ra (mỗi đơn, mỗi phút giao).
- Thu ngân: giao dịch = khoản thu (thu trước, thu sau, thu thêm) + khoản hoàn đã trả + đơn nhận tại quầy.

Từ lịch sử 8 tuần, mỗi vị trí có:
1. tỷ lệ việc theo từng giờ của từng thứ trong tuần (đủ ít nhất 3 ngày cùng thứ; không đủ thì gộp ngày thường/cuối
   tuần, rồi gộp cả tuần);
2. số việc trên mỗi ly theo thứ, để đổi dự báo số ly của ngày thành khối việc của vị trí đó;
3. sức làm mỗi người mỗi giờ tính cùng đơn vị việc (phân vị 98 ở các giờ không quá tải, như BRU-28).
"""
from collections import defaultdict
from datetime import datetime, time, timedelta

from django.utils import timezone

from apps.accounts.models import Role

UNITS = {Role.PHA_CHE: ("tải pha chế", "tải"), Role.PHUC_VU: ("lượt phục vụ", "lượt"),
         Role.THU_NGAN: ("giao dịch thu ngân", "giao dịch")}
MIN_DAYS = 3


def _bounds(today, window):
    tz = timezone.get_current_timezone()
    return (timezone.make_aware(datetime.combine(today - timedelta(days=window), time.min), tz),
            timezone.make_aware(datetime.combine(today, time.min), tz))


def _bucket(moment):
    t = timezone.localtime(moment)
    return t.date(), t.hour


def history(today, window=56):
    """{vị trí: {(ngày, giờ): khối việc}}, cùng {(ngày, giờ): số ly} để đổi đơn vị."""
    from apps.orders.models import Order, OrderLine, Payment
    from apps.shifts.models import Refund

    lo, hi = _bounds(today, window)
    work = {r: defaultdict(float) for r in UNITS}
    cups = defaultdict(float)
    for line in (OrderLine.objects.filter(order__created_at__gte=lo, order__created_at__lt=hi)
                 .select_related("order", "item__group")):
        n = line.quantity - line.cancelled_quantity
        if n <= 0:
            continue
        b = _bucket(line.order.created_at)
        cups[b] += n
        work[Role.PHA_CHE][b] += n * float(line.item.group.load_factor)
    for created, role in (Order.objects.filter(created_at__gte=lo, created_at__lt=hi, backup_slip__isnull=True)
                          .values_list("created_at", "created_by__role")):
        if role == Role.THU_NGAN:
            work[Role.THU_NGAN][_bucket(created)] += 1
        else:  # phục vụ, chủ quán nhận đơn tại bàn
            work[Role.PHUC_VU][_bucket(created)] += 1
    trips = set()
    for order_id, served in (OrderLine.objects.filter(served_at__gte=lo, served_at__lt=hi)
                             .values_list("order_id", "served_at")):
        trips.add((order_id, timezone.localtime(served).replace(second=0, microsecond=0)))
    for _order, served in trips:
        work[Role.PHUC_VU][(served.date(), served.hour)] += 1
    for created in Payment.objects.filter(created_at__gte=lo, created_at__lt=hi).values_list("created_at", flat=True):
        work[Role.THU_NGAN][_bucket(created)] += 1
    for paid in (Refund.objects.filter(status=Refund.Status.PAID, paid_at__gte=lo, paid_at__lt=hi)
                 .values_list("paid_at", flat=True)):
        work[Role.THU_NGAN][_bucket(paid)] += 1
    return work, cups


def _group(day):
    return day.weekday() >= 5


def profile(work, cups):
    """Cho mỗi vị trí: tỷ lệ việc theo giờ của từng thứ và số việc mỗi ly theo thứ (có lùi về nhóm ngày khi thiếu)."""
    days = sorted({d for d, _h in cups} | {d for w in work.values() for d, _h in w})
    out = {}
    for role, counts in work.items():
        by_day = defaultdict(lambda: defaultdict(float))
        for (d, h), v in counts.items():
            by_day[d][h] += v
        cup_day = defaultdict(float)
        for (d, _h), v in cups.items():
            cup_day[d] += v

        def pool(select):
            chosen = [d for d in days if select(d) and sum(by_day[d].values()) > 0]
            hours = defaultdict(float)
            for d in chosen:
                for h, v in by_day[d].items():
                    hours[h] += v
            total = sum(hours.values())
            cup_total = sum(cup_day[d] for d in chosen)
            return (len({d for d in chosen}), {h: v / total for h, v in hours.items()} if total else {},
                    total / cup_total if cup_total else None)

        shares, per_cup, basis = {}, {}, {}
        for wd in range(7):
            n, share, ratio = pool(lambda d, wd=wd: d.weekday() == wd)
            label = "cùng thứ"
            if n < MIN_DAYS:
                n, share, ratio = pool(lambda d, g=wd >= 5: _group(d) == g)
                label = "cuối tuần" if wd >= 5 else "ngày thường"
            if n < MIN_DAYS:
                n, share, ratio = pool(lambda d: True)
                label = "cả tuần"
            shares[wd], per_cup[wd], basis[wd] = share, ratio, f"{n} ngày {label}"
        out[role] = {"shares": shares, "per_cup": per_cup, "basis": basis, "label": UNITS[role][0],
                     "unit": UNITS[role][1]}
    return out


def calm_rates(today, roles, work, window=56, q=0.98):
    """Sức làm mỗi người mỗi giờ theo đơn vị việc của vị trí: phân vị q của (việc trong giờ ÷ số người có mặt) ở các
    giờ không quá tải. Bỏ 2% cao nhất phòng chấm công sai. Trả {vị trí: (giá trị, số giờ mẫu)}."""
    from apps.orders.workload import day_frames

    samples = defaultdict(list)
    for k in range(1, window + 1):
        day = today - timedelta(days=k)
        for f in day_frames(day)["frames"]:
            if f["overloaded"]:
                continue
            hour = timezone.localtime(f["start"]).hour
            for r in roles:
                present = f["presence"].get(r, 0)
                if present:
                    samples[r].append(work[r].get((day, hour), 0.0) / present)
    out = {}
    for r in roles:
        v = sorted(samples[r])
        out[r] = (v[min(int(q * len(v)), len(v) - 1)], len(v)) if len(v) >= 5 else (None, len(v))
    return out


def hourly_work(role_profile, day, cups):
    """Khối việc từng giờ của vị trí trong ngày `day` khi dự kiến bán `cups` ly. None khi thiếu dữ liệu."""
    wd = day.weekday()
    share, ratio = role_profile["shares"].get(wd) or {}, role_profile["per_cup"].get(wd)
    if not share or ratio is None:
        return None
    return {h: cups * ratio * s for h, s in share.items()}
