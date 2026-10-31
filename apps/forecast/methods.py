"""Cách dự báo một chuỗi theo ngày, đánh giá cuốn chiếu và chọn cách tính (thiết kế mua nguyên liệu mục 4.4, 6.2;
phân tích "Lựa chọn mô hình dự báo và quản lý nguyên vật liệu cho LAM Coffee" ngày 27/10/2026).

Chuỗi là [(ngày, giá trị hoặc None, trạng thái)] liên tục theo lịch; trạng thái 'ok' (học được), 'dong_cua' (quán
nghỉ, không bán) hoặc 'bo_qua' (chưa chốt, hết hàng, bị chặn: không học và không đo sai số). Chuỗi có thể là tổng số
ly cả quán, số ly một món hay tiêu hao một nguyên liệu. Hàm thuần, không đọc cơ sở dữ liệu.

Các cách tính:
- M0  Ước tính của Chủ quán: tuần thấp, thường lệ, cao; chia theo hồ sơ thứ trong tuần. Khoảng thấp–cao coi là
      khoảng 90% nên độ lệch chuẩn tuần = (cao − thấp) / 3,29.
- LN  Bình quân theo loại ngày: trung bình các ngày cùng loại (ngày thường thứ Hai–thứ Sáu, cuối tuần thứ Bảy–Chủ
      nhật) trong 28 ngày gần nhất. Dùng khi mới có vài tuần dữ liệu, chưa đủ 4 lần cho mỗi thứ.
- WMA Bình quân có trọng số cùng thứ: 4 lần gần nhất của cùng thứ trong 8 tuần, trọng số 0,4 / 0,3 / 0,2 / 0,1 (lần
      mới nhất nặng nhất); thiếu lần thì chia lại trọng số, thứ chưa có lần nào thì lấy LN.
- HW  Holt-Winters cộng tính, xu hướng tắt dần, mùa vụ 7 ngày theo thứ (Hyndman và Athanasopoulos, Forecasting:
      Principles and Practice, mục 8.3–8.4). Ngày không học thì không cập nhật. Tham số α, β, γ chọn trên lưới bằng
      sai số một bước trong mẫu, chỉ trên dữ liệu có trước các gốc đánh giá. Chỉ dùng khi đủ 8 tuần ngày học được.
- TSB Teunter, Syntetos và Babai (2011) cho chuỗi bán lác đác: làm trơn riêng xác suất có bán và lượng khi có bán;
      dự báo = xác suất × lượng. Khác Croston ở chỗ tự giảm dần khi món lâu không bán.
- PH  Phân cấp (hierarchy.py): tổng số ly cả quán × tỷ trọng từng món × định mức nhiều tầng. Ở đây chỉ nhận dự báo
      đã tính sẵn tại từng gốc để đánh giá cùng một cách với các cách khác.

Đánh giá cuốn chiếu: tại mỗi gốc chỉ dùng thông tin có tới hết ngày gốc, dự báo h ngày học được kế tiếp và cộng dồn
(dừng trước ngày bị bỏ qua). Mỗi h ghi MAE, WAPE (tổng sai số tuyệt đối / tổng thực tế), độ chệch, RMSE và danh sách
sai số (thực − dự báo) để lấy phân vị cho tồn an toàn.

Chọn cách tính theo giai đoạn dữ liệu (BRU-21): dưới 14 ngày học được dùng ước tính của Chủ quán; 14 đến 55 ngày dùng
cách mặc định của giai đoạn (trộn với ước tính của Chủ quán theo số ngày đã có); từ 56 ngày lần đầu chọn cách có MAE
nhỏ nhất ở cửa sổ quyết định rồi giữ nguyên. Sau đó chỉ đổi khi Chủ quán duyệt (BRU-37): cách khác có MAE thấp hơn ít
nhất 5% trong 4 tuần gốc gần nhất thì được ghi thành đề xuất, không tự đổi.
"""

import math
from dataclasses import dataclass, replace
from datetime import timedelta

H_MAX = 10  # số h tối thiểu luôn được đo
H_MONTH = 31  # cửa sổ tháng hiển thị cho Chủ quán
Z90 = 1.645  # nửa độ rộng của khoảng 90% theo phân phối chuẩn: thấp–cao = 2 × 1,645 σ = 3,29 σ


@dataclass(frozen=True)
class Config:
    """Tham số của các cách tính. Giá trị dùng thật lấy từ apps/core/params.py (planning.method_config)."""

    wma_weights: tuple = (0.4, 0.3, 0.2, 0.1)
    wma_weeks: int = 8
    ln_days: int = 28
    hw_min_days: int = 56
    hw_alpha: tuple = (0.05, 0.1, 0.2, 0.3, 0.5)
    hw_beta: tuple = (0.0, 0.05)
    hw_gamma: tuple = (0.05, 0.1, 0.2, 0.3)
    hw_phi: float = 0.9
    tsb_alpha: float = 0.1
    tsb_beta: float = 0.1
    adi_cut: float = 1.32
    cv2_cut: float = 0.49
    owner_days: int = 14
    model_days: int = 56
    prior_days: int = 7
    min_origins: int = 8
    quantile_min: int = 20
    switch_gain: float = 0.05
    switch_days: int = 28
    bias_limit: float = 0.5
    lookback: int = 84
    auto_switch: bool = False


