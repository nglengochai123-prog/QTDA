"""Hình học biểu đồ SVG vẽ ở máy chủ (không cần thư viện hay mạng ngoài), dùng chung cho mọi báo cáo.

Theo kỹ năng dataviz: một trục, nét mảnh (đường 2px, cột tối đa 24px, đầu cột bo 4px và vuông ở đường gốc), khe 2px
giữa các mảng, nhãn chọn lọc, lưới mờ nét liền, chú giải khi từ 2 chuỗi trở lên, mỗi phần tử có chú thích khi rê
chuột hoặc chạm, và luôn có bảng số liệu đi kèm. Màu chuỗi theo thứ tự cố định của bảng màu tham chiếu đã kiểm định
(ô 1 xanh, ô 2 cam, ô 3 xanh ngọc; nền trắng: đạt mọi ngưỡng, ô 3 dưới 3:1 nên luôn có nhãn hoặc bảng số liệu).
Thang tuần tự một màu xanh, nhạt tới đậm. Màu trạng thái (tốt, cảnh báo, nghiêm trọng) chỉ dùng cho trạng thái.

Mỗi hàm trả về dict hình học; mẫu ở templates/reports/charts/ vẽ thành SVG.
"""

import math
from datetime import timedelta

WIDTH = 640
# Bề rộng hệ tọa độ theo chỗ đặt, để chữ 11–12px trong SVG hiện gần đúng cỡ đó trên màn hình máy tính:
# thẻ chiếm cả hàng, thẻ nửa hàng (grid-2), thẻ một phần ba hàng (grid-3).
WIDE, HALF, THIRD = 1080, 540, 360
SEQ = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]  # thang tuần tự xanh


def nice_max(value):
    if value <= 0:
        return 1
    exp = 10 ** math.floor(math.log10(value))
    for step in (1, 2, 2.5, 5, 10):
        if value <= step * exp:
            return step * exp
    return 10 * exp


def _scale_top(peak):
    """Đỉnh trục chia đều 4 khoảng tròn (0, 10, 20, 30, 40), để vạch chia luôn là số dễ đọc."""
    return 4 * nice_max(peak / 4) if peak > 0 else 4


def fmt(value):
    """Số gọn cho trục và nhãn: 1,2 tr; 35 k; 820."""
    value = float(value or 0)
    sign = "−" if value < 0 else ""
    value = abs(value)
    if value >= 1_000_000:
        return sign + f"{value / 1_000_000:.1f}".rstrip("0").rstrip(".").replace(".", ",") + " tr"
    if value >= 10_000:
        return sign + f"{value / 1000:.0f} k"
    if value >= 1000:
        return sign + f"{value / 1000:.1f}".rstrip("0").rstrip(".").replace(".", ",") + " k"
    if value != int(value):
        return sign + f"{value:.1f}".replace(".", ",")
    return sign + f"{value:.0f}"


def _column_path(x, y, w, h, r=4):
    """Cột đứng bo 4px ở đầu, vuông ở đường gốc."""
    if h <= 0 or w <= 0:
        return ""
    r = min(r, w / 2, h)
    return (f"M{x:.1f},{y + h:.1f}V{y + r:.1f}Q{x:.1f},{y:.1f} {x + r:.1f},{y:.1f}H{x + w - r:.1f}"
            f"Q{x + w:.1f},{y:.1f} {x + w:.1f},{y + r:.1f}V{y + h:.1f}Z")


def _bar_path(x, y, w, h, r=4):
    """Thanh ngang bo 4px ở đầu phải, vuông ở đường gốc bên trái."""
    if h <= 0 or w <= 0:
        return ""
    r = min(r, h / 2, w)
    return (f"M{x:.1f},{y:.1f}H{x + w - r:.1f}Q{x + w:.1f},{y:.1f} {x + w:.1f},{y + r:.1f}V{y + h - r:.1f}"
            f"Q{x + w:.1f},{y + h:.1f} {x + w - r:.1f},{y + h:.1f}H{x:.1f}Z")


def _ticks(top, y0, plot_h, n=4, formatter=fmt):
    return [{"y": round(y0 + plot_h - plot_h * k / n, 1), "text": formatter(top * k / n)} for k in range(n + 1)]


def _label_every(n, room=12):
    return max(1, math.ceil(n / room))


