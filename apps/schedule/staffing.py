"""Tính số người cần theo hàng đợi và chia số người cho các ca (FR-37, BRU-28, BRU-30).

Quy trình lập lịch nhân sự dịch vụ thường dùng (Thompson 1998; Ernst và cộng sự 2004):
1. Dự báo tải từng giờ: số ly dự báo của ngày × tỷ lệ bán theo giờ × hệ số tải bình quân mỗi ly.
2. Số người cần từng giờ theo mô hình hàng đợi nhiều người phục vụ M/M/c (Erlang C), hiệu chỉnh độ biến động theo
   Allen–Cunneen vì đơn đến theo nhóm nhiều ly và thời gian pha không đều. Mỗi giờ tính như một hàng đợi dừng
   (xấp xỉ SIPP của Green, Kolesar và Soares 2001, hợp khi thời gian pha vài phút so với khung một giờ).
3. Chia vào các ca Chủ quán khai báo bằng bài toán phủ tập hợp (Dantzig 1954): chọn số người mỗi ca để mọi giờ đủ
   người, tổng giờ công nhỏ nhất. Ca chồng nhau không bị đếm hai lần như cách lấy giờ cao nhất của từng ca.

Vì sao không chia thẳng tải cho năng suất: làm tròn lên tải ÷ năng suất cho phép người làm tới 100% công suất, khi đó
hàng chờ dài ra không giới hạn ở giờ cao điểm; còn năng suất học bằng trung vị tải mỗi người ở giờ không quá tải lại
gồm cả thời gian rảnh, nên thấp hơn sức làm thật và gợi ý thừa người. Erlang C giữ được cả hai: biết sức làm thật
và biết cần dư bao nhiêu để khách không chờ quá chuẩn.

Hàm thuần, không đọc cơ sở dữ liệu.
"""

import math
from itertools import product

# ---------------- hàng đợi ----------------


def erlang_c(c, a):
    """Xác suất phải chờ của M/M/c với tải a = λ/μ (Erlang); 1 khi c ≤ a (hàng đợi không ổn định)."""
    if c <= 0 or a >= c:
        return 1.0
    if a <= 0:
        return 0.0
    # Tính Erlang B theo truy hồi cho ổn định số, rồi đổi sang Erlang C.
    b = 1.0
    for k in range(1, c + 1):
        b = a * b / (k + a * b)
    rho = a / c
    return b / (1 - rho + rho * b)


def wait_ok_probability(c, lam, mu, t, scv=1.0):
    """P(thời gian chờ trong hàng ≤ t) của hàng đợi c người, λ việc/giờ, μ việc/giờ mỗi người, t giờ.

    scv: bình phương hệ số biến thiên trung bình của khoảng đến và thời gian phục vụ ((c²a + c²s) / 2, Allen–Cunneen);
    1 là M/M/c. Đuôi chờ được kéo dài theo scv."""
    if lam <= 0:
        return 1.0
    a = lam / mu
    if c <= a:
        return 0.0
    pw = erlang_c(c, a)
    return 1 - pw * math.exp(-(c * mu - lam) * t / max(scv, 1e-9))


def servers_needed(lam, mu, t, target, scv=1.0, minimum=0, max_servers=20):
    """Số người nhỏ nhất để P(chờ ≤ t) ≥ target; không thấp hơn minimum."""
    if lam <= 0:
        return minimum
    c = max(minimum, 1, math.floor(lam / mu) + 1)
    while c < max_servers and wait_ok_probability(c, lam, mu, t, scv) < target:
        c += 1
    return c


def hourly_needs(loads, rate, wait_min, target, scv, minimum, hours):
    """Số người cần từng giờ mở cửa: nhỏ nhất để P(chờ trong hàng ≤ wait_min phút) ≥ target, không dưới minimum.

    loads: {giờ: tải dự kiến}; rate: sức làm mỗi người mỗi giờ (cùng đơn vị tải); hours: các giờ mở cửa."""
    return {h: servers_needed(loads.get(h, 0), rate, wait_min / 60, target, scv, minimum) for h in hours}


def staff_shifts(loads, rate, wait_min, target, scv, minimum, hours, shifts):
    """Cả quy trình cho một vị trí trong một ngày: số người từng giờ rồi chia vào ca.

    Trả (số người mỗi ca, số người cần từng giờ, các giờ không ca nào phủ)."""
    need = hourly_needs(loads, rate, wait_min, target, scv, minimum, hours)
    x, uncovered = cover_shifts(shifts, need)
    return x, need, uncovered


def batch_scv(sizes):
    """c²a của dòng ly khi đơn đến theo Poisson và mỗi đơn có B ly: E[B²]/E[B] (chỉ số phân tán của quá trình nhóm).

    sizes: {số ly trong đơn: tỷ lệ}."""
    total = sum(sizes.values())
    if not total:
        return 1.0
    m1 = sum(k * p for k, p in sizes.items()) / total
    m2 = sum(k * k * p for k, p in sizes.items()) / total
    return m2 / m1 if m1 else 1.0


