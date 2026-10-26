"""Mô phỏng sự kiện rời rạc một ngày bán để kiểm tra cách gợi ý số người cần (FR-37, BRU-27, BRU-28, BRU-30).

Quán giả lập (hệ thống không biết các tham số này):
- Khách đến theo Poisson không dừng theo giờ; mỗi đơn 1–4 ly, món rút theo tỷ trọng thực đơn.
- Phục vụ: nhận order tại bàn (đơn được gửi pha chế khi nhận xong), mang món khi cả đơn pha xong, dọn bàn sau khi khách
  dùng. Mang món được ưu tiên trước nhận order, nhận order trước dọn bàn.
- Pha chế: hàng chờ chung theo thứ tự gửi, mỗi ly một người pha, thời gian theo nhóm món (phân phối Gamma).
- Thu ngân: thanh toán khi khách về.
- Số người có mặt đổi theo từng giờ theo lịch; người đang làm dở vẫn làm xong rồi mới nghỉ.

Đo như hệ thống đo (orders/workload.py): mỗi khung một giờ có tải theo hệ số nhóm món của Chủ quán, thời gian chờ trung
vị từ lúc gửi pha chế đến lúc mang ra, số ly tồn cuối khung, cờ quá tải; số người có mặt theo vai trò.
Đây là dữ liệu mô phỏng, chỉ để kiểm tra logic; số thật của quán cần đo lại sau khi vận hành.
"""

import heapq
import math
from dataclasses import dataclass, field
from statistics import median

from . import staffing

ROLES = ("pha_che", "phuc_vu", "thu_ngan")

# Tỷ lệ số ly theo giờ mở cửa 6–21 giờ (ngày thường: cao điểm sáng đi làm và tối gia đình; cuối tuần: tối đông hơn).
PROFILE = {
    False: {6: .05, 7: .10, 8: .10, 9: .07, 10: .05, 11: .05, 12: .04, 13: .04, 14: .05, 15: .06, 16: .06, 17: .05,
            18: .06, 19: .09, 20: .09, 21: .04},
    True: {6: .04, 7: .08, 8: .09, 9: .08, 10: .05, 11: .04, 12: .03, 13: .03, 14: .04, 15: .05, 16: .06, 17: .05,
           18: .07, 19: .12, 20: .11, 21: .05},
}
CUPS_PER_DAY = {False: 190, True: 260}
ORDER_SIZES = {1: 0.75, 2: 0.17, 3: 0.05, 4: 0.03}
# Nhóm món: (tỷ trọng ly, phút pha thật trung bình, hệ số tải Chủ quán khai)
GROUPS = {"Cà phê": (0.46, 1.3, 1.0), "Trà": (0.27, 2.0, 1.5), "Cacao và Matcha": (0.10, 2.0, 1.5),
          "Nước ép": (0.06, 2.8, 2.0), "Sinh tố": (0.05, 3.2, 2.5), "Món dừa": (0.06, 2.4, 2.0)}
SERVICE_SHAPE = 4.0  # Gamma k = 4: hệ số biến thiên 0,5
WAITER = {"take": 1.5, "deliver": 0.7, "clear": 1.0}  # phút mỗi đơn
CASHIER_MIN = 1.5
STAY_MIN = (30, 70)  # khách ngồi bao lâu sau khi có món


@dataclass
class DayResult:
    frames: list
    events: list = field(default_factory=list)  # (giờ thập phân, 'gui'|'xong', tải, số pha chế) cho ước lượng sức làm
    take_waits: list = field(default_factory=list)
    pay_waits: list = field(default_factory=list)


