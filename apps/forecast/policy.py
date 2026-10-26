"""Bộ tính chính sách mua cho một nguyên liệu (thiết kế mua nguyên liệu mục 6, 8.2, 9.1).

Hàm thuần: nhận nhu cầu dự báo theo ngày, sai số cửa sổ, tồn, hàng đang về và tham số; trả mọi đại lượng cần hiển thị.
Không đọc cơ sở dữ liệu, không ghi gì, không liên hệ nhà cung cấp; phần đọc dữ liệu và lưu kết quả ở planning.py.

Quy ước thời gian:
- Hôm nay là t0; f0 là tỷ lệ bán còn lại của hôm nay theo hồ sơ giờ, bằng 0 sau giờ đóng cửa.
- Cửa sổ n ngày gồm phần còn lại của hôm nay và n ngày lịch kế tiếp; ngày đóng cửa có nhu cầu 0. Sai số σ_h lấy
  theo h là số ngày mở cửa trong cửa sổ.
- Lô đang về được cộng vào tồn dự kiến cuối ngày giao dự kiến (giả định xấu: về cuối ngày), nên mỗi ngày có hai mức:
  tồn trước khi hàng về (thấp nhất trong ngày) và tồn cuối ngày. Thiếu hàng và rủi ro xét theo tồn trước khi hàng về,
  để không bỏ sót khoảng thiếu trong chính ngày giao. Lô mới đặt hôm nay về sau ℓ ngày.
- Lịch kiểm tra định kỳ tính từ ngày kiểm tra gốc và chu kỳ R; giám sát liên tục sau mỗi biến động chỉ kích hoạt khi
  ngày phải đặt rơi vào trước lần kiểm tra kế tiếp.
- Hàng có hạn dùng (khi biết các lô đang có và hạn của từng lô): dòng tồn chạy theo lô, dùng lô cũ trước (FIFO), lô quá
  hạn bị bỏ cuối ngày. Vị thế tồn trừ phần dự kiến hết hạn trong cửa sổ, theo chính sách EWA (Estimated Withdrawal and
  Aging) của Broekmeulen và van Donselaar 2009 cho hàng dễ hỏng có thời gian giao và nhu cầu đổi theo ngày. Không có
  thông tin lô thì giữ cách tính cũ (coi toàn bộ tồn đều dùng được).
"""

import math
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from statistics import NormalDist

WEEKDAYS = ["thứ Hai", "thứ Ba", "thứ Tư", "thứ Năm", "thứ Sáu", "thứ Bảy", "Chủ nhật"]

# Ngày gốc mặc định của lịch kiểm tra khi Chủ quán chưa khai: thứ Hai 05/01/2026 (cộng thêm thứ kiểm tra nếu chu kỳ
# là bội của 7 ngày).
EPOCH = date(2026, 1, 5)

BUY, TOP_UP, EXPEDITE, NONE, NO_DATA = "mua", "mua_bo_sung", "thuc_giao", "khong_can", "thieu_du_lieu"
ACTION_LABELS = {BUY: "Mua", TOP_UP: "Mua bổ sung", EXPEDITE: "Thúc giao", NONE: "Không cần mua",
                 NO_DATA: "Chưa đủ dữ liệu"}


def k_for(csl_percent):
    """Hệ số an toàn k = Φ⁻¹(CSL), làm tròn 3 chữ số như bảng tra (95% → 1,645; 90% → 1,282)."""
    return round(NormalDist().inv_cdf(csl_percent / 100), 3)


