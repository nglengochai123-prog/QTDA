"""Mô phỏng khép kín kế hoạch mua nguyên liệu trên một quán giả lập (thiết kế mua nguyên liệu mục 12.3, 12.4).

Mục đích: kiểm tra quyết định mua chứ không chỉ sai số dự báo. Mỗi ngày giả lập:
1. Sáng: hàng đặt trước đó về (có thể trễ một ngày).
2. Trong ngày: khách gọi món theo nhu cầu thật của "thế giới"; ly nào thiếu nguyên liệu thì không bán được, mỗi nguyên
   liệu thiếu tính tối đa một trường hợp mỗi ngày (BRU-26). Dùng lô cũ trước (FIFO).
3. Tối: bỏ lô hết hạn; hệ thống chỉ thấy số ly đã bán theo món, tiêu hao đã bán và cờ hết hàng (như usage.series_for,
   hierarchy.from_usage), chạy đúng các hàm dự báo và chính sách đang dùng (hierarchy.build, methods.forecast_series,
   policy.compute); Chủ quán giả lập làm theo đề xuất và duyệt mọi đề xuất đổi cách dự báo.

Thế giới giả lập có những thứ hệ thống không biết trước: thứ trong tuần, mùa hè, Tết đóng cửa, ngày lễ, mức bán trôi
dần, cú sốc thời tiết chung cả ngày, phân tán lớn hơn Poisson, ước tính tuần của Chủ quán lệch so với thật.
Đây là dữ liệu mô phỏng: kết quả xác minh logic quyết định, không thay cho kiểm chứng trên dữ liệu thật của quán.

Hàm thuần, không đọc hay ghi cơ sở dữ liệu.
"""

import math
import random
from dataclasses import dataclass, field
from datetime import date, timedelta

from . import hierarchy, methods, policy

# ---------------- thế giới ----------------

GROUP_SHARE = {"Cà phê": 0.46, "Trà": 0.27, "Cacao và Matcha": 0.10, "Nước ép": 0.06, "Sinh tố": 0.05,
               "Món dừa": 0.06}
WEEKDAY = [0.93, 0.90, 0.93, 0.96, 1.02, 1.20, 1.26]  # thứ Hai … Chủ nhật; cuối tuần đông hơn ~25% (khảo sát)
SUMMER_GROUPS = {"Trà": 0.22, "Nước ép": 0.30, "Sinh tố": 0.30, "Món dừa": 0.15, "Cà phê": 0.04,
                 "Cacao và Matcha": -0.08}


def tet_day(year):
    """Mùng 1 Tết âm lịch (bảng tra cho các năm mô phỏng)."""
    return {2026: date(2026, 2, 17), 2027: date(2027, 2, 6), 2028: date(2028, 1, 26)}[year]


def calendar_factor(d):
    """(hệ số, đóng cửa) của một ngày: lễ, Tết; mùa vụ tính riêng theo nhóm món."""
    tet = tet_day(d.year) if d.month <= 3 else None
    if tet:
        k = (d - tet).days
        if 0 <= k <= 2:
            return 0.0, True  # Mùng 1–3 nghỉ
        if -7 <= k <= -1:
            return 1.12 + 0.04 * (7 + k) / 7, False  # tuần cuối năm âm lịch đông dần
        if 3 <= k <= 8:
            return 1.25, False  # khách về quê, đi chơi Tết
    holidays = {(1, 1): 1.25, (4, 30): 1.35, (5, 1): 1.30, (9, 2): 1.35, (12, 24): 1.20, (3, 8): 1.10,
                (10, 20): 1.10}
    return holidays.get((d.month, d.day), 1.0), False


def summer_factor(group, d):
    """Mùa nóng tháng 4–8 ở Đà Nẵng: đồ uống lạnh, trái cây tăng; lên xuống dần theo hình sin."""
    amp = SUMMER_GROUPS.get(group, 0.0)
    phase = (d.timetuple().tm_yday - 105) / 365 * 2 * math.pi  # đỉnh khoảng giữa tháng 7
    return 1 + amp * max(0.0, math.sin(phase + 0.5)) ** 1.5