DEFAULT = Config()

STAGE_OWNER, STAGE_EARLY, STAGE_MODEL = "uoc_tinh", "buoc_dau", "mo_hinh"
STAGE_LABELS = {STAGE_OWNER: "Ước tính ban đầu, theo ước tính Chủ quán",
                STAGE_EARLY: "Thống kê bước đầu, độ tin cậy thấp", STAGE_MODEL: "Đã đánh giá"}
METHOD_LABELS = {"M0": "Ước tính của Chủ quán", "LN": "Bình quân theo loại ngày",
                 "WMA": "Bình quân có trọng số cùng thứ", "HW": "Holt-Winters chu kỳ 7 ngày",
                 "TSB": "TSB cho nhu cầu lác đác", "PH": "Phân cấp: tổng số ly × tỷ trọng món × định mức"}


def is_weekend(d):
    return d.weekday() >= 5


# ---------------- M0 ----------------

def weekday_profile(series, today, weeks=8):
    """Tỷ trọng mỗi thứ trong tuần (tổng bằng 1) từ ngày học được; thiếu thứ nào thì chia đều."""
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


# ---------------- LN, WMA ----------------

def _recent_ok(history, end, days):
    """Các (ngày, giá trị) học được trong `days` ngày tính tới `end`, mới nhất trước."""
    lo = end - timedelta(days=days - 1)
    out = []
    for t, x, st in reversed(history):
        if t > end:
            continue
        if t < lo:
            break
        if st == "ok":
            out.append((t, x))
    return out


def ln_table(history, end, cfg=DEFAULT):
    """{False: trung bình ngày thường, True: trung bình cuối tuần} trong cfg.ln_days ngày tới `end`; loại ngày chưa có
    thì dùng trung bình chung. None nếu chưa có ngày học được nào (khi đó lùi tới 8 tuần để tìm)."""
    recent = _recent_ok(history, end, cfg.ln_days) or _recent_ok(history, end, 7 * cfg.wma_weeks)
    if not recent:
        return None
    by = {False: [], True: []}
    for t, x in recent:
        by[is_weekend(t)].append(x)
    overall = sum(x for _, x in recent) / len(recent)
    return {k: (sum(v) / len(v) if v else overall) for k, v in by.items()}


def wma_table(history, end, cfg=DEFAULT):
    """{thứ: dự báo} theo bình quân có trọng số cùng thứ; None nếu chưa có dữ liệu."""
    need = len(cfg.wma_weights)
    by_dow = [[] for _ in range(7)]
    for t, x in _recent_ok(history, end, 7 * cfg.wma_weeks):
        xs = by_dow[t.weekday()]
        if len(xs) < need:
            xs.append(x)
    out, ln = {}, None
    for dow, xs in enumerate(by_dow):
        if xs:
            w = cfg.wma_weights[:len(xs)]
            out[dow] = sum(a * b for a, b in zip(w, xs)) / sum(w)
        else:
            ln = ln or ln_table(history, end, cfg)
            if ln is None:
                return None
            out[dow] = ln[dow >= 5]
    return out


# ---------------- HW ----------------

class HoltWinters:
    """Holt-Winters cộng tính, xu hướng tắt dần φ, mùa vụ theo thứ trong tuần. Đơn vị bước là ngày lịch."""

    def __init__(self, alpha, beta, gamma, phi, level, season, last):
        self.a, self.b, self.g, self.phi = alpha, beta, gamma, phi
        self.level, self.trend, self.season, self.last = level, 0.0, list(season), last

    def _damp(self, k):
        if k <= 0:
            return 0.0
        if self.phi >= 1:
            return float(k)
        return self.phi * (1 - self.phi ** k) / (1 - self.phi)

    def predict(self, t):
        return self.level + self._damp((t - self.last).days) * self.trend + self.season[t.weekday()]

    def update(self, t, y):
        """Cập nhật bằng quan sát y của ngày t; trả sai số một bước (y − dự báo)."""
        k = max((t - self.last).days, 1)
        dow = t.weekday()
        err = y - (self.level + self._damp(k) * self.trend + self.season[dow])
        prev = self.level
        base = self.level + self._damp(k) * self.trend
        self.level = self.a * (y - self.season[dow]) + (1 - self.a) * base
        self.trend = self.b * (self.level - prev) + (1 - self.b) * self.phi * self.trend
        self.season[dow] = self.g * (y - self.level) + (1 - self.g) * self.season[dow]
        self.last = t
        return err


