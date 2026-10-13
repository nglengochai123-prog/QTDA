"""Phương pháp dự báo tiêu hao nguyên liệu theo ngày và sai số cửa sổ (thiết kế mua nguyên liệu mục 4.4, 6.2).

- M0: ước tính tuần của Chủ quán (thấp, thường lệ, cao), phân bổ theo hồ sơ thứ trong tuần; độ lệch chuẩn tuần bằng
  (cao − thấp) / 3,29 vì khoảng thấp–cao được coi là khoảng tin cậy 90%.
- M1: trung bình cùng thứ của 4 đến 8 tuần gần nhất, chỉ trên ngày đủ điều kiện.
- M2: mô hình tuyến tính động chuẩn (West và Harrison) với mức và 7 hệ số thứ, chiết khấu mức và mùa vụ theo tham số
  dự báo hiện có, phương sai quan sát chưa biết (cập nhật liên hợp); tiên nghiệm lấy từ M0 khi có.
- Sai số: đánh giá gốc trượt, mỗi gốc dự báo h ngày mở cửa kế tiếp, σ_h là căn trung bình bình phương tổng sai số,
  kèm độ chệch và độ phủ; bỏ gốc có ngày bị bỏ qua trong cửa sổ.

Hàm thuần trên chuỗi [(ngày, giá trị hoặc None, trạng thái)]; không đọc cơ sở dữ liệu.
"""

import math
from datetime import timedelta

H_MAX = 10
Z90 = 1.645  # nửa độ rộng của khoảng 90% theo phân phối chuẩn: thấp–cao = 2 × 1,645 σ = 3,29 σ


# ---------------- M0 ----------------

def weekday_profile(series, today, weeks=8):
    """Tỷ trọng mỗi thứ trong tuần (tổng bằng 1) từ ngày đủ điều kiện; thiếu thứ nào thì chia đều."""
    lo = today - timedelta(days=7 * weeks)
    sums, counts = [0.0] * 7, [0] * 7
    for d, x, st in series:
        if st == "ok" and d >= lo:
            sums[d.weekday()] += x
            counts[d.weekday()] += 1
    if min(counts) == 0 or sum(sums) <= 0:
        return [1 / 7] * 7
    means = [s / c for s, c in zip(sums, counts)]
    total = sum(means)
    return [m / total for m in means]


class OwnerEstimate:
    def __init__(self, low, typical, high, profile):
        self.low, self.typical, self.high = float(low), float(typical), float(high)
        self.profile = profile
        self.sd_week = max((self.high - self.low) / (2 * Z90), 0.0)

    def mean(self, d):
        return self.typical * self.profile[d.weekday()]

    def sigma(self, h):
        """Độ lệch chuẩn tổng h ngày từ khoảng tuần của Chủ quán (coi các tuần bất định như nhau, tỷ lệ √(h/7))."""
        return self.sd_week * math.sqrt(h / 7)


# ---------------- M1 ----------------

def m1_table(history, end, weeks=8):
    """Trung bình cùng thứ trên tối đa `weeks` quan sát đủ điều kiện gần nhất trong 8 tuần tính tới ngày `end`
    (gồm cả `end`); thứ chưa có quan sát dùng trung bình chung. Trả {thứ: trung bình} hoặc None nếu chưa có dữ liệu."""
    lo = end - timedelta(days=7 * weeks - 1)
    by_dow = [[] for _ in range(7)]
    for t, x, st in history:
        if st == "ok" and lo <= t <= end:
            by_dow[t.weekday()].append(x)
    allv = [x for xs in by_dow for x in xs]
    if not allv:
        return None
    overall = sum(allv) / len(allv)
    return {dow: (sum(xs[-weeks:]) / len(xs[-weeks:]) if xs else overall) for dow, xs in enumerate(by_dow)}


# ---------------- M2 ----------------

def _matvec(A, v):
    return [sum(a * b for a, b in zip(row, v)) for row in A]