# ---------------- chia vào ca ----------------


SEARCH_LIMIT = 200_000  # quá số tổ hợp này (nhiều ca chồng nhau trong một ngày) thì dùng cách tham lam


def covers(shift, hour):
    """Ca (giờ bắt đầu, giờ kết thúc, tính bằng giờ thập phân) có mặt trong khung [hour, hour+1) ít nhất nửa khung."""
    start, end = shift
    return min(end, hour + 1) - max(start, hour) >= 0.5 - 1e-9


def cover_shifts(shifts, need, max_each=None):
    """Bài toán phủ: số người x mỗi ca để Σ x của các ca có mặt trong giờ h ≥ need[h], tổng giờ công nhỏ nhất.

    shifts: [(bắt đầu, kết thúc)]; need: {giờ: số người}. Duyệt hết vì mỗi ngày chỉ vài ca và vài người; hòa thì chọn
    ít người hơn, rồi ít dư hơn. Trả (x theo thứ tự ca, các giờ không ca nào phủ được)."""
    hours = [h for h, n in need.items() if n > 0]
    uncovered = [h for h in hours if not any(covers(s, h) for s in shifts)]
    hours = [h for h in hours if h not in uncovered]
    if not shifts:
        return [], uncovered
    top = max((need[h] for h in hours), default=0)
    limits = []
    for s in shifts:
        own = [need[h] for h in hours if covers(s, h)]
        limits.append(min(max(own, default=0), max_each if max_each is not None else top))
    if math.prod(lim + 1 for lim in limits) > SEARCH_LIMIT:
        return _cover_greedy(shifts, need, hours), uncovered
    best, best_key = None, None
    for x in product(*[range(lim + 1) for lim in limits]):
        ok = True
        surplus = 0
        for h in hours:
            have = sum(xi for xi, s in zip(x, shifts) if covers(s, h))
            if have < need[h]:
                ok = False
                break
            surplus += have - need[h]
        if not ok:
            continue
        hours_used = sum(xi * (s[1] - s[0]) for xi, s in zip(x, shifts))
        key = (round(hours_used, 6), sum(x), surplus)
        if best_key is None or key < best_key:
            best, best_key = list(x), key
    return best or [0] * len(shifts), uncovered


def _cover_greedy(shifts, need, hours):
    """Phủ tham lam khi quá nhiều ca để duyệt hết: mỗi bước thêm một người vào ca bù được nhiều giờ thiếu nhất trên mỗi
    giờ công, rồi bỏ bớt người thừa ở ca dài trước. Không bảo đảm nhỏ nhất nhưng luôn đủ người."""
    x = [0] * len(shifts)

    def short():
        return {h: need[h] - sum(xi for xi, s in zip(x, shifts) if covers(s, h)) for h in hours}

    gap = short()
    while any(v > 0 for v in gap.values()):
        gain = [sum(1 for h in hours if gap[h] > 0 and covers(s, h)) / max(s[1] - s[0], 1e-9) for s in shifts]
        x[max(range(len(shifts)), key=lambda i: gain[i])] += 1
        gap = short()
    for i in sorted(range(len(shifts)), key=lambda i: shifts[i][0] - shifts[i][1]):
        while x[i] > 0:
            x[i] -= 1
            if any(v > 0 for v in short().values()):
                x[i] += 1
                break
    return x


def peak_per_shift(shifts, need):
    """Cách cũ: mỗi ca lấy số người của giờ cao nhất trong ca, các ca tính riêng."""
    return [max((n for h, n in need.items() if covers(s, h)), default=0) for s in shifts]


# ---------------- ước lượng sức làm từ dữ liệu ----------------


def saturated_rate(events):
    """Sức làm mỗi người mỗi giờ khi mọi người đều bận (thông lượng lúc bão hòa).

    events: [(thời điểm giờ thập phân, 'gui' | 'xong', tải, số người có mặt lúc đó[, số ly])], đã sắp theo thời gian
    (cùng thời điểm thì 'xong' trước 'gui'). Số ly mặc định 1; dữ liệu thật ghi theo dòng món nên một dòng có thể nhiều ly.
    Trong khoảng có ít nhất c ly đang chờ hoặc đang pha với c người có mặt, mọi người đều bận; tải pha xong trong các
    khoảng đó chia cho số giờ-người bận là sức làm. Trả (sức làm, số giờ-người bận) hoặc (None, 0)."""
    pending, last_t, last_c = 0, None, 0
    busy_hours, done_load = 0.0, 0.0
    for t, kind, load, c, *rest in events:
        n = rest[0] if rest else 1
        if last_t is not None and last_c > 0 and pending >= last_c:
            busy_hours += (t - last_t) * last_c
        if kind == "gui":
            pending += n
        else:
            if last_c > 0 and pending >= last_c:
                done_load += load
            pending = max(pending - n, 0)
        last_t, last_c = t, c
    if busy_hours <= 0:
        return None, 0.0
    return done_load / busy_hours, busy_hours