def _hw_start(obs):
    """Mức và mùa vụ ban đầu từ 14 quan sát đầu: mức = trung bình 7 quan sát đầu, mùa vụ thứ d = trung bình các quan
    sát thứ d trong 14 quan sát đầu trừ trung bình chung (thứ chưa có thì 0)."""
    first = obs[:14]
    if len(first) < 7:
        return None
    level = sum(x for _, x in first[:7]) / 7
    mean = sum(x for _, x in first) / len(first)
    by = [[] for _ in range(7)]
    for t, x in first:
        by[t.weekday()].append(x)
    season = [(sum(v) / len(v) - mean) if v else 0.0 for v in by]
    return level, season


def hw_build(obs, params, cfg=DEFAULT):
    """Mô hình HW đã chạy qua các quan sát [(ngày, giá trị)] với tham số (α, β, γ); None nếu chưa đủ 7 quan sát."""
    start = _hw_start(obs)
    if start is None:
        return None
    a, b, g = params
    model = HoltWinters(a, b, g, cfg.hw_phi, start[0], start[1], obs[0][0] - timedelta(days=1))
    for t, x in obs:
        model.update(t, x)
    return model


def hw_fit(obs, cfg=DEFAULT):
    """Chọn (α, β, γ) trên lưới theo tổng bình phương sai số một bước, bỏ 14 quan sát khởi tạo."""
    start = _hw_start(obs)
    if start is None or len(obs) < 21:
        return None
    best, best_sse = None, None
    for a in cfg.hw_alpha:
        for b in cfg.hw_beta:
            for g in cfg.hw_gamma:
                model = HoltWinters(a, b, g, cfg.hw_phi, start[0], start[1], obs[0][0] - timedelta(days=1))
                sse = 0.0
                for i, (t, x) in enumerate(obs):
                    e = model.update(t, x)
                    if i >= 14:
                        sse += e * e
                if best_sse is None or sse < best_sse - 1e-9:
                    best, best_sse = (a, b, g), sse
    return best


# ---------------- TSB ----------------

class TSB:
    def __init__(self, alpha, beta, obs):
        first = obs[:14]
        nonzero = [x for _, x in first if x > 0]
        self.a, self.b = alpha, beta
        self.p = len(nonzero) / len(first) if first else 0.0
        self.z = sum(nonzero) / len(nonzero) if nonzero else 0.0

    def update(self, x):
        if x > 0:
            self.p += self.b * (1 - self.p)
            self.z += self.a * (x - self.z) if self.z else x - self.z
        else:
            self.p += self.b * (0 - self.p)

    @property
    def value(self):
        return self.p * self.z


def tsb_build(obs, cfg=DEFAULT):
    if not obs:
        return None
    model = TSB(cfg.tsb_alpha, cfg.tsb_beta, obs)
    for _, x in obs:
        model.update(x)
    return model


# ---------------- phân loại nhu cầu ----------------

def demand_class(series, end, cfg=DEFAULT, days=56):
    """Phân loại theo Syntetos và Boylan (2005) trên 8 tuần tới `end`: khoảng cách trung bình giữa hai ngày có bán (ADI)
    và bình phương hệ số biến thiên của lượng khi có bán (CV²); kèm nhóm XYZ theo hệ số biến thiên của lượng theo ngày
    (X dưới 0,5: ổn định; Y tới 1: dao động; Z trên 1: khó đoán)."""
    vals = [x for _, x in _recent_ok(series, end, days)]
    if not vals:
        return None
    nonzero = [x for x in vals if x > 0]
    adi = len(vals) / len(nonzero) if nonzero else float(len(vals) + 1)
    if len(nonzero) > 1:
        m = sum(nonzero) / len(nonzero)
        cv2 = (sum((x - m) ** 2 for x in nonzero) / (len(nonzero) - 1)) / (m * m) if m > 0 else 0.0
    else:
        cv2 = 0.0
    mean = sum(vals) / len(vals)
    cv = (math.sqrt(sum((x - mean) ** 2 for x in vals) / max(len(vals) - 1, 1)) / mean) if mean > 0 else None
    lumpy_q, erratic_q = adi > cfg.adi_cut, cv2 > cfg.cv2_cut
    kind = ("thua_tho" if lumpy_q and erratic_q else "lac_dac" if lumpy_q else
            "dao_dong" if erratic_q else "deu")
    xyz = "Z" if cv is None or cv > 1 else "Y" if cv > 0.5 else "X"
    return {"adi": round(adi, 2), "cv2": round(cv2, 3), "cv": round(cv, 3) if cv is not None else None,
            "kind": kind, "intermittent": lumpy_q, "xyz": xyz}


# ---------------- dự báo từ cuối chuỗi ----------------