def menu_usage():
    """{món: (nhóm, {nguyên liệu: lượng mỗi ly})} từ công thức thật; món có tùy chọn lấy trung bình các tùy chọn."""
    from apps.catalog import thuc_don_lam as data

    out = {}
    for group, name, _text, lines, variants, _notes in data.ITEMS:
        base = {k: float(v) for k, v in data.expand(lines).items()}
        for _g, options in variants.items():
            n = len(options)
            for _o, extra in options.items():
                for k, v in data.expand(extra).items():
                    base[k] = base.get(k, 0.0) + float(v) / n
        out[name] = (group, base)
    return out


@dataclass
class World:
    """Nhu cầu thật theo món và ngày; hệ thống không đọc được các tham số này."""

    start: date
    days: int
    seed: int = 1
    cups_per_day: float = 185.0  # ~135 đơn ngày thường × 1,35 ly (khảo sát 130–160 đơn/ngày)
    drift_sd: float = 0.004  # trôi mức bán mỗi ngày (log)
    shock_sd: float = 0.10  # cú sốc chung cả ngày: mưa, sự kiện (log)
    dispersion: float = 25.0  # Gamma(k) nhân vào Poisson: k nhỏ thì phân tán lớn
    shift_day: int = 200  # ngày có thay đổi lâu dài (quán đối diện khai trương …)
    shift_size: float = -0.12
    items: dict = field(default_factory=dict)

    def __post_init__(self):
        rnd = random.Random(self.seed)
        usage = menu_usage()
        by_group = {}
        for name, (group, _) in usage.items():
            by_group.setdefault(group, []).append(name)
        weights = {}
        for group, names in by_group.items():
            names = sorted(names)
            rnd.shuffle(names)
            raw = [1 / (r + 1) ** 0.9 for r in range(len(names))]  # vài món bán chạy, đuôi dài
            for name, w in zip(names, raw):
                weights[name] = GROUP_SHARE[group] * w / sum(raw)
        self.items = {name: {"group": usage[name][0], "usage": usage[name][1], "share": weights[name]}
                      for name in usage}
        level, self.level = 0.0, []
        for j in range(self.days):
            level += rnd.gauss(0, self.drift_sd) - 0.02 * level  # trôi có hồi về, không chạy mất
            self.level.append(level + (self.shift_size if j >= self.shift_day else 0.0))
        self.shock = [rnd.gauss(0, self.shock_sd) for _ in range(self.days)]
        self._rnd = random.Random(self.seed * 7919 + 1)

    def date(self, j):
        return self.start + timedelta(days=j)

    def expected(self, j, name):
        d = self.date(j)
        cal, closed = calendar_factor(d)
        if closed:
            return 0.0
        it = self.items[name]
        return (self.cups_per_day * it["share"] * WEEKDAY[d.weekday()] / (sum(WEEKDAY) / 7) * cal
                * summer_factor(it["group"], d) * math.exp(self.level[j]))

    def closed(self, j):
        return calendar_factor(self.date(j))[1]

    def demand(self, j):
        """Số ly khách gọi trong ngày j theo món (ngẫu nhiên: sốc chung × Gamma × Poisson)."""
        rnd = self._rnd
        common = math.exp(self.shock[j] - self.shock_sd ** 2 / 2)
        out = {}
        for name in self.items:
            lam = self.expected(j, name) * common
            if lam <= 0:
                continue
            lam *= rnd.gammavariate(self.dispersion, 1 / self.dispersion)
            n = _poisson(rnd, lam)
            if n:
                out[name] = n
        return out

    def expected_usage(self, j, ing):
        return sum(self.expected(j, n) * it["usage"].get(ing, 0.0) for n, it in self.items.items())


def _poisson(rnd, lam):
    if lam > 50:
        return max(0, int(round(rnd.gauss(lam, math.sqrt(lam)))))
    k, p, target = 0, 1.0, math.exp(-lam)
    while True:
        p *= rnd.random()
        if p <= target:
            return k
        k += 1


# ---------------- nguyên liệu và nhà cung cấp ----------------

@dataclass
class Spec:
    """Nguyên liệu trong mô phỏng: quy cách, hạn dùng, thời gian giao, độ tin cậy giao."""

    name: str
    unit: str
    pack: float
    shelf: int = None  # ngày kể từ khi nhận
    lead: int = 1  # ngày giao danh nghĩa ℓ
    late_p: float = 0.08  # xác suất về trễ thêm một ngày
    critical: bool = False
    moq: int = 1
    capacity: float = None