def _room(plot_w, label_px=44):
    """Số nhãn trục x vừa bề rộng vẽ, mỗi nhãn ngày dạng dd/mm cần khoảng 44px."""
    return max(2, int(plot_w // label_px))


def _show_labels(n, every):
    """Nhãn thứ 0, every, 2·every... và luôn nhãn cuối; bỏ nhãn đều đặn nằm quá sát nhãn cuối để khỏi chồng chữ."""
    shown = {i for i in range(0, n, every) if n - 1 - i >= max(every * 0.6, 1) or i == n - 1}
    shown.add(n - 1)
    return shown


# ---------------- Cột một chuỗi ----------------

def columns(points, height=220, highlight=None, width=WIDTH, value_fmt=fmt):
    """points: [(nhãn trục, giá trị, chú thích)]. highlight: tập chỉ số cột nhấn (cột còn lại màu nền nhạt)."""
    if not points:
        return None
    pad_l, pad_r, pad_t, pad_b = 52, 8, 12, 26
    top = _scale_top(max(v for _, v, _ in points))
    plot_w, plot_h = width - pad_l - pad_r, height - pad_t - pad_b
    slot = plot_w / len(points)
    bar_w = max(min(slot - 2, 28 if width >= WIDE else 24), 2)
    every = _label_every(len(points), _room(plot_w, 36))
    bars = []
    for i, (label, value, tip) in enumerate(points):
        h = 0 if top == 0 else max(value, 0) / top * plot_h
        x = pad_l + i * slot + (slot - bar_w) / 2
        bars.append({"d": _column_path(x, pad_t + plot_h - h, bar_w, h), "label": label, "tip": tip,
                     "muted": highlight is not None and i not in highlight,
                     "show_label": i % every == 0, "lx": round(x + bar_w / 2, 1),
                     "hx": round(pad_l + i * slot, 1), "hw": round(slot, 1)})
    return {"bars": bars, "ticks": _ticks(top, pad_t, plot_h, formatter=value_fmt), "w": width, "h": height,
            "x0": pad_l, "x1": width - pad_r, "base": pad_t + plot_h, "label_y": height - 8, "top": pad_t,
            "plot_h": plot_h}


# ---------------- Cột chồng nhiều chuỗi ----------------

def stacked_columns(labels, series, height=230, tips=None, value_fmt=fmt, width=WIDTH):
    """labels: nhãn trục x; series: [{"name", "values", "slot"}] (slot 1..3 hoặc "muted"); tối đa 4 chuỗi."""
    if not labels or not series:
        return None
    pad_l, pad_r, pad_t, pad_b = 52, 8, 12, 26
    totals = [sum(max(s["values"][i] or 0, 0) for s in series) for i in range(len(labels))]
    if not any(totals):
        return None
    top = _scale_top(max(totals))
    plot_w, plot_h = width - pad_l - pad_r, height - pad_t - pad_b
    slot = plot_w / len(labels)
    bar_w = max(min(slot - 2, 28 if width >= WIDE else 24), 2)
    every = _label_every(len(labels), _room(plot_w))
    cols = []
    for i, label in enumerate(labels):
        x = pad_l + i * slot + (slot - bar_w) / 2
        y = pad_t + plot_h
        segs = []
        nonzero = [s for s in series if (s["values"][i] or 0) > 0]
        for s in nonzero:
            v = s["values"][i]
            h = v / top * plot_h
            last = s is nonzero[-1]
            gap = 0 if last else 2  # khe 2px màu nền giữa các mảng
            seg_h = max(h - gap, 0.5)
            y -= h
            d = _column_path(x, y + gap, bar_w, seg_h, 4 if last else 0)
            segs.append({"d": d, "slot": s.get("slot", 1)})
        tip = (tips[i] if tips else f"{label}: " + " · ".join(f"{s['name']} {value_fmt(s['values'][i] or 0)}"
                                                              for s in series))
        cols.append({"segs": segs, "label": label, "show_label": i % every == 0, "lx": round(x + bar_w / 2, 1),
                     "hx": round(pad_l + i * slot, 1), "hw": round(slot, 1), "tip": tip})
    return {"cols": cols, "ticks": _ticks(top, pad_t, plot_h, formatter=value_fmt), "w": width, "h": height,
            "x0": pad_l, "x1": width - pad_r, "base": pad_t + plot_h, "label_y": height - 8, "top": pad_t, "plot_h": plot_h,
            "legend": [{"name": s["name"], "slot": s.get("slot", 1)} for s in series]}


# ---------------- Đường (xu hướng theo thời gian) ----------------

def line(labels, series, height=230, value_fmt=fmt, tip_labels=None, floor_zero=True, width=WIDTH):
    """series: [{"name", "values" (None = không có số), "slot" (1..3 hoặc "muted"), "area": bool, "label_end": bool}].

    Một trục y. Mỗi vị trí x có một vùng chạm cao hết biểu đồ, chú thích liệt kê mọi chuỗi tại vị trí đó."""
    if not labels or not series:
        return None
    vals = [v for s in series for v in s["values"] if v is not None]
    if not vals:
        return None
    pad_l, pad_r, pad_t, pad_b = 52, 56, 14, 26
    low = 0 if floor_zero else min(vals)
    top = _scale_top(max(vals) - low) + low if not floor_zero else _scale_top(max(vals))
    plot_w, plot_h = width - pad_l - pad_r, height - pad_t - pad_b
    n = len(labels)
    step = plot_w / max(n - 1, 1)

    def xy(i, v):
        return pad_l + i * step, pad_t + plot_h - (v - low) / ((top - low) or 1) * plot_h

    out = []
    for s in series:
        pts = [(i, v) for i, v in enumerate(s["values"]) if v is not None]
        if not pts:
            continue
        coords = [xy(i, v) for i, v in pts]
        d = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in coords)
        area = None
        if s.get("area"):
            area = d + f" L{coords[-1][0]:.1f},{pad_t + plot_h:.1f} L{coords[0][0]:.1f},{pad_t + plot_h:.1f} Z"
        end_x, end_y = coords[-1]
        out.append({"d": d, "area": area, "slot": s.get("slot", 1), "name": s["name"],
                    "end": {"x": round(end_x, 1), "y": round(end_y, 1), "text": value_fmt(pts[-1][1])}
                    if s.get("label_end", True) else None})
    shown = _show_labels(n, _label_every(n, _room(plot_w)))
    hits = []
    for i, label in enumerate(labels):
        x = pad_l + i * step
        parts = [f"{s['name']} {value_fmt(s['values'][i])}" for s in series if s["values"][i] is not None]
        hits.append({"x": round(x - step / 2, 1), "w": round(step, 1), "cx": round(x, 1),
                     "tip": f"{(tip_labels or labels)[i]}: " + " · ".join(parts),
                     "label": label, "show_label": i in shown})
    ticks = [{"y": round(pad_t + plot_h - plot_h * k / 4, 1), "text": value_fmt(low + (top - low) * k / 4)}
             for k in range(5)]
    return {"series": out, "hits": hits, "ticks": ticks, "w": width, "h": height, "x0": pad_l,
            "x1": width - pad_r, "base": pad_t + plot_h, "top": pad_t, "label_y": height - 8, "plot_h": plot_h,
            "legend": [{"name": s["name"], "slot": s.get("slot", 1)} for s in series] if len(series) > 1 else []}


def sparkline(values, width=120, height=32):
    """Đường nhỏ trong ô số liệu: màu nhạt, điểm cuối màu nhấn."""
    vals = [v for v in values if v is not None]
    if len(vals) < 2:
        return None
    lo, hi = min(vals), max(vals)
    span = (hi - lo) or 1
    step = (width - 8) / (len(values) - 1)
    pts = [(4 + i * step, 4 + (height - 8) * (1 - (v - lo) / span)) for i, v in enumerate(values) if v is not None]
    return {"d": "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in pts), "w": width, "h": height,
            "ex": round(pts[-1][0], 1), "ey": round(pts[-1][1], 1)}


# ---------------- Thanh ngang ----------------

def hbars(rows, marker_key=None, label_w=150, width=WIDTH):
    """rows: [{"label", "value", "marker"?, "tip", "text", "muted"?, "status"?}] → thanh ngang một chuỗi, vạch mốc."""
    if not rows:
        return None
    peak = max(max(r["value"], (r.get(marker_key) or 0) if marker_key else 0) for r in rows)
    top = _scale_top(peak * 1.05)
    plot_w, row_h, bar_h = width - label_w - 96, 28, 16
    out = []
    for i, r in enumerate(rows):
        w = max(r["value"], 0) / top * plot_w if top else 0
        marker = r.get(marker_key) if marker_key else None
        y = i * row_h + 6
        mx = round(label_w + marker / top * plot_w, 1) if marker else None
        # Nhãn số đặt sau đầu thanh; nếu vạch mốc nằm ngay sau đầu thanh thì đặt sau vạch để khỏi đè lên nhau.
        vx = label_w + w + 8
        if mx is not None and label_w + w - 2 <= mx < vx + 40:
            vx = mx + 8
        out.append({**r, "y": y, "ty": y + bar_h / 2, "d": _bar_path(label_w, y, w, bar_h), "mx": mx,
                    "vx": round(vx, 1)})
    return {"rows": out, "w": width, "h": len(rows) * row_h + 10, "x0": label_w, "label_x": label_w - 8,
            "bar_h": bar_h}


# ---------------- Thanh tỷ phần (một thanh 100%) ----------------

def share_bar(parts, value_fmt=fmt):
    """parts: [(nhãn, giá trị, slot)] tối đa 6 phần → một thanh 100% có khe 2px; nhãn trong mảng chỉ khi vừa."""
    parts = [(label, float(v), slot) for label, v, slot in parts if v and v > 0]
    total = sum(v for _, v, _ in parts)
    if not total:
        return None
    width, height, x = WIDTH, 28, 0.0
    segs = []
    for i, (label, v, slot) in enumerate(parts):
        w = v / total * width
        pct = v / total * 100
        text = f"{pct:.0f}%"
        seg_w = max(w - (2 if i < len(parts) - 1 else 0), 1)
        segs.append({"x": round(x, 1), "w": round(seg_w, 1), "slot": slot, "label": label, "pct": pct,
                     "value": value_fmt(v), "text": text, "fits": seg_w >= len(text) * 7 + 12,
                     "tx": round(x + seg_w / 2, 1), "tip": f"{label}: {value_fmt(v)} ({pct:.0f}%)"})
        x += w
    return {"segs": segs, "w": width, "h": height, "total": total}


# ---------------- Bản đồ nhiệt (thứ × giờ) ----------------

def heatmap(row_labels, col_labels, values, tip=None, value_fmt=fmt, width=WIDTH):
    """values[r][c] ≥ 0 → ô màu theo thang tuần tự một màu (7 bậc theo tỷ lệ với ô lớn nhất); 0 là ô nền."""
    if not row_labels or not col_labels:
        return None
    peak = max((v for row in values for v in row), default=0)
    if peak <= 0:
        return None
    label_w, top_h = 64, 20
    cell_w = (width - label_w) / len(col_labels)
    cell_h = 24
    cells = []
    for r, rl in enumerate(row_labels):
        for c, cl in enumerate(col_labels):
            v = values[r][c] or 0
            step = None if v <= 0 else min(len(SEQ) - 1, int(v / peak * len(SEQ) - 1e-9))
            cells.append({"x": round(label_w + c * cell_w + 1, 1), "y": top_h + r * cell_h + 1,
                          "w": round(cell_w - 2, 1), "h": cell_h - 2, "fill": SEQ[step] if step is not None else None,
                          "tip": tip(r, c, v) if tip else f"{rl}, {cl}: {value_fmt(v)}"})
    every = _label_every(len(col_labels), _room(width - label_w, 30))
    cols = [{"x": round(label_w + c * cell_w + cell_w / 2, 1), "text": cl}
            for c, cl in enumerate(col_labels) if c % every == 0]
    rows = [{"y": top_h + r * cell_h + cell_h / 2, "text": rl} for r, rl in enumerate(row_labels)]
    legend = [{"fill": SEQ[i], "text": value_fmt(peak * (i + 1) / len(SEQ))} for i in range(len(SEQ))]
    return {"cells": cells, "cols": cols, "rows": rows, "w": width, "h": top_h + len(row_labels) * cell_h + 4,
            "label_x": label_w - 8, "legend": legend, "peak": value_fmt(peak)}


# ---------------- Phân tán (ma trận thực đơn) ----------------

def scatter(points, x_mid, y_mid, x_fmt=fmt, y_fmt=fmt, quadrants=None, height=300, label_top=6, width=WIDTH):
    """points: [{"x", "y", "label", "tip"}]; x_mid, y_mid: đường chia bốn ô (trung bình). Một màu, nhãn chọn lọc."""
    if not points:
        return None
    pad_l, pad_r, pad_t, pad_b = 56, 16, 16, 30
    xs, ys = [p["x"] for p in points], [p["y"] for p in points]
    x_top, y_top = _scale_top(max(xs + [x_mid]) * 1.05), _scale_top(max(ys + [y_mid]) * 1.05)
    y_low = min(0, min(ys))
    if y_low < 0:
        y_low = -_scale_top(-y_low)
    plot_w, plot_h = width - pad_l - pad_r, height - pad_t - pad_b

    def px(v):
        return round(pad_l + v / x_top * plot_w, 1)

    def py(v):
        return round(pad_t + plot_h - (v - y_low) / (y_top - y_low) * plot_h, 1)

    ranked = sorted(points, key=lambda p: -(p["x"] / x_top + (p["y"] - y_low) / (y_top - y_low)))
    dots = [{"cx": px(p["x"]), "cy": py(p["y"]), "tip": p["tip"], "label": p["label"], "show": False, "_rank": i}
            for i, p in enumerate(points)]
    rank = {id(p): k for k, p in enumerate(ranked)}
    # Đặt nhãn tham lam theo thứ tự nổi bật: thử bên phải, bên trái, rồi lệch lên hoặc xuống một dòng; chỗ nào cũng
    # chồng lên nhãn khác hay chấm khác thì bỏ nhãn (vẫn còn chú thích khi rê chuột và bảng số liệu).
    placed = []
    for p, d in sorted(zip(points, dots), key=lambda pd: rank[id(pd[0])]):
        if rank[id(p)] >= label_top:
            continue
        text = d["label"] if len(d["label"]) <= 22 else d["label"][:21] + "…"
        w, h = len(text) * 6.2 + 4, 13
        for anchor, dx, dy in (("start", 8, 0), ("end", -8, 0), ("start", 8, -13), ("start", 8, 13),
                               ("end", -8, -13), ("end", -8, 13)):
            lx, ly = d["cx"] + dx, d["cy"] + dy
            box = (lx if anchor == "start" else lx - w, ly - h / 2, (lx + w) if anchor == "start" else lx, ly + h / 2)
            if box[0] < pad_l or box[2] > width - 2 or box[1] < 0 or box[3] > pad_t + plot_h:
                continue
            if any(box[0] < b[2] and b[0] < box[2] and box[1] < b[3] and b[1] < box[3] for b in placed):
                continue
            if any(o is not d and box[0] - 4 < o["cx"] < box[2] + 4 and box[1] - 4 < o["cy"] < box[3] + 4
                   for o in dots):
                continue
            placed.append(box)
            d.update(show=True, anchor=anchor, lx=round(lx, 1), ly=round(ly, 1), text=text)
            break
    for d in dots:
        d.pop("_rank")
    q = quadrants or {}
    return {"dots": dots, "w": width, "h": height, "x0": pad_l, "x1": width - pad_r, "y0": pad_t,
            "base": pad_t + plot_h, "mx": px(x_mid), "my": py(y_mid), "label_y": height - 8,
            "xticks": [{"x": px(x_top * k / 4), "text": x_fmt(x_top * k / 4)} for k in range(5)],
            "yticks": [{"y": py(y_low + (y_top - y_low) * k / 4), "text": y_fmt(y_low + (y_top - y_low) * k / 4)}
                       for k in range(5)],
            "q": {"tr": q.get("tr", ""), "tl": q.get("tl", ""), "br": q.get("br", ""), "bl": q.get("bl", "")},
            "zero": py(0) if y_low < 0 else None}


# ---------------- Lịch dùng lô (dải thời gian) ----------------

def lot_timeline(views, unit, today, max_days=60, width=WIDE):
    """Mỗi lô một dòng: dải từ ngày bắt đầu lấy tới ngày dự kiến dùng hết, vạch hạn dùng; lô sẽ bỏ có phần đỏ."""
    from apps.inventory import lots as lot_rules

    rows = [v for v in views if v.state != lot_rules.EXPIRED]
    if not rows:
        return None
    ends = []
    for v in rows:
        for d in (v.used_up, v.expiry_date):
            if d:
                ends.append((d - today).days + 1)
    span = min(max(ends + [7]), max_days)
    label_w, plot_w, row_h = 120, width - 120 - 90, 30
    day_w = plot_w / span

    def x(day):
        return round(label_w + min(max(day, 0), span) * day_w, 1)

    out = []
    for i, v in enumerate(rows):
        y = 26 + i * row_h
        start = (v.start - today).days if v.start else None
        end = ((v.used_up - today).days + 1) if v.used_up else None
        exp = ((v.expiry_date - today).days + 1) if v.expiry_date else None
        if start is None:
            seg = None
        else:
            stop = end if end is not None else (exp if exp is not None else span)
            seg = {"x": x(start), "w": max(x(stop) - x(start) - 1, 2)}
        waste = None
        if v.waste > 0 and exp is not None:
            waste = {"x": x(exp), "text": f"bỏ ~{fmt(v.waste)} {unit}"}
        tip = (f"Lô {v.code}: còn {fmt(float(v.remaining))} {unit}"
               + (f", bắt đầu lấy {v.start:%d/%m}" if v.start else ", chưa tới lượt trong tầm nhìn")
               + (f", dự kiến hết {v.used_up:%d/%m}" if v.used_up else "")
               + (f", hạn {v.expiry_date:%d/%m}" if v.expiry_date else ", chưa rõ hạn")
               + (f", dự kiến bỏ {fmt(v.waste)} {unit}" if v.waste > 0 else ""))
        out.append({"y": y, "ty": y + 9, "label": v.code, "seg": seg, "exp": x(exp) if exp is not None and exp <= span
                    else None, "waste": waste, "tip": tip, "rank": v.rank})
    ticks = []
    every = max(1, math.ceil(span / _room(plot_w, 48)))
    every = 7 if every > 2 and span > 21 else every
    for d in range(0, span + 1, every):
        ticks.append({"x": x(d), "text": f"{today + timedelta(days=d):%d/%m}"})
    return {"rows": out, "w": width, "h": 26 + len(rows) * row_h + 8, "x0": label_w, "x1": width - 90,
            "ticks": ticks, "today": x(0), "label_x": label_w - 8}


# ---------------- Khoảng (dự báo: kỳ vọng và khoảng 10–90%) ----------------

def ranges(rows, label_w=130, width=WIDTH, unit=""):
    """rows: [{"label", "lo", "mid", "hi", "tip"}] → mỗi dòng một dải từ lo tới hi và một chấm ở mid (một trục)."""
    if not rows:
        return None
    pad_r, row_h = 110, 28
    peak = max(r["hi"] for r in rows) * 1.05 or 1
    # Chọn 4, 5 hoặc 6 khoảng chia sao cho đỉnh trục sát số lớn nhất nhất (vạch chia vẫn là số tròn).
    n, top = min(((k, k * nice_max(peak / k)) for k in (4, 5, 6)), key=lambda t: t[1])
    plot_w = width - label_w - pad_r
    out = []

    def x(v):
        return round(label_w + max(v, 0) / top * plot_w, 1)

    for i, r in enumerate(rows):
        y = 22 + i * row_h
        lo, hi = x(r["lo"]), x(r["hi"])
        out.append({**r, "y": y, "cy": y + 8, "bx": lo, "bw": max(hi - lo, 2), "cx": x(r["mid"]), "vx": hi + 8,
                    "text": f"{fmt(r['mid'])} ({fmt(r['lo'])}–{fmt(r['hi'])}){unit}"})
    ticks = [{"x": x(top * k / n), "text": fmt(top * k / n)} for k in range(n + 1)]
    return {"rows": out, "w": width, "h": 22 + len(rows) * row_h + 4, "x0": label_w, "label_x": label_w - 8,
            "ticks": ticks}


# ---------------- Tương thích: thanh chồng BO-01 ----------------

def stacked(parts, target):
    """BO-01: một thanh xếp chồng (đã xác minh + đang xử lý) so với vạch mục tiêu."""
    total = sum(v for _, v, _ in parts)
    top = nice_max(max(total, target) * 1.1)
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