class NormalDLM:
    """Mức + 7 hệ số thứ, G = I, chiết khấu theo khối, phương sai quan sát chưa biết (n, S)."""

    def __init__(self, level, factors, level_var, factor_var, S0, delta_level=0.95, delta_season=0.99):
        self.m = [level] + list(factors)
        self.C = [[0.0] * 8 for _ in range(8)]
        self.C[0][0] = level_var
        for j in range(1, 8):
            self.C[j][j] = factor_var
        self.n, self.S = 1.0, max(S0, 1e-6)
        self.dl, self.ds = delta_level, delta_season

    def _W(self, C=None):
        C = C or self.C
        W = [[0.0] * 8 for _ in range(8)]
        W[0][0] = C[0][0] * (1 / self.dl - 1)
        for i in range(1, 8):
            for j in range(1, 8):
                W[i][j] = C[i][j] * (1 / self.ds - 1)
        return W

    def _R(self):
        W = self._W()
        return [[self.C[i][j] + W[i][j] for j in range(8)] for i in range(8)]

    @staticmethod
    def _F(dow):
        F = [0.0] * 8
        F[0] = 1.0
        F[1 + dow] = 1.0
        return F

    def skip(self):
        self.C = self._R()

    def update(self, y, dow):
        R = self._R()
        F = self._F(dow)
        RF = _matvec(R, F)
        f = sum(a * b for a, b in zip(F, self.m))
        Q = sum(a * b for a, b in zip(F, RF)) + self.S
        e = y - f
        A = [x / Q for x in RF]
        n1 = self.n + 1
        S1 = self.S + (self.S / n1) * (e * e / Q - 1)
        S1 = max(S1, 1e-6)
        self.m = [m + a * e for m, a in zip(self.m, A)]
        scale = S1 / self.S
        self.C = [[scale * (R[i][j] - A[i] * A[j] * Q) for j in range(8)] for i in range(8)]
        self.n, self.S = n1, S1

    def mean(self, dow):
        return self.m[0] + self.m[1 + dow]

    def state(self):
        return [list(self.m), [list(r) for r in self.C], self.n, self.S]

    def restore(self, st):
        self.m, self.C, self.n, self.S = list(st[0]), [list(r) for r in st[1]], st[2], st[3]


def m2_model(prior, series, delta_level, delta_season):
    """Mô hình M2 khởi tạo từ tiên nghiệm M0 nếu có, nếu không từ tuần dữ liệu đầu tiên (tiên nghiệm rộng)."""
    if prior is not None:
        level = prior.typical / 7
        factors = [prior.typical * p - level for p in prior.profile]
        day_sd = prior.sd_week / math.sqrt(7) if prior.sd_week > 0 else 0.3 * level
        return NormalDLM(level, factors, (0.3 * level) ** 2 + day_sd ** 2, (0.2 * level) ** 2 + 1e-6,
                         max(day_sd ** 2, 1e-6), delta_level, delta_season)
    first = [x for _, x, st in series if st == "ok"][:7]
    level = sum(first) / len(first) if first else 0.0
    var = (sum((x - level) ** 2 for x in first) / len(first)) if len(first) > 1 else (0.5 * level) ** 2
    return NormalDLM(level, [0.0] * 7, max(level ** 2, 1e-6), max((0.5 * level) ** 2, 1e-6), max(var, 1e-6),
                     delta_level, delta_season)


# ---------------- đánh giá gốc trượt ----------------

def _next_open(series_index, start_idx, h):
    """Chỉ số của h ngày mở cửa kế tiếp sau start_idx; None nếu gặp ngày bị bỏ qua hoặc hết dữ liệu."""
    out, j = [], start_idx + 1
    while len(out) < h and j < len(series_index):
        st = series_index[j][2]
        if st == "bo_qua":
            return None
        if st == "ok":
            out.append(j)
        j += 1
    return out if len(out) == h else None


def rolling(series, method, *, prior=None, delta_level=0.95, delta_season=0.99, lookback=84, h_max=H_MAX):
    """Sai số cửa sổ theo gốc trượt cho phương pháp 'M0' | 'M1' | 'M2'.

    Trả {"origins": [(ngày gốc, {h: sai số tổng})], "by_h": {h: {"rmse", "bias", "n"}}}. Gốc nằm trong `lookback` ngày
    cuối; mỗi gốc dự báo bằng dữ liệu tới hết ngày gốc."""
    if not series:
        return {"origins": [], "by_h": {}}
    last = series[-1][0]
    first_origin = last - timedelta(days=lookback)
    model = m2_model(prior, series, delta_level, delta_season) if method == "M2" else None
    origins = []
    for idx, (d, x, st) in enumerate(series):
        if model is not None:
            if st == "ok":
                model.update(x, d.weekday())
            else:
                model.skip()
        if d < first_origin:
            continue
        table = m1_table(series[max(0, idx - 70):idx + 1], d) if method == "M1" else None
        if method == "M1" and table is None:
            continue
        errors = {}
        for h in range(1, h_max + 1):
            nxt = _next_open(series, idx, h)
            if nxt is None:
                break
            pred = 0.0
            for j in nxt:
                t = series[j][0]
                if method == "M0":
                    pred += prior.mean(t)
                elif method == "M1":
                    pred += table[t.weekday()]
                else:
                    pred += model.mean(t.weekday())
            errors[h] = sum(series[j][1] for j in nxt) - pred
        if errors:
            origins.append((d, errors))
    return {"origins": origins, "by_h": summarize(origins, h_max)}