def _obs(series, end=None):
    return [(t, x) for t, x, st in series if st == "ok" and (end is None or t <= end)]


def predictor(series, method, cfg=DEFAULT, *, estimate=None, profile=None, hw_params=None, external_daily=None):
    """Hàm ngày → dự báo dùng mọi dữ liệu của chuỗi; None nếu cách tính chưa dùng được."""
    end = series[-1][0] if series else None
    if method == "M0":
        if not estimate:
            return None
        owner = OwnerEstimate(*estimate, profile or weekday_profile(series, (end or 0) and end + timedelta(days=1)))
        return owner.mean
    if method == "PH":
        if external_daily is None:
            return None
        return lambda t: external_daily.get(t.isoformat(), 0.0)
    if not series:
        return None
    if method == "LN":
        table = ln_table(series, end, cfg)
        return (lambda t: table[is_weekend(t)]) if table else None
    if method == "WMA":
        table = wma_table(series, end, cfg)
        return (lambda t: table[t.weekday()]) if table else None
    obs = _obs(series)
    if method == "HW":
        params = hw_params or hw_fit(obs, cfg)
        model = hw_build(obs, params, cfg) if params and len(obs) >= cfg.hw_min_days else None
        return (lambda t: max(model.predict(t), 0.0)) if model else None
    if method == "TSB":
        model = tsb_build(obs, cfg)
        return (lambda t: model.value) if model else None
    raise ValueError(method)


# ---------------- đánh giá gốc trượt ----------------

def _next_open(series, start_idx, h_max):
    """Chỉ số các ngày học được kế tiếp sau start_idx, tối đa h_max ngày, dừng trước ngày bị bỏ qua (cửa sổ chứa ngày
    bị bỏ qua không được dùng để đo sai số)."""
    out, j = [], start_idx + 1
    while len(out) < h_max and j < len(series):
        st = series[j][2]
        if st == "bo_qua":
            break
        if st == "ok":
            out.append(j)
        j += 1
    return out


def hw_eval_params(series, cfg=DEFAULT, lookback=None):
    """(tham số HW, ngày bắt đầu được đánh giá): tham số chọn chỉ trên dữ liệu trước gốc đánh giá đầu tiên (hoặc trên
    cfg.hw_min_days ngày học được đầu tiên nếu dữ liệu trước đó chưa đủ); gốc chỉ được đánh giá từ khi đã có đủ số
    ngày đó. None nếu chuỗi chưa đủ dữ liệu cho HW."""
    if not series:
        return None, None
    first_origin = series[-1][0] - timedelta(days=lookback or cfg.lookback)
    obs = _obs(series)
    if len(obs) < cfg.hw_min_days:
        return None, None
    ready = obs[cfg.hw_min_days - 1][0]
    fit_end = max(ready, first_origin - timedelta(days=1))
    params = hw_fit([o for o in obs if o[0] <= fit_end], cfg)
    return params, max(ready, first_origin)