# Quy cách và thời gian giao giả định theo cách mua thường gặp của quán cà phê nhỏ (chợ, đại lý). Chủ quán cần thay
# bằng số thật ở Quản trị › Nguyên vật liệu.
SPECS = [
    Spec("Cà phê bột", "g", 1000, shelf=90, lead=2, critical=True),
    Spec("Sữa đặc", "ml", 1284, shelf=180, lead=1, critical=True),
    Spec("Sữa tươi", "ml", 1000, shelf=7, lead=1, critical=True),
    Spec("Kem béo Rich", "ml", 907, shelf=30, lead=2, critical=True),
    Spec("Đường cát", "g", 1000, shelf=365, lead=1),
    Spec("Đường gói", "goi", 100, shelf=365, lead=2),
    Spec("Nước cốt dừa", "ml", 400, shelf=365, lead=2),
    Spec("Bột matcha", "g", 500, shelf=180, lead=3),
    Spec("Bột cacao", "g", 500, shelf=365, lead=3),
    Spec("Chanh", "qua", 10, shelf=7, lead=1),
    Spec("Tắc", "qua", 50, shelf=7, lead=1, critical=True),
    Spec("Cam", "qua", 10, shelf=10, lead=1),
    Spec("Xoài", "qua", 4, shelf=5, lead=1),
    Spec("Bơ", "qua", 4, shelf=4, lead=1),
    Spec("Mứt đào", "ml", 1000, shelf=90, lead=3),
    Spec("Siro đào", "ml", 750, shelf=365, lead=3),
    Spec("Đào ngâm (lát)", "cai", 30, shelf=365, lead=3),
    Spec("Kem dừa (viên)", "cai", 50, shelf=30, lead=2),
]


@dataclass
class Rules:
    """Tham số chính sách: mặc định như Kiểm soát › Tham số của hệ thống."""

    csl_critical: int = 95
    csl_normal: int = 95
    csl_long_life: int = 98  # mức tối thiểu cho hàng để lâu (nhóm B); 0 để tắt
    group_a_shelf: int = 14
    a_review: int = 1
    a_target: int = 2
    b_review: int = 7
    b_weekday: int = 6  # Chủ nhật
    horizon: int = 35
    candidates: tuple = ("LN", "WMA", "HW")  # cách tính trực tiếp trên chuỗi nguyên liệu được đánh giá
    hierarchy: bool = True  # thêm cách phân cấp: tổng số ly × tỷ trọng món × định mức
    stockout_target: float = None  # thử nghiệm: số lần thiếu cho phép mỗi tháng chia đều cho từng nguyên liệu
    csl_by_group: dict = None  # thử nghiệm: {"A": %, "B": %} thay cho CSL theo trọng yếu
    aging: bool = True  # cho bộ tính biết các lô đang có và hạn dùng (EWA)
    label: str = "Hệ thống hiện tại"


# Cách tính trước 26/10/2026: CSL 95% trọng yếu, 90% còn lại cho mọi nhóm, không theo dõi hạn của lô.
BEFORE_2610 = Rules(csl_normal=90, csl_long_life=0, aging=False, label="Trước 26/10/2026")
# Chỉ dự báo trực tiếp trên chuỗi nguyên liệu, không có cách phân cấp: để thấy phần đóng góp của dự báo theo món.
NO_HIERARCHY = Rules(hierarchy=False, label="Không dự báo phân cấp")


def owner_estimate(world, ing, rnd, start_j=0, weeks=4):
    """Ước tính tuần của Chủ quán: thường lệ lệch ±20% so với thật, khoảng thấp–cao ±35%."""
    weekly = sum(world.expected_usage(start_j + k, ing) for k in range(7 * weeks)) / weeks
    typical = weekly * math.exp(rnd.gauss(0, 0.2))
    return (round(typical * 0.65, 1), round(typical, 1), round(typical * 1.35, 1))


# ---------------- vận hành ----------------

@dataclass
class Lot:
    qty: float
    expires: date  # hết hạn sau ngày này


@dataclass
class Order:
    qty: float
    expected: date
    actual: date
    midday: bool = False  # về giữa ngày (nửa nhu cầu đã qua) thay vì trước giờ mở cửa