def summarize(origins, h_max=H_MAX):
    out = {}
    for h in range(1, h_max + 1):
        es = [e[h] for _, e in origins if h in e]
        if es:
            out[h] = {"rmse": math.sqrt(sum(x * x for x in es) / len(es)), "bias": sum(es) / len(es), "n": len(es),
                      "errors": es}
    return out


def coverage(errors, quantile):
    return sum(1 for e in errors if e <= quantile) / len(errors) if errors else None


def empirical_quantile(values, p):
    s = sorted(values)
    if not s:
        return None
    pos = p * (len(s) - 1)
    lo = int(math.floor(pos))
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


# ---------------- chọn phương pháp và giai đoạn ----------------

STAGE_OWNER, STAGE_EARLY, STAGE_MODEL = "uoc_tinh", "buoc_dau", "mo_hinh"
STAGE_LABELS = {STAGE_OWNER: "Ước tính ban đầu, theo ước tính Chủ quán",
                STAGE_EARLY: "Thống kê bước đầu, độ tin cậy thấp", STAGE_MODEL: "Đã đánh giá"}
METHOD_LABELS = {"M0": "Ước tính của Chủ quán", "M1": "Trung bình theo thứ", "M2": "Mô hình tuyến tính động Bayes"}


def forecast_ingredient(series, *, today, horizon, estimate=None, delta_level=0.95, delta_season=0.99,
                        previous_method=None, decision_h=2, k=1.645, csl=95, blocked_share=0.0,
                        blocked_limit=0.2, switch_gain=0.05, switch_days=28, bias_limit=0.5):
    """Dự báo U b theo ngày từ hôm nay và σ_h, theo giai đoạn dữ liệu (mục 4.4).

    estimate: (thấp, thường lệ, cao) theo tuần, hoặc None. Trả dict lưu được bằng JSON (ngày dạng ISO)."""
    eligible = sum(1 for _, _, st in series if st == "ok")
    profile = weekday_profile(series, today)
    prior = OwnerEstimate(*estimate, profile) if estimate else None
    days = [today + timedelta(days=j) for j in range(horizon)]
    warnings, errors_by_method = [], {}
    decision_h = max(1, min(decision_h, H_MAX))
    if blocked_share > blocked_limit:
        warnings.append(f"{round(blocked_share * 100)}% số ngày trong 8 tuần bị chặn do hết hàng: dự báo có thể thấp"
                        + ("; dùng lại ước tính của Chủ quán." if prior else "."))
    out = {"eligible_days": eligible, "estimate": list(estimate) if estimate else None, "profile": profile,
           "warnings": warnings}
    if eligible < 14 or (blocked_share > blocked_limit and prior):
        if prior:
            out.update(method="M0", stage=STAGE_OWNER, sigma=[prior.sigma(h) for h in range(1, H_MAX + 1)],
                       sigma_label="theo khoảng của Chủ quán", provisional=True,
                       daily={d.isoformat(): prior.mean(d) for d in days})
            return out
        if eligible < 3:
            out.update(method=None, stage=STAGE_OWNER, sigma=[], sigma_label="", provisional=True, daily={})
            warnings.append("Chưa có ước tính tuần của Chủ quán và chưa đủ dữ liệu bán để tính.")
            return out
    if eligible < 56:
        method = "M2" if prior else "M1"
        res = rolling(series, method, prior=prior, delta_level=delta_level, delta_season=delta_season)
        errors_by_method[method] = res["by_h"]
        sigma1 = res["by_h"].get(1, {}).get("rmse")
        if not sigma1 or res["by_h"][1]["n"] < 8:
            vals = [x for _, x, st in series if st == "ok"]
            mean = sum(vals) / len(vals)
            sigma1 = math.sqrt(sum((x - mean) ** 2 for x in vals) / max(len(vals) - 1, 1))
        if eligible < 14:
            warnings.append(f"Mới có {eligible} ngày dữ liệu và chưa có ước tính tuần của Chủ quán: số liệu rất tạm.")
        out.update(method=method, stage=STAGE_EARLY,
                   sigma=[sigma1 * math.sqrt(h) for h in range(1, H_MAX + 1)],
                   sigma_label="ước lượng tạm, √h × σ1", provisional=True)
        out["daily"] = _predict(series, method, prior, days, delta_level, delta_season)
        out["errors"] = _jsonable_errors(errors_by_method)
        return out
    candidates = ["M1", "M2"] + (["M0"] if prior else [])
    results = {m: rolling(series, m, prior=prior, delta_level=delta_level, delta_season=delta_season)
               for m in candidates}
    for m, res in results.items():
        errors_by_method[m] = res["by_h"]
    usable = []
    for m in candidates:
        st = results[m]["by_h"].get(decision_h)
        if not st or st["n"] < 8:
            continue
        if abs(st["bias"]) > bias_limit * st["rmse"]:
            warnings.append(f"{METHOD_LABELS[m]} lệch hệ thống (độ chệch {st['bias']:.0f} so với σ {st['rmse']:.0f}); "
                            f"không dùng.")
            continue
        usable.append(m)
    if not usable:
        measured_ok = [m for m in candidates if (results[m]["by_h"].get(decision_h) or {}).get("n", 0) >= 8]
        if measured_ok:
            least = min(measured_ok, key=lambda m: abs(results[m]["by_h"][decision_h]["bias"])
                        / max(results[m]["by_h"][decision_h]["rmse"], 1e-9))
            usable = [least]
            warnings.append(f"Mọi phương pháp đều lệch hệ thống; tạm dùng {METHOD_LABELS[least]} vì ít lệch nhất. "
                            f"Cần xem lại dữ liệu hoặc ước tính.")
    incumbent = previous_method if previous_method in usable else ("M1" if "M1" in usable else
                                                                   (usable[0] if usable else "M1"))
    method = incumbent
    for m in usable:
        if m == incumbent:
            continue
        gain = _recent_gain(results[incumbent]["origins"], results[m]["origins"], decision_h, switch_days)
        if gain is not None and gain >= switch_gain:
            method = m
            if previous_method:
                warnings.append(f"Chuyển sang {METHOD_LABELS[m]}: sai số thấp hơn {gain * 100:.0f}% trong "
                                f"{switch_days // 7} tuần gần nhất.")
            break
    by_h = results[method]["by_h"]
    sigma, measured = [], True
    for h in range(1, H_MAX + 1):
        st = by_h.get(h)
        if st and st["n"] >= 8:
            sigma.append(st["rmse"])
        else:
            measured = False
            base = by_h.get(1, {}).get("rmse") or 0.0
            sigma.append(base * math.sqrt(h))
    quantiles, q_cov = _quantile_check(by_h, csl)
    out.update(method=method, stage=STAGE_MODEL, sigma=sigma, provisional=not measured,
               sigma_label="đo trực tiếp" if measured else "ước lượng tạm, √h × σ1",
               daily=_predict(series, method, prior, days, delta_level, delta_season),
               errors=_jsonable_errors(errors_by_method), error_quantiles=quantiles, quantile_coverage=q_cov,
               ksigma_coverage={h: coverage(by_h[h]["errors"], k * by_h[h]["rmse"]) for h in by_h})
    return out