def rolling(series, method, cfg=DEFAULT, *, estimate=None, estimate_since=None, h_max=H_MAX, external=None,
            hw_params=None, keep=False, keep_days=None, lookback=None):
    """Sai số cửa sổ theo gốc trượt của một cách tính.

    estimate = (thấp, thường lệ, cao) theo tuần; estimate_since là ngày ước tính có hiệu lực (None: từ đầu chuỗi), M0
    chỉ có gốc từ ngày đó. external = {ngày gốc ISO: {ngày ISO: dự báo}} cho PH. keep=True thì giữ dự báo của mọi
    ngày không nghỉ trong keep_days ngày lịch sau mỗi gốc (để tính phân cấp từ dự báo tổng số ly), kể cả ngày bị bỏ
    qua khi đo sai số.

    Trả {"origins": [(ngày gốc, {h: (tổng thực, tổng dự báo)})], "by_h": {h: chỉ số}, "predictions": {...}}."""
    out = {"origins": [], "by_h": {}, "predictions": {}}
    if not series or (method == "M0" and not estimate) or (method == "PH" and external is None):
        return out
    first_origin = series[-1][0] - timedelta(days=lookback or cfg.lookback)
    hw = tsb = None
    start_at = first_origin
    if method == "HW":
        params, start_at = (hw_params, None) if hw_params else hw_eval_params(series, cfg, lookback)
        if params is None:
            return out
        if start_at is None:
            obs = _obs(series)
            if len(obs) < cfg.hw_min_days:
                return out
            start_at = max(obs[cfg.hw_min_days - 1][0], first_origin)
        seen = []
    elif method == "TSB":
        seen = []
    origins = []
    for idx, (d, x, st) in enumerate(series):
        if method == "HW" and st == "ok":
            seen.append((d, x))
            if hw is None:
                if len(seen) >= 7:
                    hw = hw_build(seen, params, cfg)
            else:
                hw.update(d, x)
        elif method == "TSB" and st == "ok":
            seen.append((d, x))
            if tsb is None:
                tsb = tsb_build(seen, cfg)
            else:
                tsb.update(x)
        if d < start_at:
            continue
        if method == "M0":
            if estimate_since is not None and d < estimate_since:
                continue
            past = series[max(0, idx - 56):idx + 1]
            owner = OwnerEstimate(*estimate, weekday_profile(past, d + timedelta(days=1)))
            predict = owner.mean
        elif method == "LN":
            table = ln_table(series[max(0, idx - 70):idx + 1], d, cfg)
            if table is None:
                continue
            predict = lambda t, table=table: table[is_weekend(t)]  # noqa: E731
        elif method == "WMA":
            table = wma_table(series[max(0, idx - 70):idx + 1], d, cfg)
            if table is None:
                continue
            predict = lambda t, table=table: table[t.weekday()]  # noqa: E731
        elif method == "HW":
            if hw is None:
                continue
            snap = (hw.level, hw.trend, list(hw.season), hw.last)
            predict = lambda t, s=snap, m=hw: max(  # noqa: E731
                s[0] + m._damp((t - s[3]).days) * s[1] + s[2][t.weekday()], 0.0)
        elif method == "TSB":
            if tsb is None:
                continue
            predict = lambda t, v=tsb.value: v  # noqa: E731
        elif method == "PH":
            table = external.get(d.isoformat())
            if table is None:
                continue
            predict = lambda t, table=table: table.get(t.isoformat(), 0.0)  # noqa: E731
        else:
            raise ValueError(method)
        nxt = _next_open(series, idx, h_max)
        sums, acc_a, acc_f = {}, 0.0, 0.0
        for h, j in enumerate(nxt, start=1):
            f = predict(series[j][0])
            acc_a += series[j][1]
            acc_f += f
            sums[h] = (acc_a, acc_f)
        if sums:
            origins.append((d, sums))
        if keep:
            ahead = series[idx + 1:idx + 1 + (keep_days or h_max + 7)]
            kept = {t.isoformat(): predict(t) for t, _, st in ahead if st != "dong_cua"}
            if kept:
                out["predictions"][d.isoformat()] = kept
    out["origins"] = origins
    out["by_h"] = summarize(origins, h_max)
    return out


