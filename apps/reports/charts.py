"""Hình học biểu đồ SVG vẽ ở máy chủ cho bảng điều khiển (không cần thư viện hay mạng ngoài).

Theo kỹ năng dataviz: một trục, nét mảnh, khe 2px giữa các cột, nhãn chọn lọc, lưới mờ, chú giải khi
từ 2 chuỗi trở lên, mỗi cột có chú thích khi rê chuột hoặc chạm, và luôn có bảng số liệu đi kèm.
Màu chuỗi lấy từ bảng màu tham chiếu đã kiểm định của kỹ năng (ô 1 xanh #2a78d6, ô 2 cam #eb6834).
"""

import math

WIDTH, HEIGHT = 640, 220
PAD_L, PAD_R, PAD_T, PAD_B = 64, 12, 12, 28


def _nice_max(value):
    if value <= 0:
        return 1
    exp = 10 ** math.floor(math.log10(value))
    for step in (1, 2, 2.5, 5, 10):
        if value <= step * exp:
            return step * exp
    return 10 * exp


def _scale_top(peak):
    """Đỉnh trục chia đều 4 khoảng tròn (0, 10, 20, 30, 40), để vạch chia luôn là số chẵn dễ đọc."""
    return 4 * _nice_max(peak / 4) if peak > 0 else 4


def _fmt(value):
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}".rstrip("0").rstrip(".") + " tr"
    if value >= 1000:
        return f"{value / 1000:.0f} k"
    return f"{value:.0f}"


def columns(points):
    """points: [(nhãn trục, giá trị, chú thích)] → hình học biểu đồ cột một chuỗi."""
    if not points:
        return None
    top = _scale_top(max(v for _, v, _ in points))
    plot_w, plot_h = WIDTH - PAD_L - PAD_R, HEIGHT - PAD_T - PAD_B
    slot = plot_w / len(points)
    bar_w = max(min(slot - 2, 28), 2)  # khe 2px giữa các cột
    bars = []
    for i, (label, value, tip) in enumerate(points):
        h = 0 if top == 0 else value / top * plot_h
        x = PAD_L + i * slot + (slot - bar_w) / 2
        bars.append({"x": round(x, 1), "y": round(PAD_T + plot_h - h, 1), "w": round(bar_w, 1), "h": round(h, 1),
                     "label": label, "tip": tip, "show_label": len(points) <= 12 or i % math.ceil(len(points) / 12) == 0,
                     "lx": round(x + bar_w / 2, 1)})
    ticks = [{"y": round(PAD_T + plot_h - plot_h * k / 4, 1), "text": _fmt(top * k / 4)} for k in range(5)]
    return {"bars": bars, "ticks": ticks, "w": WIDTH, "h": HEIGHT, "x0": PAD_L, "x1": WIDTH - PAD_R,
            "base": PAD_T + plot_h, "label_y": HEIGHT - 8}


def hbars(rows, marker_key=None):
    """rows: [{"label", "value", "marker"?, "tip"}] → thanh ngang một chuỗi, có vạch mốc (mục tiêu, tồn an toàn)."""
    if not rows:
        return None
    peak = max(max(r["value"], (r.get(marker_key) or 0) if marker_key else 0) for r in rows)
    top = _scale_top(peak * 1.1)  # chừa khoảng để vạch mốc không chạm cột số
    label_w, plot_w, row_h = 150, 330, 30
    out = []
    for i, r in enumerate(rows):
        w = r["value"] / top * plot_w if top else 0
        marker = r.get(marker_key) if marker_key else None
        out.append({**r, "y": i * row_h + 6, "w": round(max(w, 0), 1),
                    "mx": round(label_w + marker / top * plot_w, 1) if marker else None})
    return {"rows": out, "w": label_w + plot_w + 90, "h": len(rows) * row_h + 8, "x0": label_w,
            "value_x": label_w + plot_w + 12}


def stacked(parts, target):
    """BO-01: một thanh xếp chồng (đã xác minh + đang xử lý) so với vạch mục tiêu."""
    total = sum(v for _, v, _ in parts)
    top = _nice_max(max(total, target) * 1.1)
    plot_w, x0 = 520, 8
    segs, x = [], x0
    for label, value, slot in parts:
        w = value / top * plot_w
        if w > 0:
            segs.append({"label": label, "value": value, "x": round(x, 1), "w": round(max(w - 2, 1), 1), "slot": slot,
                         "tip": f"{label}: {value:,} đ".replace(",", ".")})
        x += w
    return {"segs": segs, "target_x": round(x0 + target / top * plot_w, 1), "w": x0 + plot_w + 8, "h": 56,
            "total": total, "target": target}