def _recent_gain(inc_origins, new_origins, h, days):
    """Mức giảm sai số của phương pháp mới so với phương pháp đang dùng trên cùng các gốc trong `days` ngày gần nhất."""
    a = {d: e[h] for d, e in inc_origins if h in e}
    b = {d: e[h] for d, e in new_origins if h in e}
    common = sorted(set(a) & set(b))
    if not common or (common[-1] - common[0]).days + 1 < days:
        return None
    cut = common[-1] - timedelta(days=days - 1)
    common = [d for d in common if d >= cut]
    ra = math.sqrt(sum(a[d] ** 2 for d in common) / len(common))
    rb = math.sqrt(sum(b[d] ** 2 for d in common) / len(common))
    return (ra - rb) / ra if ra > 0 else None


def _quantile_check(by_h, csl):
    """Phân vị CSL của sai số (nửa đầu các gốc) và độ phủ của nó trên nửa sau; dùng để bật cách phân vị."""
    quantiles, cov = {}, {}
    for h, st in by_h.items():
        es = st["errors"]
        if len(es) < 16:
            continue
        half = len(es) // 2
        q_first = empirical_quantile(es[:half], csl / 100)
        cov[h] = coverage(es[half:], q_first)
        quantiles[h] = empirical_quantile(es, csl / 100)
    return quantiles, cov


def _predict(series, method, prior, days, delta_level, delta_season):
    if method == "M0":
        return {d.isoformat(): prior.mean(d) for d in days}
    if method == "M1":
        table = m1_table(series, series[-1][0]) if series else None
        return {d.isoformat(): (table[d.weekday()] if table else 0.0) for d in days}
    model = m2_model(prior, series, delta_level, delta_season)
    for d, x, st in series:
        if st == "ok":
            model.update(x, d.weekday())
        else:
            model.skip()
    return {d.isoformat(): max(model.mean(d.weekday()), 0.0) for d in days}


def _jsonable_errors(errors_by_method):
    return {m: {str(h): {"rmse": round(v["rmse"], 2), "bias": round(v["bias"], 2), "n": v["n"]}
                for h, v in by_h.items()} for m, by_h in errors_by_method.items()}