def summarize(origins, h_max=H_MONTH):
    """Theo h: RMSE, MAE, WAPE, độ chệch (trung bình thực − dự báo), số gốc và danh sách sai số."""
    out = {}
    for h in range(1, h_max + 1):
        pairs = [s[h] for _, s in origins if h in s]
        if not pairs:
            continue
        es = [a - f for a, f in pairs]
        actual = sum(a for a, _ in pairs)
        abs_sum = sum(abs(e) for e in es)
        out[h] = {"rmse": math.sqrt(sum(e * e for e in es) / len(es)), "mae": abs_sum / len(es),
                  "wape": abs_sum / actual if actual > 0 else None, "bias": sum(es) / len(es), "n": len(es),
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


def _recent_gain(inc_origins, new_origins, h, days):
    """Mức giảm MAE của cách tính mới so với cách đang dùng trên cùng các gốc trong `days` ngày gần nhất; None nếu
    các gốc chung chưa trải đủ `days` ngày."""
    a = {d: s[h][0] - s[h][1] for d, s in inc_origins if h in s}
    b = {d: s[h][0] - s[h][1] for d, s in new_origins if h in s}
    common = sorted(set(a) & set(b))
    if not common or (common[-1] - common[0]).days + 1 < days:
        return None
    cut = common[-1] - timedelta(days=days - 1)
    common = [d for d in common if d >= cut]
    ma = sum(abs(a[d]) for d in common) / len(common)
    mb = sum(abs(b[d]) for d in common) / len(common)
    return (ma - mb) / ma if ma > 0 else None


def _quantile_check(by_h, csl, cfg=DEFAULT):
    """Phân vị CSL của sai số cửa sổ (khi đủ cfg.quantile_min gốc) và độ phủ của phân vị nửa đầu trên nửa sau."""
    quantiles, cov = {}, {}
    for h, st in by_h.items():
        es = st["errors"]
        if len(es) < cfg.quantile_min:
            continue
        half = len(es) // 2
        cov[h] = coverage(es[half:], empirical_quantile(es[:half], csl / 100))
        quantiles[h] = empirical_quantile(es, csl / 100)
    return quantiles, cov


def _jsonable_errors(errors_by_method):
    def r(v):
        return None if v is None else round(v, 4 if abs(v) < 10 else 2)

    return {m: {str(h): {"rmse": r(v["rmse"]), "mae": r(v["mae"]), "wape": r(v["wape"]), "bias": r(v["bias"]),
                         "n": v["n"]}
                for h, v in by_h.items()} for m, by_h in errors_by_method.items()}


# ---------------- chọn cách tính và giai đoạn ----------------

def stage_default(eligible, cfg=DEFAULT, has_ph=False):
    """Cách mặc định của giai đoạn bước đầu: phân cấp nếu có; nếu không thì LN khi chưa đủ 4 tuần, WMA khi đủ."""
    if has_ph:
        return "PH"
    return "WMA" if eligible >= 28 else "LN"


def _forecast_series(series, *, today, horizon, cfg=DEFAULT, candidates=("WMA",), approved=None, estimate=None,
                    estimate_since=None, external=None, external_daily=None, default=None, decision_h=2,
                    target_h=None, csl=95, k=1.645, blocked_share=0.0, blocked_limit=0.2, hw_params=None):
    """Dự báo theo ngày từ hôm nay và sai số cửa sổ σ_h của một chuỗi, theo giai đoạn dữ liệu (mục 4.4).

    candidates: các cách được đánh giá ở giai đoạn đã đánh giá (M0 tự thêm khi có ước tính). approved: cách tính
    đang dùng đã được duyệt (hoặc đã tự chọn lần đầu); không đổi khi chưa được duyệt. external, external_daily: dự báo
    phân cấp tại từng gốc và từ hôm nay. decision_h, target_h: số ngày của cửa sổ kích hoạt và cửa sổ mục tiêu dùng để
    mua. Trả dict lưu được bằng JSON (ngày dạng ISO)."""
    eligible = sum(1 for _, _, st in series if st == "ok")
    profile = weekday_profile(series, today)
    prior = OwnerEstimate(*estimate, profile) if estimate else None
    days = [today + timedelta(days=j) for j in range(horizon)]
    warnings, errors_by_method = [], {}
    decision_h = max(1, decision_h)
    h_max = max(H_MAX, H_MONTH, decision_h, target_h or 0)
    has_ph = external_daily is not None
    default = default or stage_default(eligible, cfg, has_ph)
    if blocked_share > blocked_limit:
        warnings.append(f"{round(blocked_share * 100)}% số ngày trong 8 tuần bị chặn do hết hàng: dự báo có thể thấp"
                        + ("; dùng lại ước tính của Chủ quán." if prior else "."))
    out = {"eligible_days": eligible, "estimate": list(estimate) if estimate else None, "profile": profile,
           "warnings": warnings, "estimate_since": estimate_since.isoformat() if estimate_since else None,
           "demand_class": demand_class(series, series[-1][0], cfg) if series else None, "proposal": None,
           "approved": approved, "auto_pick": False}
    unmeasured = [False] * h_max

    def publish(method):
        pred = predictor(series, method, cfg, estimate=estimate, profile=profile, hw_params=hw_params,
                         external_daily=external_daily)
        return {d.isoformat(): max(pred(d), 0.0) for d in days} if pred else None

    if eligible < cfg.owner_days or (blocked_share > blocked_limit and prior):
        if prior:
            out.update(method="M0", stage=STAGE_OWNER, sigma=[prior.sigma(h) for h in range(1, h_max + 1)],
                       sigma_measured=unmeasured, sigma_label="theo khoảng của Chủ quán, chưa kiểm chứng",
                       provisional=True, daily={d.isoformat(): prior.mean(d) for d in days})
            return out
        daily = publish(default) if eligible >= 3 or has_ph else None
        if daily is None:
            out.update(method=None, stage=STAGE_OWNER, sigma=[], sigma_measured=[], sigma_label="", provisional=True,
                       daily={})
            warnings.append("Chưa có ước tính tuần của Chủ quán và chưa đủ dữ liệu bán để tính.")
            return out
        vals = [x for _, x, st in series if st == "ok"]
        sd = _sd(vals) if len(vals) > 1 else (sum(daily.values()) / max(len(daily), 1)) * 0.5
        warnings.append(f"Mới có {eligible} ngày dữ liệu và chưa có ước tính tuần của Chủ quán: số liệu rất tạm.")
        out.update(method=default, stage=STAGE_EARLY, sigma=[sd * math.sqrt(h) for h in range(1, h_max + 1)],
                   sigma_measured=unmeasured, sigma_label="ước lượng tạm, √h × σ1", provisional=True, daily=daily)
        return out
    if eligible < cfg.model_days:
        # Bước đầu: cách mặc định của giai đoạn, trộn với ước tính của Chủ quán theo số ngày đã có (càng nhiều dữ
        # liệu càng ít dựa vào ước tính). Sai số chỉ là ước lượng tạm √h × σ1.
        method = approved if approved in (*candidates, default) and approved != "HW" else default
        res = rolling(series, method, cfg, estimate=estimate, estimate_since=estimate_since, h_max=h_max,
                      external=external, hw_params=hw_params)
        errors_by_method[method] = res["by_h"]
        st1 = res["by_h"].get(1)
        sigma1 = st1["rmse"] if st1 and st1["n"] >= cfg.min_origins else None
        if not sigma1:
            sigma1 = _sd([x for _, x, st in series if st == "ok"])
        daily = publish(method) or {}
        weight = None
        if prior and (estimate_since is None or estimate_since <= today):
            weight = eligible / (eligible + cfg.prior_days)
            daily = {iso: weight * v + (1 - weight) * prior.mean(d) for (iso, v), d in zip(daily.items(), days)}
        out.update(method=method, stage=STAGE_EARLY, prior_weight=round(1 - weight, 3) if weight is not None else None,
                   sigma=[sigma1 * math.sqrt(h) for h in range(1, h_max + 1)], sigma_measured=unmeasured,
                   sigma_label="ước lượng tạm, √h × σ1", provisional=True, daily=daily,
                   errors=_jsonable_errors(errors_by_method))
        return out
    pool = list(dict.fromkeys([*candidates] + (["M0"] if prior else [])))
    if approved and approved not in pool and approved in METHOD_LABELS:
        pool.append(approved)
    results = {m: rolling(series, m, cfg, estimate=estimate, estimate_since=estimate_since, h_max=h_max,
                          external=external, hw_params=hw_params) for m in pool}
    for m, res in results.items():
        if res["by_h"]:
            errors_by_method[m] = res["by_h"]
    usable = []
    for m in pool:
        st = results[m]["by_h"].get(decision_h)
        if not st or st["n"] < cfg.min_origins:
            continue
        if abs(st["bias"]) > cfg.bias_limit * st["rmse"]:
            warnings.append(f"{METHOD_LABELS[m]} lệch hệ thống (độ chệch {st['bias']:.0f} so với σ {st['rmse']:.0f}); "
                            f"không dùng.")
            continue
        usable.append(m)
    if approved in usable:
        method = approved
    else:
        if approved:
            warnings.append(f"Cách tính đã duyệt ({METHOD_LABELS.get(approved, approved)}) chưa dùng được ở cửa sổ "
                            f"{decision_h} ngày; tạm chọn cách khác theo đánh giá.")
        if usable:
            method = min(usable, key=lambda m: results[m]["by_h"][decision_h]["mae"])
            out["auto_pick"] = True
        else:
            measured = [m for m in pool if (results[m]["by_h"].get(decision_h) or {}).get("n", 0) >= cfg.min_origins]
            if measured:
                method = min(measured, key=lambda m: abs(results[m]["by_h"][decision_h]["bias"])
                             / max(results[m]["by_h"][decision_h]["rmse"], 1e-9))
                warnings.append(f"Mọi cách tính đều lệch hệ thống; tạm dùng {METHOD_LABELS[method]} vì ít lệch nhất. "
                                f"Cần xem lại dữ liệu hoặc ước tính.")
            else:
                method = default
                warnings.append(f"Chưa đủ {cfg.min_origins} gốc đánh giá cho cửa sổ {decision_h} ngày; tạm dùng "
                                f"{METHOD_LABELS[default]}.")
            out["auto_pick"] = approved is None
    best = None
    for m in usable if approved and method == approved else ():
        # Chỉ so với cách đang dùng đã được chọn trước đó; lần tự chọn đầu tiên đã lấy cách tốt nhất.
        if m == method:
            continue
        gain = _recent_gain(results[method]["origins"], results[m]["origins"], decision_h, cfg.switch_days)
        if gain is not None and gain >= cfg.switch_gain and (best is None or gain > best[1]):
            best = (m, gain)
    if best:
        cur, new = results[method]["by_h"][decision_h], results[best[0]]["by_h"][decision_h]
        out["proposal"] = {"method": best[0], "from": method, "gain": round(best[1], 4), "h": decision_h,
                           "weeks": cfg.switch_days // 7, "mae_from": round(cur["mae"], 2),
                           "mae_to": round(new["mae"], 2)}
        if cfg.auto_switch:
            warnings.append(f"Chuyển sang {METHOD_LABELS[best[0]]}: MAE thấp hơn {best[1] * 100:.0f}% trong "
                            f"{cfg.switch_days // 7} tuần gần nhất.")
            method = best[0]
    by_h = results[method]["by_h"] if method in results else {}
    if not by_h:
        res = rolling(series, method, cfg, estimate=estimate, estimate_since=estimate_since, h_max=h_max,
                      external=external, hw_params=hw_params)
        by_h = res["by_h"]
        errors_by_method[method] = by_h
    sigma, flags = [], []
    base = (by_h.get(1) or {}).get("rmse") or _sd([x for _, x, st in series if st == "ok"])
    for h in range(1, h_max + 1):
        st = by_h.get(h)
        if st and st["n"] >= cfg.min_origins:
            sigma.append(st["rmse"])
            flags.append(True)
        else:
            # chưa đủ gốc: ước lượng tạm theo căn bậc hai, hiển thị rõ là tạm
            longest = max((g for g in range(1, h) if flags[g - 1]), default=None)
            sigma.append(sigma[longest - 1] * math.sqrt(h / longest) if longest else base * math.sqrt(h))
            flags.append(False)
    needed = [decision_h] + ([target_h] if target_h else [])
    provisional = not all(flags[h - 1] for h in needed)
    if not all(flags):
        short = [h for h, ok in enumerate(flags, start=1) if not ok]
        warnings.append(f"Sai số cửa sổ từ {short[0]} ngày chưa đủ {cfg.min_origins} gốc đánh giá; phần đó là ước lượng "
                        f"tạm.")
    quantiles, q_cov = _quantile_check(by_h, csl, cfg)
    out.update(method=method, stage=STAGE_MODEL, sigma=sigma, sigma_measured=flags, provisional=provisional,
               sigma_label="đo trực tiếp" if not provisional else "ước lượng tạm, √h × σ",
               daily=publish(method) or {}, errors=_jsonable_errors(errors_by_method),
               error_quantiles=quantiles, quantile_n={h: by_h[h]["n"] for h in quantiles}, quantile_coverage=q_cov,
               ksigma_coverage={h: coverage(by_h[h]["errors"], k * by_h[h]["rmse"]) for h in by_h})
    return out


def _sd(vals):
    if len(vals) < 2:
        return 0.0
    m = sum(vals) / len(vals)
    return math.sqrt(sum((x - m) ** 2 for x in vals) / (len(vals) - 1))


def residual_season_factor(percent, baseline, current):
    """Điều chỉnh mùa là mức thay đổi so với nền ngoài mùa. Phần mô hình đã học (dự báo hiện tại so với nền) được trừ
    đi, chỉ áp phần còn thiếu, và không vượt quá mức Chủ quán đặt cũng không đổi chiều. Mô hình đã thích nghi hoàn toàn
    thì hệ số về 1: không giảm hai lần.

    Ví dụ nền 100, Chủ quán đặt −15%: mô hình chưa học (dự báo 100) → 0,85; đã học hết (85) → 1; học một phần (92)
    → 0,85 / 0,92."""
    target = 1 + percent / 100
    if not baseline or baseline <= 0 or current is None or current <= 0:
        return target
    learned = current / baseline
    factor = target / learned
    lo, hi = (target, 1.0) if target <= 1 else (1.0, target)
    return min(max(factor, lo), hi)


def with_overrides(cfg, **kw):
    return replace(cfg, **kw)


def forecast_series(series, *, today, horizon, cfg=DEFAULT, candidates=("WMA",), approved=None, estimate=None,
                    estimate_since=None, external=None, external_daily=None, default=None, decision_h=2,
                    target_h=None, csl=95, k=1.645, blocked_share=0.0, blocked_limit=0.2, hw_params=None):
    out = _forecast_series(series, today=today, horizon=horizon, cfg=cfg, candidates=candidates,
                           approved=approved, estimate=estimate, estimate_since=estimate_since,
                           external=external, external_daily=external_daily, default=default,
                           decision_h=decision_h, target_h=target_h, csl=csl, k=k,
                           blocked_share=blocked_share, blocked_limit=blocked_limit, hw_params=hw_params)
    if approved and out.get("method") != approved and not cfg.auto_switch:
        candidate = out.get("method")
        out["warnings"] = [w.replace("tạm chọn cách khác theo đánh giá", "đề xuất cách khác, chờ duyệt")
                            .replace("tạm dùng", "ứng viên thay thế là") for w in out["warnings"]]
        out["auto_pick"] = False
        out["requires_approval"] = True
        out["fallback_candidate"] = candidate
        out["proposal"] = ({"method": candidate, "from": approved, "gain": 0, "h": decision_h,
                            "weeks": 0, "mae_from": None, "mae_to": None, "urgent": True,
                            "reason": "Cách đã duyệt không còn đủ điều kiện"} if candidate else None)
        # Do not publish another method under the old approval. Keep the approved method only if calculable.
        pred = predictor(series, approved, cfg, estimate=estimate, profile=weekday_profile(series, today),
                         hw_params=hw_params, external_daily=external_daily)
        out["method"] = approved if pred else None
        out["daily"] = { (today + timedelta(days=j)).isoformat(): max(pred(today + timedelta(days=j)), 0.0)
                         for j in range(horizon)} if pred else {}
        out["provisional"] = True
        out["sigma"] = []
        out["sigma_measured"] = []
        out["sigma_label"] = "Chờ duyệt phương án dự báo; không dùng sai số của cách thay thế"
        out["warnings"].append("Cách đã duyệt không còn đủ điều kiện. Chưa áp dụng cách thay thế; "
                               "Chủ quán cần xem xét đề xuất. Tạm dừng đề xuất mua tự động.")
    else:
        out["requires_approval"] = False
    return out