def simulate_day(staff, weekend, rnd, cups=None, standard=10.0, backlog_limit=15, shock=1.0):
    """staff: {vai trò: {giờ: số người}}. Trả DayResult với các khung giờ đo như hệ thống."""
    cups = (cups or CUPS_PER_DAY[weekend]) * shock
    mean_size = sum(k * p for k, p in ORDER_SIZES.items())
    events = []  # (thời điểm phút, thứ tự, loại, dữ liệu)
    seq = [0]

    def push(t, kind, data):
        seq[0] += 1
        heapq.heappush(events, (t, seq[0], kind, data))

    orders = []
    for hour, share in PROFILE[weekend].items():
        lam = cups * share / mean_size  # đơn mỗi giờ
        t = hour * 60.0
        while True:
            t += rnd.expovariate(lam / 60) if lam > 0 else 1e9
            if t >= (hour + 1) * 60:
                break
            size = _draw(rnd, ORDER_SIZES)
            items = [_draw(rnd, {g: v[0] for g, v in GROUPS.items()}) for _ in range(size)]
            orders.append({"arrive": t, "items": items})
    for i, o in enumerate(orders):
        push(o["arrive"], "arrive", i)
    for h in range(0, 25):
        push(h * 60.0, "shift", h)

    def cap(role, t):
        return staff.get(role, {}).get(int(t // 60), 0)

    busy = {r: 0 for r in ROLES}
    bar_q = []  # (thời điểm gửi, thứ tự, mã đơn, chỉ số ly)
    waiter_q = []  # (ưu tiên, thời điểm, thứ tự, việc, mã đơn)
    cash_q = []
    cup_rows = []  # mỗi ly: gửi, xong, mang ra, tải
    order_cups = {}
    est_events = []

    def start_work(t):
        while bar_q and busy["pha_che"] < cap("pha_che", t):
            sent, _s, oi, ci = heapq.heappop(bar_q)
            g = orders[oi]["items"][ci]
            dur = rnd.gammavariate(SERVICE_SHAPE, GROUPS[g][1] / SERVICE_SHAPE)
            busy["pha_che"] += 1
            push(t + dur, "cup_done", (oi, ci))
        while waiter_q and busy["phuc_vu"] < cap("phuc_vu", t):
            _p, _t0, _s, job, oi = heapq.heappop(waiter_q)
            busy["phuc_vu"] += 1
            if job == "take":
                orders[oi]["take_start"] = t
            push(t + rnd.gammavariate(4, WAITER[job] / 4), "waiter_done", (job, oi))
        while cash_q and busy["thu_ngan"] < cap("thu_ngan", t):
            t0, _s, oi = heapq.heappop(cash_q)
            busy["thu_ngan"] += 1
            orders[oi]["pay_wait"] = t - t0
            push(t + rnd.gammavariate(4, CASHIER_MIN / 4), "pay_done", oi)

    while events:
        t, _s, kind, data = heapq.heappop(events)
        if kind == "arrive":
            seq[0] += 1
            heapq.heappush(waiter_q, (1, t, seq[0], "take", data))
        elif kind == "waiter_done":
            job, oi = data
            busy["phuc_vu"] -= 1
            o = orders[oi]
            if job == "take":
                o["sent"] = t
                o["take_wait"] = o["take_start"] - o["arrive"]
                order_cups[oi] = len(o["items"])
                for ci in range(len(o["items"])):
                    seq[0] += 1
                    heapq.heappush(bar_q, (t, seq[0], oi, ci))
                    est_events.append((t / 60, "gui", GROUPS[o["items"][ci]][2], cap("pha_che", t)))
                o["done"] = [None] * len(o["items"])
            elif job == "deliver":
                o["served"] = t
                push(t + rnd.uniform(*STAY_MIN), "leave", oi)
        elif kind == "cup_done":
            oi, ci = data
            busy["pha_che"] -= 1
            o = orders[oi]
            o["done"][ci] = t
            est_events.append((t / 60, "xong", GROUPS[o["items"][ci]][2], cap("pha_che", t)))
            order_cups[oi] -= 1
            if order_cups[oi] == 0:
                seq[0] += 1
                heapq.heappush(waiter_q, (0, t, seq[0], "deliver", oi))
        elif kind == "leave":
            seq[0] += 1
            heapq.heappush(cash_q, (t, seq[0], data))
            seq[0] += 1
            heapq.heappush(waiter_q, (2, t, seq[0], "clear", data))
        elif kind == "pay_done":
            busy["thu_ngan"] -= 1
        start_work(t)

    for o in orders:
        if "sent" not in o:
            continue
        for ci, g in enumerate(o["items"]):
            cup_rows.append((o["sent"], o["done"][ci], o.get("served"), GROUPS[g][2]))
    frames = []
    for h in sorted(set(PROFILE[weekend]) | {max(PROFILE[weekend]) + 1}):
        lo, hi = h * 60, (h + 1) * 60
        rows = [r for r in cup_rows if lo <= r[0] < hi]
        waits = [r[2] - r[0] for r in rows if r[2] is not None]
        backlog = sum(1 for r in cup_rows if r[0] < hi and (r[1] is None or r[1] > hi))
        if not rows and not backlog:
            continue
        med = median(waits) if waits else None
        frames.append({"hour": h, "cups": len(rows), "load": sum(r[3] for r in rows), "median_wait": med,
                       "backlog": backlog,
                       "overloaded": bool((med is not None and med > standard) or backlog > backlog_limit),
                       "presence": {r: staff.get(r, {}).get(h, 0) for r in ROLES}})
    return DayResult(frames, est_events, [o["take_wait"] for o in orders if "take_wait" in o],
                     [o["pay_wait"] for o in orders if "pay_wait" in o])


def _draw(rnd, weights):
    x = rnd.random() * sum(weights.values())
    for k, w in weights.items():
        x -= w
        if x <= 0:
            return k
    return k


# ---------------- lịch và cách gợi ý ----------------

SHIFTS_BASIC = [("Ca sáng", 6, 14), ("Ca chiều", 14, 22)]
SHIFTS_PEAK = [("Ca sáng", 6, 14), ("Ca chiều", 14, 22), ("Ca cao điểm sáng", 7, 11), ("Ca cao điểm tối", 18, 22)]


def staff_from_shifts(shifts, counts):
    """{vai trò: [số người mỗi ca]} → {vai trò: {giờ: số người có mặt}} theo quy tắc có mặt nửa khung."""
    out = {}
    for role, xs in counts.items():
        per = {}
        for h in range(0, 24):
            per[h] = sum(x for x, (_n, a, b) in zip(xs, shifts) if staffing.covers((a, b), h))
        out[role] = per
    return out


def as_is_staff(weekend):
    """Lịch cũ cố định, không theo tải: mỗi ca 1 pha chế, 1 phục vụ (cuối tuần 2), 1 thu ngân."""
    return staff_from_shifts(SHIFTS_BASIC, {"pha_che": [1, 1], "phuc_vu": [2, 2] if weekend else [1, 1],
                                            "thu_ngan": [1, 1]})


def history(days, rnd, staff_fn=as_is_staff, start_weekday=0):
    """Chạy nhiều ngày theo một lịch, trả các khung giờ (để học năng suất) và sự kiện quầy pha chế."""
    out = []
    for k in range(days):
        weekend = (start_weekday + k) % 7 >= 5
        shock = math.exp(rnd.gauss(0, 0.10) - 0.005)
        res = simulate_day(staff_fn(weekend), weekend, rnd, shock=shock)
        out.append((weekend, res))
    return out


def old_productivity(hist, minimum_samples=5):
    """Như schedule.services.productivity: trung vị tải mỗi người của các giờ không quá tải."""
    samples = {r: [] for r in ROLES}
    for _w, res in hist:
        for f in res.frames:
            if f["overloaded"]:
                continue
            for r in ROLES:
                if f["presence"][r]:
                    samples[r].append(f["load"] / f["presence"][r])
    return {r: (median(v) if len(v) >= minimum_samples else None) for r, v in samples.items()}


def load_profile(hist):
    """Như schedule.services._hourly_profile: tỷ lệ ly theo giờ (ngày thường, cuối tuần) và tải bình quân mỗi ly."""
    cups = {False: {}, True: {}}
    load = n = 0.0
    for weekend, res in hist:
        for f in res.frames:
            cups[weekend][f["hour"]] = cups[weekend].get(f["hour"], 0) + f["cups"]
            load += f["load"]
            n += f["cups"]
    shares = {w: {h: v / sum(c.values()) for h, v in c.items()} for w, c in cups.items() if sum(c.values())}
    return shares, (load / n if n else 1.0)


def hourly_load(cups, shares, load_per_cup):
    return {h: cups * s * load_per_cup for h, s in shares.items()}


def need_old(loads, prod, minimum=1):
    """BRU-28 như đang cài: làm tròn lên tải ÷ năng suất, không thấp hơn tối thiểu (theo từng giờ)."""
    return {h: max(minimum, math.ceil(v / prod)) if prod else minimum for h, v in loads.items()}


def need_queue(loads, rate, wait_min, target, scv, minimum=1):
    """Số người mỗi giờ theo Erlang C (Allen–Cunneen): P(chờ trong hàng ≤ wait_min phút) ≥ target."""
    return staffing.hourly_needs(loads, rate, wait_min, target, scv, minimum, sorted(loads))


def estimate_rates(hist, q=0.98):
    """Sức làm như schedule.services.rates khi Chủ quán chưa đặt: pha chế đo lúc mọi người bận, vị trí khác lấy giờ
    đông nhất đã làm kịp (phân vị q của tải mỗi người ở giờ không quá tải)."""
    done = busy = 0.0
    for _w, res in hist:
        rate, b = staffing.saturated_rate(sorted(res.events, key=lambda e: (e[0], e[1] == "gui")))
        if rate:
            done += rate * b
            busy += b
    calm = {r: [] for r in ROLES}
    for _w, res in hist:
        for f in res.frames:
            if not f["overloaded"]:
                for r in ROLES:
                    if f["presence"][r]:
                        calm[r].append(f["load"] / f["presence"][r])
    out = {r: sorted(v)[min(int(q * len(v)), len(v) - 1)] if v else None for r, v in calm.items()}
    if busy:
        out["pha_che"] = done / busy
    return out


def plan_staff(shifts, loads, rates, wait_min, target, scv, minimum=1, hours=range(6, 22)):
    """Lịch theo cách mới: Erlang C từng giờ rồi phủ ca (như schedule.services.suggest_day)."""
    spans = [(a, b) for _n, a, b in shifts]
    loads = {h: loads.get(h, 0) for h in hours}
    counts = {r: staffing.staff_shifts(loads, rates[r], wait_min, target, scv, minimum, list(hours), spans)[0]
              for r in ROLES}
    return staff_from_shifts(shifts, counts)


def plan_old(shifts, loads, productivity, minimum=1):
    """Lịch theo cách trước 26/10: làm tròn lên tải ÷ năng suất trung vị, giờ cao nhất của từng ca."""
    spans = [(a, b) for _n, a, b in shifts]
    return staff_from_shifts(shifts, {r: staffing.peak_per_shift(spans, need_old(loads, productivity[r], minimum))
                                      for r in ROLES})


def evaluate(staff_fn, days, rnd, start_weekday=0, standard=10.0, scale=1.0, busy_cups=20):
    """Chạy thử một lịch: tỷ lệ khung đạt chuẩn chờ (BO-03), giờ công theo vai trò, chờ nhận order, chờ thanh toán."""
    frames, take, pay = [], [], []
    hours = {r: 0 for r in ROLES}
    for k in range(days):
        weekend = (start_weekday + k) % 7 >= 5
        staff = staff_fn(weekend)
        shock = math.exp(rnd.gauss(0, 0.10) - 0.005)
        res = simulate_day(staff, weekend, rnd, cups=CUPS_PER_DAY[weekend] * scale, shock=shock, standard=standard)
        frames += [f for f in res.frames if f["cups"] > 0]
        take += res.take_waits
        pay += res.pay_waits
        for r in ROLES:
            hours[r] += sum(staff[r].values())
    ok = sum(1 for f in frames if f["median_wait"] is not None and f["median_wait"] <= standard)
    peak = [f for f in frames if f["cups"] >= busy_cups]
    peak_ok = sum(1 for f in peak if f["median_wait"] is not None and f["median_wait"] <= standard)
    take.sort()
    pay.sort()
    return {"frames": len(frames), "ok_share": ok / len(frames) if frames else None,
            "peak_frames": len(peak), "peak_ok_share": peak_ok / len(peak) if peak else None,
            "overloaded_share": sum(f["overloaded"] for f in frames) / len(frames) if frames else None,
            "hours_per_day": {r: v / days for r, v in hours.items()}, "staff_hours_per_day": sum(hours.values()) / days,
            "take_wait_p90": take[int(0.9 * (len(take) - 1))] if take else None,
            "pay_wait_p90": pay[int(0.9 * (len(pay) - 1))] if pay else None}
