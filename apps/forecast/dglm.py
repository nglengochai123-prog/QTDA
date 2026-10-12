"""Mô hình Poisson động theo khung lý thuyết của dự án (West, Harrison và Migon 1985; West và Harrison 1997).

Số ly của một món-kích cỡ trong ngày t: y_t ~ Poisson(λ_t), log λ_t = F_t' θ_t với θ = (mức nền, hiệu ứng thứ
Ba … Chủ nhật so với thứ Hai làm ngày tham chiếu). Cập nhật tuần tự bằng suy luận Bayes tuyến tính của DGLM:
khớp phân phối của log λ với Gamma(α, β) (ψ(α) − log β = f, ψ'(α) = q), cập nhật liên hợp α+y, β+1 rồi
hồi chiếu về mô-men của trạng thái. Biến đổi trạng thái theo hệ số chiết khấu (mức nền δ_L, hiệu ứng thứ δ_S).

Chỉ dùng thư viện chuẩn để chạy được trên máy của quán mà không cài thêm gói.
"""

import math
import random

P = 7  # mức nền + 6 hiệu ứng thứ (thứ Hai là ngày tham chiếu, hiệu ứng bằng 0)


# ---------------- hàm đặc biệt ----------------

def digamma(x):
    result = 0.0
    while x < 6:
        result -= 1 / x
        x += 1
    f = 1 / (x * x)
    return result + math.log(x) - 0.5 / x - f * (1 / 12 - f * (1 / 120 - f * (1 / 252 - f * (1 / 240 - f / 132))))


def trigamma(x):
    result = 0.0
    while x < 6:
        result += 1 / (x * x)
        x += 1
    f = 1 / (x * x)
    return result + 1 / x + f / 2 + f / x * (1 / 6 - f * (1 / 30 - f * (1 / 42 - f / 30)))


def alpha_from_q(q):
    """Nghiệm α của ψ'(α) = q; ψ' giảm ngặt nên chia đôi trên log α là đủ chắc chắn."""
    q = max(q, 1e-9)
    lo, hi = math.log(1e-8), math.log(1e9)
    for _ in range(200):
        mid = (lo + hi) / 2
        if trigamma(math.exp(mid)) > q:
            lo = mid
        else:
            hi = mid
        if hi - lo < 1e-12:
            break
    return math.exp((lo + hi) / 2)


# ---------------- đại số tuyến tính nhỏ ----------------

def _matvec(A, v):
    return [sum(a * b for a, b in zip(row, v)) for row in A]


def _cholesky(A):
    n = len(A)
    L = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1):
            s = A[i][j] - sum(L[i][k] * L[j][k] for k in range(j))
            if i == j:
                L[i][j] = math.sqrt(max(s, 1e-12))
            else:
                L[i][j] = s / L[j][j]
    return L


def design(dow):
    """Véc-tơ F cho thứ trong tuần (0 = thứ Hai … 6 = Chủ nhật)."""
    f = [0.0] * P
    f[0] = 1.0
    if dow > 0:
        f[dow] = 1.0
    return f


# ---------------- tiên nghiệm từ nhận định Chủ quán ----------------

Z90 = 1.2815515655446004  # phân vị 90% của chuẩn tắc: khoảng 10%–90%


def gamma_from_judgement(typical, low, high, max_days):
    """Tiên nghiệm Gamma(a, b) cho cường độ một ngày từ mức điển hình và khoảng 80% số ly của MỘT ngày tương lai.

    Phân phối dự báo của Poisson-Gamma là nhị thức âm: trung bình μ = a/b, phương sai μ + μ²/a. Khớp phương sai
    với độ rộng khoảng Chủ quán đưa ra (mục 2.1 khung lý thuyết: khoảng mô tả số ly của một ngày tương lai, không
    phải bất định của mức trung bình). Khoảng hẹp đến mức gần Poisson nghĩa là rất chắc chắn; khi đó sức nặng bị
    giới hạn ở `max_days` ngày quan sát tương đương để không tạo độ chắc chắn giả.
    Trả (a, b, số ngày tương đương b, có bị giới hạn hay không).
    """
    mu = max(float(typical), 0.1)
    sigma = max(float(high) - float(low), 0.0) / (2 * Z90)
    extra = sigma * sigma - mu
    b = (mu / extra) if extra > 0 else float("inf")  # a = μ²/extra nên b = a/μ = μ/extra
    capped = b > max_days
    if capped:
        b = float(max_days)
    return b * mu, b, b, capped