class Store:
    def __init__(self, world, specs, rules, owner="system", seed=1):
        self.w, self.specs, self.rules, self.owner = world, {s.name: s for s in specs}, rules, owner
        self.rnd = random.Random(seed * 104729 + 3)
        est_rnd = random.Random(seed * 31 + 5)
        self.estimate = {s.name: owner_estimate(world, s.name, est_rnd) for s in specs}
        self.lots = {s.name: [] for s in specs}
        self.orders = {s.name: [] for s in specs}
        self.series = {s.name: [] for s in specs}
        self.item_series = {name: [] for name in world.items}
        self.total_series = []
        self.choice = {}  # cách dự báo đang dùng theo chuỗi (Chủ quán giả lập duyệt mọi đề xuất)
        self.hw = {}  # tham số Holt-Winters chọn lại mỗi tuần để mô phỏng chạy nhanh
        self.h, self.h_items = None, []
        self.last_fc = {}
        self.k = {s.name: _new_kpi() for s in specs}
        self.months = {}
        self.lost_cups = 0
        self.cups = 0
        for s in specs:  # tồn ban đầu: khoảng 3 ngày (nhóm dễ hỏng) hoặc 10 ngày theo ước tính của Chủ quán
            days = 3 if self.group(s) == "A" else 10
            self._receive(s.name, self.estimate[s.name][1] / 7 * days, world.start)

    # ----- tham số -----
    def group(self, s):
        return "A" if s.shelf and s.shelf <= self.rules.group_a_shelf else "B"

    def csl(self, s):
        r = self.rules
        if r.csl_by_group:
            return r.csl_by_group[self.group(s)]
        if r.stockout_target is None:
            csl = r.csl_critical if s.critical else r.csl_normal
            return max(csl, r.csl_long_life) if self.group(s) == "B" else csl
        return csl_for_target(r.stockout_target, len(self.specs), self.cycles_per_month(s))

    def cycles_per_month(self, s):
        g = self.group(s)
        r = self.rules
        return 30 / max(r.a_target if g == "A" else r.b_review, 1)

    # ----- ngày -----
    def run(self, verbose=False):
        for j in range(self.w.days):
            self.day(j)
        return self.report()

    def day(self, j):
        d = self.w.date(j)
        for name in self.specs:
            for o in [o for o in self.orders[name] if o.actual == d and not o.midday]:
                self._receive(name, o.qty, d)
                self.orders[name].remove(o)
        closed = self.w.closed(j)
        demand = {} if closed else self.w.demand(j)
        sold_usage, out_today, blocked_cups, sold_cups = self._serve(j, d, demand)
        for name in self.specs:
            for o in [o for o in self.orders[name] if o.actual == d and o.midday]:
                self.orders[name].remove(o)  # lô giữa ngày đã nhận trong _serve
        month = d.strftime("%Y-%m")
        m = self.months.setdefault(month, {"stockouts": 0, "lost_cups": 0, "cups": 0, "days": 0})
        m["days"] += 1
        m["stockouts"] += len(out_today)
        for name, s in self.specs.items():
            k = self.k[name]
            k["demand"] += sum(n * self.w.items[i]["usage"].get(name, 0.0) for i, n in demand.items())
            k["used"] += sold_usage.get(name, 0.0)
            k["stockout_days"] += name in out_today
            for lot in [x for x in self.lots[name] if x.expires <= d]:
                k["expired"] += lot.qty
                self.lots[name].remove(lot)
            k["on_hand_sum"] += self.on_hand(name)
            k["days"] += 1
            if closed:
                status = "dong_cua"
            elif name in out_today or self._indirect(name, blocked_cups, demand):
                status = "bo_qua"
            else:
                status = "ok"
            self.series[name].append((d, sold_usage.get(name, 0.0) if status == "ok" else None, status))
        m["lost_cups"] += sum(blocked_cups.values())
        m["cups"] += sum(demand.values())
        for name in self.w.items:
            st = "dong_cua" if closed else "bo_qua" if name in blocked_cups else "ok"
            self.item_series[name].append((d, float(sold_cups.get(name, 0)) if st == "ok" else None, st))
        lost = sum(blocked_cups.values()) / max(sum(demand.values()), 1)
        st = "dong_cua" if closed else "bo_qua" if lost >= 0.2 else "ok"
        self.total_series.append((d, float(sum(sold_cups.values())) if st == "ok" else None, st))
        if j < self.w.days - 1 and self.owner == "system":
            self._hierarchy(d)
        if j < self.w.days - 1:
            for name, s in self.specs.items():
                self._plan(s, d)

    def _serve(self, j, d, demand):
        """Bán từng ly theo thứ tự ngẫu nhiên; lô về giữa ngày nhận khi qua nửa số ly."""
        cups = [i for i, n in demand.items() for _ in range(n)]
        self.rnd.shuffle(cups)
        used, out, blocked, sold = {}, set(), {}, {}
        half = len(cups) // 2
        for idx, item in enumerate(cups):
            if idx == half:
                for name in self.specs:
                    for o in self.orders[name]:
                        if o.actual == d and o.midday:
                            self._receive(name, o.qty, d)
            need = {k: v for k, v in self.w.items[item]["usage"].items() if k in self.specs}
            short = [k for k, v in need.items() if self.on_hand(k) + 1e-9 < v]
            self.cups += 1
            if short:
                out.update(short)
                blocked[item] = blocked.get(item, 0) + 1
                self.lost_cups += 1
                continue
            for k, v in need.items():
                self._take(k, v)
                used[k] = used.get(k, 0.0) + v
            sold[item] = sold.get(item, 0) + 1
        if half == 0:
            for name in self.specs:
                for o in self.orders[name]:
                    if o.actual == d and o.midday:
                        self._receive(name, o.qty, d)
        return used, out, blocked, sold

    def _indirect(self, name, blocked, demand):
        """Bị chặn gián tiếp: món bị ngừng vì thiếu nguyên liệu khác chiếm từ 20% tiêu hao dự kiến (usage._indirect)."""
        if not blocked:
            return False
        lost = sum(n * self.w.items[i]["usage"].get(name, 0.0) for i, n in blocked.items())
        total = sum(n * self.w.items[i]["usage"].get(name, 0.0) for i, n in demand.items())
        return total > 0 and lost / total >= 0.2

    def on_hand(self, name):
        return sum(x.qty for x in self.lots[name])

    def _take(self, name, qty):
        lots = self.lots[name]
        lots.sort(key=lambda x: x.expires)
        while qty > 1e-9 and lots:
            take = min(qty, lots[0].qty)
            lots[0].qty -= take
            qty -= take
            if lots[0].qty <= 1e-9:
                lots.pop(0)

    def _receive(self, name, qty, d):
        s = self.specs[name]
        expires = d + timedelta(days=s.shelf - 1) if s.shelf else date.max  # ngày cuối còn dùng được
        self.lots[name].append(Lot(qty, expires))
        self.k[name]["received"] += qty

    # ----- dự báo -----
    def _hw_params(self, key, series, today):
        """Tham số Holt-Winters của một chuỗi, chọn lại mỗi 7 ngày (hệ thống thật chọn lại mỗi lần tính)."""
        cached = self.hw.get(key)
        if cached and (today - cached[1]).days < 7:
            return cached[0]
        obs = [(t, x) for t, x, st in series if st == "ok"]
        params = methods.hw_fit(obs) if len(obs) >= methods.DEFAULT.hw_min_days else None
        self.hw[key] = (params, today)
        return params

    def _decide(self, key, fc, today):
        """Ghi cách tự chọn lần đầu; Chủ quán giả lập duyệt mọi đề xuất đổi (BRU-37), mỗi chuỗi tối đa một lần trong 4
        tuần như planning._hold_proposal."""
        if fc.get("stage") != methods.STAGE_MODEL or not fc.get("method"):
            return
        if key not in self.choice and fc.get("auto_pick"):
            self.choice[key] = (fc["method"], today)
        elif fc.get("proposal") and key in self.choice and (today - self.choice[key][1]).days >= 28:
            self.choice[key] = (fc["proposal"]["method"], today)

    def approved(self, key):
        return self.choice[key][0] if key in self.choice else None

    def _hierarchy(self, today):
        items = [hierarchy.Item(name, self.item_series[name], it["usage"], group=it["group"])
                 for name, it in self.w.items.items()]
        self.h = hierarchy.build(self.total_series, items, today=today, horizon=self.rules.horizon,
                                 approved=self.approved("tong"),
                                 hw_params=self._hw_params("tong", self.total_series, today))
        self.h_items = items
        self._decide("tong", self.h["total"], today)

    # ----- quyết định mua -----
    def _plan(self, s, today):
        if self.owner == "habit":
            return self._habit(s, today)
        r = self.rules
        g = self.group(s)
        R = r.a_review if g == "A" else r.b_review
        T = r.a_target if g == "A" else R
        csl = self.csl(s)
        k = policy.k_for(csl)
        series = self.series[s.name]
        recent = [st for _, _, st in series[-56:] if st != "dong_cua"]
        blocked = sum(1 for st in recent if st == "bo_qua") / len(recent) if recent else 0.0
        external, external_daily = (hierarchy.ingredient_forecast(self.h, self.h_items, s.name) if self.h and r.hierarchy
                                    else (None, None))
        cls = methods.demand_class(series, today) if series else None
        candidates = list(r.candidates) + (["TSB"] if cls and cls["intermittent"] else []) + \
            (["PH"] if external_daily is not None else [])
        fc = methods.forecast_series(
            series, today=today, horizon=r.horizon, candidates=candidates, approved=self.approved(s.name),
            estimate=self.estimate[s.name], estimate_since=self.w.start, external=external,
            external_daily=external_daily, decision_h=R + s.lead, target_h=T + s.lead, k=k, csl=csl,
            blocked_share=blocked, hw_params=self._hw_params(s.name, series, today) if "HW" in candidates else None)
        self._decide(s.name, fc, today)
        self.last_fc[s.name] = (fc, R + s.lead)
        self.k[s.name]["methods"][fc.get("method")] = self.k[s.name]["methods"].get(fc.get("method"), 0) + 1
        if not fc.get("method"):
            return
        daily = {}
        for j in range(r.horizon):
            t = today + timedelta(days=j)
            v = fc["daily"].get(t.isoformat())
            if v is not None:
                daily[t] = v
        lots, excluded = [], []
        for o in self.orders[s.name]:
            lot = policy.Lot(o.qty, o.expected, "da_dat")
            (lots if o.expected >= today else excluded).append(lot)
            if o.expected < today:
                lot.status, lot.label = "giao_cham", "giao chậm"
        inp = policy.Inputs(
            today=today, daily=daily, sigma=fc.get("sigma", []), csl=csl, available=self.on_hand(s.name),
            physical=self.on_hand(s.name), lots=lots, excluded=excluded, f0=0.0, group=g, review_days=R,
            target_days=T, review_weekday=r.b_weekday, exposure=s.lead, pack=s.pack, unit=s.unit, moq=s.moq,
            shelf_life=s.shelf, capacity=s.capacity, quantiles=quantile_mode(fc),
            sigma_measured=fc.get("sigma_measured"),
            on_hand_lots=[(x.qty, x.expires) for x in self.lots[s.name]] if r.aging else None)
        res = policy.compute(inp)
        act = res["action"]
        if act == policy.EXPEDITE:
            late = [o for o in self.orders[s.name] if o.expected < today or o.actual > today + timedelta(days=1)]
            if late and self.rnd.random() < 0.5:
                late[0].actual, late[0].midday = today + timedelta(days=1), False
                self.k[s.name]["expedited"] += 1
                return
        alert = res.get("order_by") is not None and res["order_by"] <= today
        if res["need"] and res["quantity"] > 0 and (res["triggered"] or alert or act == policy.EXPEDITE):
            self._order(s, res["quantity"], today)

    def _habit(self, s, today):
        """Cách làm khi chưa có hệ thống: nhóm dễ hỏng mua cách ngày, nhóm khác mua Chủ nhật hằng tuần, mua đủ
        lên mức "cho chắc" theo ước tính tuần cố định, không tính thứ trong tuần hay hàng đang về."""
        g = self.group(s)
        weekly = self.estimate[s.name][1]
        if g == "A":
            if (today - self.w.start).days % 2:
                return
            target = weekly / 7 * (2 + s.lead) * 1.15
        else:
            if today.weekday() != 6:
                return
            target = weekly / 7 * (7 + s.lead) * 1.15
        gap = target - self.on_hand(s.name)
        if gap > 0:
            packs = math.ceil(gap / s.pack - 0.25)
            if packs > 0:
                self._order(s, packs * s.pack, today)

    def _order(self, s, qty, today):
        expected = today + timedelta(days=s.lead)
        actual = expected + timedelta(days=1) if self.rnd.random() < s.late_p else expected
        midday = self.rnd.random() < 0.3
        self.orders[s.name].append(Order(qty, expected, actual, midday))
        self.k[s.name]["orders"] += 1
        self.k[s.name]["ordered"] += qty

    # ----- kết quả -----
    def report(self, skip_days=28):
        months = [m for m in sorted(self.months)]
        per_ing = {}
        for name, k in self.k.items():
            s = self.specs[name]
            per_ing[name] = {
                "group": self.group(s), "csl": self.csl(s) if self.owner == "system" else None,
                "stockout_days": k["stockout_days"], "fill_rate": k["used"] / k["demand"] if k["demand"] else 1.0,
                "expired_share": k["expired"] / k["received"] if k["received"] else 0.0,
                "cover_days": k["on_hand_sum"] / k["days"] / (k["demand"] / k["days"]) if k["demand"] else None,
                "orders": k["orders"], "methods": dict(k["methods"]), "expedited": k["expedited"],
                **_accuracy(*self.last_fc.get(name, ({}, 1)))}
        total_days = sum(self.months[m]["days"] for m in months)
        tfc = (self.h or {}).get("total") or {}
        return {"label": self.rules.label if self.owner == "system" else "Cách làm cũ (theo thói quen)",
                "total": {**_accuracy(tfc, hierarchy.TOTAL_DECISION_H), "item_wape_1": (self.h or {}).get("item_wape")},
                "months": {m: dict(self.months[m]) for m in months},
                "stockouts_per_month": sum(self.months[m]["stockouts"] for m in months) / total_days * 30,
                "lost_cup_share": self.lost_cups / self.cups if self.cups else 0.0,
                "ingredients": per_ing}