def whole(x):
    """Làm tròn nửa lên tới đơn vị chuẩn: tồn an toàn và các mức hiển thị theo đơn vị nguyên."""
    return float(Decimal(str(x)).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _ceil(x):
    return int(math.ceil(x - 1e-9))


def _floor(x):
    return int(math.floor(x + 1e-9))


def day_label(d):
    return f"{WEEKDAYS[d.weekday()]} {d:%d/%m}"


@dataclass
class Lot:
    """Một đơn đặt còn phải giao: lượng còn lại, ngày giao dự kiến, trạng thái."""

    quantity: float
    arrival: object  # date
    status: str = "da_dat"
    po_id: int = None
    label: str = ""
    at_start: bool = False  # về trước giờ mở cửa (chỉ dùng khi mô phỏng đề nghị giao sớm)


@dataclass
class Inputs:
    today: object  # date
    daily: dict  # {date: d(t)} từ hôm nay; thiếu ngày thì coi như 0
    sigma: list  # σ_h cho h = 1..len(sigma); h lớn hơn thì ngoại suy √h
    csl: int = 95
    available: float = 0.0  # A = P − G
    physical: float = 0.0
    reserved: float = 0.0
    committed: float = 0.0  # C: phiếu dự phòng chưa nhập bù
    lots: list = field(default_factory=list)  # Nháp còn hạn, Đã đặt, Giao một phần
    excluded: list = field(default_factory=list)  # Giao chậm, nháp quá hạn: không tính, chỉ hiển thị
    f0: float = 0.0
    group: str = "A"
    review_days: int = 1  # R
    target_days: int = 2  # T
    review_weekday: int = 6
    exposure: int = 1  # ℓ
    pack: float = 1.0
    pack_label: str = "gói"
    unit: str = ""
    moq: int = 1
    shelf_life: int = None
    capacity: float = None
    manual_ss: float = 0.0
    closed: frozenset = frozenset()
    quantiles: dict = None  # {"s": q, "S": q} khi bật cách phân vị
    sigma_label: str = "đo trực tiếp"
    sigma_measured: list = None  # σ_h có đo trực tiếp đủ gốc hay chỉ là ước lượng tạm, theo h
    review_anchor: object = None  # ngày kiểm tra gốc của lịch định kỳ
    on_hand_lots: list = None  # [(lượng, ngày cuối còn dùng được)] của tồn hiện có; None: không theo dõi hạn


class Policy:
    def __init__(self, inp):
        self.i = inp
        self.k = k_for(inp.csl)

    # ---------- cửa sổ ----------
    def d(self, t):
        if t in self.i.closed:
            return 0.0
        return float(self.i.daily.get(t, 0.0))

    def sigma_h(self, h):
        sig = self.i.sigma
        if h <= 0 or not sig:
            return 0.0
        if h <= len(sig):
            return float(sig[h - 1])
        return float(sig[-1]) * math.sqrt(h / len(sig))

    def window(self, n):
        """Các ngày của cửa sổ: phần còn lại của hôm nay (nếu còn bán) và n ngày kế tiếp."""
        t0 = self.i.today
        days = [t0 + timedelta(days=j) for j in range(1, n + 1)]
        return ([t0] if self.i.f0 > 0 else []) + days

    def mu(self, n):
        t0 = self.i.today
        return self.i.f0 * self.d(t0) + sum(self.d(t) for t in self.window(n) if t != t0)

    def open_days(self, n):
        return sum(1 for t in self.window(n) if t not in self.i.closed)

    def ksigma(self, n):
        return whole(self.k * self.sigma_h(self.open_days(n)))

    def incoming_by(self, end):
        return sum(lot.quantity for lot in self.i.lots if lot.arrival <= end)

    def ip(self, n):
        end = self.i.today + timedelta(days=n)
        return self.i.available + self.incoming_by(end) - self.i.committed

    # ---------- dòng tồn ----------
    @property
    def aging(self):
        return self.i.on_hand_lots is not None

    def lot_expiry(self, arrival):
        """Ngày cuối còn dùng được của một lô về ngày `arrival`."""
        if not self.i.shelf_life:
            return date.max
        return arrival + timedelta(days=int(self.i.shelf_life) - 1)

    def timeline(self, horizon, lots=None):
        """Mỗi ngày từ hôm nay: tồn trước khi hàng về (sau nhu cầu cả ngày, trước lô giao cuối ngày), tồn cuối ngày
        I(t), lượng dự kiến hết hạn cuối ngày, và mức an toàn kσ của cửa sổ từ nay tới t.

        Khi biết lô: nhu cầu lấy từ lô hạn gần nhất trước; phần thiếu ghi âm và được lô về sau bù trước (giống cách
        không theo lô, để hai cách cho cùng kết quả khi hàng không có hạn)."""
        lots = self.i.lots if lots is None else lots
        t0 = self.i.today
        level = self.i.available - self.i.committed
        stock, deficit = [], 0.0
        if self.aging:
            stock = sorted(([float(q), e] for q, e in self.i.on_hand_lots if q > 0), key=lambda x: x[1])
            extra = level - sum(q for q, _ in stock)
            if extra > 1e-9:
                stock.insert(0, [extra, date.max])  # tồn không rõ lô: coi như không hết hạn
            elif extra < -1e-9:
                deficit = self._take(stock, -extra)  # đã giữ cho món chờ pha, phiếu dự phòng: lấy từ lô cũ nhất
        rows = []
        for j in range(horizon):
            t = t0 + timedelta(days=j)
            demand = self.i.f0 * self.d(t) if j == 0 else self.d(t)
            early_lots = [lot for lot in lots if lot.arrival == t and lot.at_start]
            if j == 0:
                early_lots += [lot for lot in lots if lot.arrival < t0]
            late_lots = [lot for lot in lots if lot.arrival == t and not lot.at_start]
            early = sum(lot.quantity for lot in early_lots)
            late = sum(lot.quantity for lot in late_lots)
            expiring = 0.0
            if not self.aging:
                before = level + early - demand
                level = before + late
            else:
                deficit = self._add(stock, early_lots, t, deficit)
                deficit += self._take(stock, demand)
                before = sum(q for q, _ in stock) - deficit
                deficit = self._add(stock, late_lots, t, deficit)
                expiring = sum(q for q, e in stock if e <= t)
                stock = [x for x in stock if x[1] > t]
                level = sum(q for q, _ in stock) - deficit
            rows.append({"date": t, "demand": round(demand, 2), "arriving": round(early + late, 2),
                         "before_arrival": round(before, 2), "level": round(level, 2),
                         "expiring": round(expiring, 2),
                         "safety": self.ksigma(j) if j > 0 or self.i.f0 > 0 else 0.0,
                         "closed": t in self.i.closed})
        return rows

    @staticmethod
    def _take(stock, qty):
        """Lấy từ lô hạn gần nhất trước; trả phần còn thiếu."""
        stock.sort(key=lambda x: x[1])
        for x in stock:
            if qty <= 1e-9:
                break
            use = min(x[0], qty)
            x[0] -= use
            qty -= use
        stock[:] = [x for x in stock if x[0] > 1e-9]
        return max(qty, 0.0)

    def _add(self, stock, lots, t, deficit):
        for lot in lots:
            q = lot.quantity
            cover = min(q, deficit)
            deficit -= cover
            if q - cover > 1e-9:
                stock.append([q - cover, self.lot_expiry(max(lot.arrival, t))])
        return deficit

    def outdating(self, rows, n):
        """Lượng dự kiến hết hạn từ nay tới hết cửa sổ n ngày (theo dòng tồn đã tính, chưa có lô đặt mới)."""
        end = self.i.today + timedelta(days=n)
        return sum(r["expiring"] for r in rows if r["date"] <= end)

    def scan(self, rows):
        """Ngày rủi ro: tồn trước khi hàng về < kσ(nay..t) lần đầu; ngày dự kiến hết: tồn trước khi hàng về < 0 lần đầu.
        Tồn cuối ngày dương không che được khoảng thiếu trước lô giao cuối ngày."""
        risk = stockout = None
        for j, r in enumerate(rows):
            if j == 0 and self.i.f0 <= 0:
                continue
            low = r["before_arrival"]
            if risk is None and low < r["safety"]:
                risk = r["date"]
            if stockout is None and low < 0:
                stockout = r["date"]
        return risk, stockout

    def business_days_before(self, day, n):
        d = day
        while n > 0:
            d -= timedelta(days=1)
            if d not in self.i.closed:
                n -= 1
        return d

    # ---------- kỳ kiểm tra ----------
    def review_schedule(self):
        """(R hiệu lực tới lần kiểm tra kế tiếp, T hiệu lực, hôm nay có phải ngày kiểm tra, ngày kiểm tra kế tiếp)."""
        i = self.i
        R, T = max(i.review_days, 1), max(i.target_days, i.review_days, 1)
        if R == 1:
            review_today, r_eff = True, 1
        else:
            anchor = i.review_anchor
            if anchor is None:
                anchor = EPOCH + timedelta(days=(i.review_weekday if R % 7 == 0 else 0))
            k = (i.today - anchor).days % R
            review_today = k == 0
            r_eff = R - k if k else R
        t_eff = max(r_eff, T - (R - r_eff))
        return r_eff, t_eff, review_today, i.today + timedelta(days=r_eff)

    # ---------- tính ----------
    def run(self):
        i = self.i
        ell = i.exposure
        r_eff, t_eff, review_today, next_review = self.review_schedule()
        n_s, n_S = r_eff + ell, t_eff + ell
        horizon = max(len(i.daily), n_S + 1, 2)
        mu_s, mu_S = round(self.mu(n_s), 2), round(self.mu(n_S), 2)
        sig_s, sig_S = self.sigma_h(self.open_days(n_s)), self.sigma_h(self.open_days(n_S))
        notes = []
        by_h = (i.quantiles or {}).get("by_h") or {}
        h_s, h_S = self.open_days(n_s), self.open_days(n_S)
        if i.quantiles and "s" in i.quantiles:
            ss_s, ss_S = whole(i.quantiles["s"] - mu_s), whole(i.quantiles["S"] - mu_S)
            ss_method = "phân vị"
        elif h_s in by_h and h_S in by_h:
            # Phân vị CSL của tổng cửa sổ = trung bình + phân vị sai số; tồn an toàn là số suy ra, không cộng kσ.
            ss_s, ss_S = whole(by_h[h_s]), whole(by_h[h_S])
            ss_method = "phân vị"
        else:
            ss_s, ss_S = whole(self.k * sig_s), whole(self.k * sig_S)
            ss_method = "kσ"
        computed_ss = (ss_s, ss_S)
        manual = float(i.manual_ss or 0)
        if manual > ss_s or manual > ss_S:
            notes.append(f"Dùng tồn an toàn Chủ quán nhập {fmt(manual)} {i.unit} vì lớn hơn số tính được "
                         f"{fmt(ss_s)} {i.unit}.")
            ss_s, ss_S = max(ss_s, manual), max(ss_S, manual)
        s, S = mu_s + ss_s, mu_S + ss_S
        ip_s, ip_S = self.ip(n_s), self.ip(n_S)
        rows = self.timeline(horizon)
        out_s = out_S = 0.0
        if self.aging:
            # EWA: phần dự kiến hết hạn trước khi kịp dùng không bảo vệ được cửa sổ.
            out_s, out_S = self.outdating(rows, n_s), self.outdating(rows, n_S)
            ip_s, ip_S = ip_s - out_s, ip_S - out_S
        risk, stockout = self.scan(rows)
        order_by = self.business_days_before(risk, ell + 1) if risk else None
        order_now = order_by is not None and order_by <= i.today
        arrival = i.today + timedelta(days=ell)
        # Kiểm tra định kỳ: chỉ vào ngày kiểm tra, so vị thế tồn với s. Giám sát liên tục: bất kỳ lúc nào, khi ngày phải
        # đặt rơi vào trước lần kiểm tra kế tiếp (đợi tới lần kiểm tra sau thì hàng về không kịp).
        triggered = review_today and ip_s <= s
        late_risk = order_by is not None and order_by < next_review
        need = triggered or late_risk
        trigger = "định kỳ" if triggered else "giám sát liên tục" if late_risk else None
        # Thiếu trước khi đơn đặt hôm nay kịp về: mua thường không cứu được, phải thúc giao hoặc mua gấp.
        urgent = risk is not None and risk <= arrival
        q0 = max(0.0, S - ip_S)
        # Lô về sau ngày rủi ro nằm trong cửa sổ vẫn được IP tính; dòng tồn theo ngày mới thấy khoảng thiếu trước khi
        # lô đó về, nên lấy kết luận khắt khe hơn (mục 6.6, 8.2). Lô mới về cuối ngày `arrival`: ngày đó chỉ được bù ở
        # tồn cuối ngày, các ngày sau được bù cả tồn trước khi hàng về.
        end_S = i.today + timedelta(days=n_S)
        gap = max([r["safety"] - (r["level"] if r["date"] == arrival else r["before_arrival"])
                   for r in rows if arrival <= r["date"] <= end_S] or [0.0])
        if gap > q0 + 1e-9 and risk is not None:
            notes.append(f"Dòng tồn thiếu {fmt(gap)} {i.unit} trước khi lô đang về tới; lượng đặt tính theo dòng tồn.")
            q0 = gap
        if urgent:
            short = max([r["safety"] - r["before_arrival"] for r in rows if r["date"] <= arrival] or [0.0])
            if short > q0:
                q0 = short
        idx = (arrival - i.today).days
        before = rows[idx - 1]["level"] if idx >= 1 else rows[0]["level"]
        old_stock = max(0.0, before)
        caps = {}
        if i.shelf_life:
            usable = self.demand_between(arrival, i.shelf_life)
            caps["hạn dùng"] = round(max(0.0, usable - old_stock), 2)
        if i.capacity:
            caps["sức chứa"] = round(max(0.0, i.capacity - old_stock), 2)
        packs, binding, expiry_excess = 0, None, 0.0
        infeasible, conflict, options = False, None, []
        pack = i.pack if i.pack and i.pack > 0 else 1.0
        action, expedite_po, expedite_day = self.choose_action(need, risk, n_S, horizon, arrival)
        if need and q0 > 0:
            if i.group == "B" and q0 < pack / 2 and not order_now:
                need = False
                notes.append(f"Lượng thiếu {fmt(q0)} {i.unit} dưới nửa {i.pack_label}: không mua tuần này.")
            else:
                packs = max(_ceil(q0 / pack), i.moq)
                reach = max(_ceil(max(s - ip_s, 0) / pack), i.moq)  # số gói nhỏ nhất giữ vị thế tồn không dưới s
                room = caps.get("sức chứa")
                if room is not None and packs * pack > room + 1e-9:
                    # Sức chứa là giới hạn vật lý: không bao giờ đề xuất vượt.
                    binding = "sức chứa"
                    fit = _floor(room / pack)
                    if fit >= i.moq and ip_s + fit * pack >= s:
                        packs = fit
                        notes.append(f"Giới hạn bởi sức chứa: mua {packs} {i.pack_label}, lần mua kế tiếp sẽ sớm hơn "
                                     f"{t_eff} ngày.")
                    else:
                        infeasible = True
                        packs = fit if fit >= i.moq else 0
                        options = [
                            f"Chia thành nhiều lần giao nhỏ hơn, mỗi lần không quá {fmt(room)} {i.unit}.",
                            f"Đổi sang quy cách nhỏ hơn {fmt(pack)} {i.unit} hoặc bỏ lượng đặt tối thiểu {i.moq} "
                            f"{i.pack_label}.",
                            "Đổi nhà cung cấp có quy cách hoặc lịch giao phù hợp.",
                            "Bổ sung chỗ bảo quản rồi khai lại sức chứa.",
                        ]
                        notes.append(f"Không khả thi trong sức chứa: cần khoảng {reach} {i.pack_label} để giữ mức phục "
                                     f"vụ nhưng chỉ chứa thêm được {fmt(room)} {i.unit}"
                                     + (f"; tạm đề xuất {packs} {i.pack_label} vừa sức chứa." if packs else "."))
                shelf = caps.get("hạn dùng")
                if not infeasible and shelf is not None and packs * pack > shelf + 1e-9:
                    fit = _floor(shelf / pack)
                    if room is not None:
                        fit = min(fit, _floor(room / pack))
                    binding = binding or "hạn dùng"
                    if fit >= i.moq and ip_s + fit * pack >= s:
                        packs = fit
                        binding = "hạn dùng"
                        notes.append(f"Giới hạn bởi hạn dùng: mua {packs} {i.pack_label}, lần mua kế tiếp sẽ sớm hơn "
                                     f"{t_eff} ngày.")
                    else:
                        # Hạn dùng là giới hạn mềm: xung đột với mức phục vụ, trình cả hai cách cho Chủ quán chọn.
                        conflict = binding = "hạn dùng"
                        packs = min(reach, packs)
                        expiry_excess = max(0.0, packs * pack - shelf)
                        options = [
                            f"Mua {packs} {i.pack_label}: giữ mức phục vụ {i.csl}%, dự kiến hết hạn khoảng "
                            f"{fmt(expiry_excess)} {i.unit}.",
                            f"Mua {max(fit, 0)} {i.pack_label}: không hết hạn, nhưng có thể thiếu trước lần mua kế tiếp "
                            f"(mức phục vụ thấp hơn {i.csl}%).",
                        ]
                        notes.append(f"Giới hạn bởi hạn dùng xung đột với mức phục vụ; đề xuất {packs} "
                                     f"{i.pack_label}, dự kiến hết hạn khoảng {fmt(expiry_excess)} {i.unit}.")
        elif need and action != EXPEDITE and not urgent:
            need = False  # vị thế tồn đã đủ tới mức mục tiêu
        if not need:
            action, expedite_po, expedite_day = NONE, None, None
        elif action != EXPEDITE and urgent:
            notes.append("Có thể thiếu trước khi đơn đặt hôm nay kịp về: cân nhắc mua gấp hoặc nhờ giao ngay.")
        quantity = round(packs * pack, 2)
        delta = round(quantity - q0, 2) if packs else 0.0
        if action == EXPEDITE and packs:
            notes.append("Nếu nhà cung cấp không giao sớm được, mua bổ sung theo số đề xuất.")
        sig_flags = i.sigma_measured or []

        def measured(h):
            return bool(sig_flags[h - 1]) if 0 < h <= len(sig_flags) else (i.sigma_measured is None)

        result = {
            "today": i.today, "f0": round(i.f0, 3), "k": self.k, "csl": i.csl, "group": i.group,
            "review_days": i.review_days, "target_days": i.target_days, "review_today": review_today,
            "r_eff": r_eff, "t_eff": t_eff,
            "next_review": next_review, "exposure": ell, "window_s_days": n_s, "window_S_days": n_S,
            "window_s": [t for t in self.window(n_s)], "window_S": [t for t in self.window(n_S)],
            "mu_s": mu_s, "mu_S": mu_S, "sigma_s": round(sig_s, 2), "sigma_S": round(sig_S, 2),
            "ss_method": ss_method, "sigma_label": i.sigma_label, "computed_ss": computed_ss,
            "ss_s": ss_s, "ss_S": ss_S, "s": round(s, 2), "S": round(S, 2), "manual_ss": manual,
            "ip_s": round(ip_s, 2), "ip_S": round(ip_S, 2), "outdating_s": round(out_s, 2),
            "outdating_S": round(out_S, 2), "available": i.available, "physical": i.physical,
            "reserved": i.reserved, "committed": i.committed,
            "counted_lots": [lot for lot in i.lots if lot.arrival <= i.today + timedelta(days=n_S)],
            "uncounted_lots": [lot for lot in i.lots if lot.arrival > i.today + timedelta(days=n_S)],
            "excluded_lots": i.excluded, "timeline": rows, "risk_date": risk, "stockout_date": stockout,
            "order_by": order_by, "order_now": order_now, "triggered": triggered, "need": need, "q0": round(q0, 2),
            "caps": caps, "binding": binding, "packs": packs, "quantity": quantity, "delta": delta,
            "expiry_excess": round(expiry_excess, 2), "action": action, "expedite_po": expedite_po,
            "expedite_day": expedite_day, "urgent": bool(urgent and need), "trigger": trigger if need else None,
            "infeasible": infeasible, "conflict": conflict, "options": options,
            "sigma_s_measured": measured(h_s), "sigma_S_measured": measured(h_S),
            "notes": notes, "cover_days": self.cover_days(rows), "stockout_part": self.stockout_part(rows, stockout),
        }
        result["reason"] = reason(result, i)
        return result

    def demand_between(self, start, days):
        """μ([start, start + days)); phần vượt tầm dự báo ngoại suy bằng trung bình 7 ngày cuối có dự báo."""
        total, known = 0.0, sorted(t for t in self.i.daily if t >= self.i.today)
        last7 = [self.d(t) for t in known[-7:]]
        filler = sum(last7) / len(last7) if last7 else 0.0
        for j in range(days):
            t = start + timedelta(days=j)
            total += self.d(t) if t in self.i.daily else filler
        return total

    def choose_action(self, need, risk, n_S, horizon, arrival):
        """Mua, Mua bổ sung (đã có lô đang về hoặc lô về sau ngày rủi ro), Thúc giao (đề nghị nhà cung cấp giao trước giờ
        mở cửa một ngày sớm hơn thì hết rủi ro trong cửa sổ mục tiêu). Trả (hành động, mã đơn, ngày đề nghị giao)."""
        i = self.i
        if not need:
            return NONE, None, None
        end = i.today + timedelta(days=n_S)
        first_day = i.today if i.f0 > 0 else i.today + timedelta(days=1)
        late_lots = [lot for lot in i.lots if risk and lot.arrival >= risk and lot.status != "nhap"]
        late_lots += [lot for lot in i.excluded if lot.status == "giao_cham"]
        for lot in sorted(late_lots, key=lambda x: x.arrival):
            day = max(min(lot.arrival, arrival), first_day)
            moved = [x for x in i.lots if x is not lot] + [Lot(lot.quantity, day, lot.status, lot.po_id, at_start=True)]
            r2, _ = self.scan(self.timeline(horizon, moved))
            if r2 is None or r2 > end:
                return EXPEDITE, lot.po_id, day
        if i.lots or i.excluded:
            return TOP_UP, None, None
        return BUY, None, None

    def cover_days(self, rows):
        """Số ngày bán đủ dùng theo nhu cầu kỳ vọng tính từ bây giờ, có phần lẻ của ngày hết hàng."""
        f0 = self.i.f0
        start = self.i.available - self.i.committed
        if f0 > 0 and rows[0]["before_arrival"] < 0:
            today_demand = rows[0]["demand"]
            return round(f0 * max(0.0, start) / today_demand, 1) if today_demand > 0 else 0.0
        prev = rows[0]["level"]
        for j, r in enumerate(rows):
            if j == 0:
                continue
            if r["before_arrival"] < 0:
                frac = prev / r["demand"] if r["demand"] > 0 else 0
                return round((f0 if f0 > 0 else 0) + j - 1 + max(0.0, min(1.0, frac)), 1)
            prev = r["level"]
        return None

    def stockout_part(self, rows, stockout):
        """Phần của ngày hết hàng đã bán được trước khi hết (0 là đầu ngày, 1 là cuối ngày)."""
        if stockout is None:
            return None
        for j, r in enumerate(rows):
            if r["date"] == stockout:
                before = rows[j - 1]["level"] if j > 0 else self.i.available - self.i.committed
                return round(max(0.0, min(1.0, before / r["demand"])), 2) if r["demand"] > 0 else 0.0
        return None


def fmt(x):
    """Số có dấu chấm ngăn nghìn như màn hình: 3900 → 3.900."""
    x = float(x)
    if abs(x - round(x)) < 0.005:
        return f"{round(x):,}".replace(",", ".")
    return f"{x:,.1f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _part_of_day(frac):
    return "đầu ngày" if frac < 0.34 else "giữa ngày" if frac < 0.67 else "cuối ngày"


def reason(r, i):
    """Một đến hai câu tự sinh từ số liệu (mục 9.1)."""
    unit = i.unit
    parts = [f"Tồn có thể dùng {fmt(r['available'])} {unit}"]
    if r["stockout_date"]:
        parts[0] += f", đủ tới khoảng {_part_of_day(r['stockout_part'] or 0)} {day_label(r['stockout_date'])}."
    else:
        parts[0] += ", đủ dùng trong tầm dự báo."
    for lot in r["uncounted_lots"]:
        if r["risk_date"] and lot.arrival > r["risk_date"]:
            parts.append(f"Lô {fmt(lot.quantity)} {unit} về {day_label(lot.arrival)}, sau ngày có thể thiếu nên không được "
                         f"tính.")
    for lot in r["excluded_lots"]:
        parts.append(f"Lô {fmt(lot.quantity)} {unit} {lot.label or 'giao chậm'} không được tính.")
    if r["action"] in (BUY, TOP_UP):
        when = "trong hôm nay" if r["order_now"] or (r["order_by"] and r["order_by"] <= r["today"]) else \
            f"trước hết {day_label(r['order_by'])}" if r["order_by"] else "trong lần kiểm tra này"
        earliest = r["today"] + timedelta(days=i.exposure)
        if r["risk_date"] and r["risk_date"] > earliest:
            target = f" để hàng về trước {day_label(r['risk_date'])}"
        elif r["risk_date"]:
            target = f"; có thể thiếu từ {day_label(r['risk_date'])} trước khi hàng về, nên cân nhắc mua gấp"
        else:
            target = ""
        if r["infeasible"]:
            parts.append("Không khả thi trong sức chứa; xem các cách xử lý.")
        else:
            parts.append(f"Cần đặt {when} {r['packs']} {i.pack_label}{target}.")
    elif r["action"] == EXPEDITE:
        parts.append(f"Đề nghị nhà cung cấp giao trước giờ mở cửa {day_label(r['expedite_day'])}.")
    elif r["risk_date"]:
        parts.append(f"Chưa cần mua; ngày phải đặt chậm nhất {day_label(r['order_by'])}.")
    else:
        parts.append("Chưa cần mua.")
    return " ".join(parts)


def compute(inputs):
    return Policy(inputs).run()