def prior_state(weekday, weekend):
    """Trạng thái ban đầu (m, C) từ tiên nghiệm Gamma của ngày thường và cuối tuần.

    Mức nền mang thông tin ngày thường; hiệu ứng thứ Bảy, Chủ nhật có kỳ vọng bằng chênh lệch log giữa hai loại
    ngày; các ngày thường khác thứ Hai có kỳ vọng 0. Phương sai lấy từ ψ' của tiên nghiệm tương ứng.
    """
    a_wd, b_wd = weekday
    a_we, b_we = weekend
    f_wd, q_wd = digamma(a_wd) - math.log(b_wd), trigamma(a_wd)
    f_we, q_we = digamma(a_we) - math.log(b_we), trigamma(a_we)
    m = [f_wd] + [0.0] * 4 + [f_we - f_wd] * 2
    C = [[0.0] * P for _ in range(P)]
    C[0][0] = q_wd
    for d in range(1, 5):
        C[d][d] = q_wd
    for d in (5, 6):
        C[d][d] = q_we
    return m, C


# ---------------- mô hình ----------------

class PoissonDGLM:
    def __init__(self, m, C, delta_level, delta_season):
        self.m = list(m)
        self.C = [list(r) for r in C]
        self.dl = delta_level
        self.ds = delta_season

    def copy(self):
        return PoissonDGLM(self.m, self.C, self.dl, self.ds)

    def _evolve(self):
        """R = C + W, W theo chiết khấu từng khối (mức nền, hiệu ứng thứ)."""
        R = [list(r) for r in self.C]
        R[0][0] += self.C[0][0] * (1 / self.dl - 1)
        for i in range(1, P):
            for j in range(1, P):
                R[i][j] += self.C[i][j] * (1 / self.ds - 1)
        return R

    def predictive(self, dow, R=None):
        """(α, β) của Gamma khớp với log λ ngày tới có thứ `dow`; dự báo một ngày là nhị thức âm(α, β)."""
        R = R or self._evolve()
        F = design(dow)
        RF = _matvec(R, F)
        f = sum(a * b for a, b in zip(F, self.m))
        q = max(sum(a * b for a, b in zip(F, RF)), 1e-9)
        alpha = alpha_from_q(q)
        beta = math.exp(digamma(alpha) - f)
        return alpha, beta, f, q, R, RF

    def update(self, y, dow):
        alpha, beta, f, q, R, RF = self.predictive(dow)
        a2, b2 = alpha + y, beta + 1
        f2, q2 = digamma(a2) - math.log(b2), trigamma(a2)
        self.m = [m + rf * (f2 - f) / q for m, rf in zip(self.m, RF)]
        shrink = (1 - q2 / q) / q
        self.C = [[R[i][j] - RF[i] * RF[j] * shrink for j in range(P)] for i in range(P)]
        return alpha, beta

    def skip(self):
        """Ngày không đủ điều kiện (đóng cửa, chưa chốt, thiếu hàng): chỉ biến đổi trạng thái, không cập nhật."""
        self.C = self._evolve()

    def ahead(self, dows):
        """Phân phối từng ngày trong các ngày tới (không cập nhật): [(α, β), ...] cho ngày 1..h."""
        model = self.copy()
        out = []
        for dow in dows:
            alpha, beta, f, q, R, RF = model.predictive(dow)
            out.append((alpha, beta))
            model.C = R  # bất định trạng thái tăng dần theo thời hạn
        return out

    def simulate(self, dows, n, rng):
        """Các đường mô phỏng nhất quán qua nhiều ngày: list n đường, mỗi đường là số ly từng ngày."""
        L = _cholesky(self.C)
        w_level = self.C[0][0] * (1 / self.dl - 1)
        paths = []
        for _ in range(n):
            z = [rng.gauss(0, 1) for _ in range(P)]
            theta = [mi + sum(L[i][k] * z[k] for k in range(i + 1)) for i, mi in enumerate(self.m)]
            path = []
            for dow in dows:
                theta[0] += rng.gauss(0, math.sqrt(max(w_level, 0)))
                eta = theta[0] + (theta[dow] if dow > 0 else 0.0)
                path.append(poisson(math.exp(min(eta, 12)), rng))
            paths.append(path)
        return paths