def _accuracy(fc, h):
    """Cách tính cuối cùng và sai số cuốn chiếu của nó ở cửa sổ quyết định: WAPE (tổng sai số tuyệt đối / tổng thực
    tế) và độ chệch tương đối (dương là dự báo thấp hơn thực tế)."""
    st = ((fc.get("errors") or {}).get(fc.get("method")) or {}).get(str(h)) or {}
    mean = None
    if st.get("wape") and st.get("mae"):
        mean = st["mae"] / st["wape"]
    return {"method": fc.get("method"), "wape": st.get("wape"),
            "bias_share": st["bias"] / mean if mean and st.get("bias") is not None else None}


def _new_kpi():
    return {"demand": 0.0, "used": 0.0, "stockout_days": 0, "expired": 0.0, "received": 0.0, "on_hand_sum": 0.0,
            "days": 0, "orders": 0, "ordered": 0.0, "methods": {}, "expedited": 0}


def quantile_mode(fc, need=methods.DEFAULT.quantile_min):
    """Như planning._quantile_mode: phân vị sai số khi đủ gốc đánh giá, không âm."""
    q, n = fc.get("error_quantiles") or {}, fc.get("quantile_n") or {}
    ok = {int(h): max(v, 0.0) for h, v in q.items() if n.get(h, 0) >= need}
    return {"by_h": ok} if ok else None


def csl_for_target(per_month, n_items, cycles_per_month):
    """Mức phục vụ chu kỳ suy từ số trường hợp thiếu cho phép mỗi tháng toàn quán (tiêu chí thời gian trung bình giữa
    hai lần thiếu hàng, Silver, Pyke và Peterson): mỗi nguyên liệu được chia đều phần cho phép, chia cho số chu kỳ
    bổ sung trong tháng. Giới hạn 90%–99,5% để không đòi tồn an toàn vô hạn."""
    p = per_month / max(n_items, 1) / max(cycles_per_month, 1e-9)
    return round(min(99.5, max(90.0, 100 * (1 - p))), 1)


def simulate(rules=None, owner="system", seed=1, days=364, start=date(2026, 11, 2), specs=SPECS):
    world = World(start=start, days=days, seed=seed)
    return Store(world, specs, rules or Rules(), owner=owner, seed=seed).run()