# ---------------- phân phối nhị thức âm (dự báo một ngày) ----------------

def nb_pmf_list(alpha, beta, upto):
    """P(Y = k) với Y ~ Poisson(λ), λ ~ Gamma(α, β), k = 0..upto."""
    p = beta / (1 + beta)
    pmf = [math.exp(alpha * math.log(p))]
    for k in range(1, upto + 1):
        pmf.append(pmf[-1] * (alpha + k - 1) / k * (1 - p))
    return pmf


def nb_summary(alpha, beta, probs=(0.1, 0.5, 0.9)):
    mean = alpha / beta
    upto = int(mean + 12 * math.sqrt(mean + mean * mean / alpha) + 20)
    pmf = nb_pmf_list(alpha, beta, upto)
    out, acc, k = [], 0.0, 0
    targets = list(probs)
    for k, pk in enumerate(pmf):
        acc += pk
        while targets and acc >= targets[0]:
            out.append(k)
            targets.pop(0)
    while targets:
        out.append(upto)
        targets.pop(0)
    return mean, out


def crps_discrete(pmf, y):
    """CRPS của phân phối rời rạc trên 0..K với quan sát y: Σ_k (F(k) − 1{y ≤ k})² (Gneiting và Raftery 2007)."""
    total, cdf = 0.0, 0.0
    for k, pk in enumerate(pmf):
        cdf += pk
        total += (cdf - (1.0 if y <= k else 0.0)) ** 2
    if y >= len(pmf):  # quan sát nằm ngoài phần đuôi đã tính: mỗi bước còn lại đóng góp (F − 0)²
        total += (y - len(pmf)) * cdf * cdf
    return total


def poisson_pmf_list(lam, upto):
    lam = max(lam, 1e-9)
    pmf = [math.exp(-lam)]
    for k in range(1, upto + 1):
        pmf.append(pmf[-1] * lam / k)
    return pmf


# ---------------- lấy mẫu Poisson (Hörmann 1993, PTRS) ----------------

def poisson(lam, rng):
    if lam < 10:
        L, k, p = math.exp(-lam), 0, 1.0
        while True:
            p *= rng.random()
            if p <= L:
                return k
            k += 1
    slam, loglam = math.sqrt(lam), math.log(lam)
    b = 0.931 + 2.53 * slam
    a = -0.059 + 0.02483 * b
    inv_alpha = 1.1239 + 1.1328 / (b - 3.4)
    vr = 0.9277 - 3.6224 / (b - 2)
    while True:
        u = rng.random() - 0.5
        v = rng.random()
        us = 0.5 - abs(u)
        k = math.floor((2 * a / us + b) * u + lam + 0.43)
        if us >= 0.07 and v <= vr:
            return int(k)
        if k < 0 or (us < 0.013 and v > us):
            continue
        if (math.log(v) + math.log(inv_alpha) - math.log(a / (us * us) + b)
                <= -lam + k * loglam - math.lgamma(k + 1)):
            return int(k)


def quantile(sorted_values, p):
    if not sorted_values:
        return 0
    i = min(len(sorted_values) - 1, max(0, int(math.ceil(p * len(sorted_values))) - 1))
    return sorted_values[i]


def make_rng(*parts):
    return random.Random("|".join(str(p) for p in parts))
