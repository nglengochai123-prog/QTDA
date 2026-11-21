"""Giải thích bằng lời vì sao gợi ý N người cho một vị trí trong một ca (BRU-37: gợi ý phải để Chủ quán kiểm tra được).

Đọc căn cứ đã lưu cùng gợi ý (RoleNeed.basis, do services.suggest_day ghi) và tính lại đúng công thức hàng đợi đã
dùng (staffing.wait_ok_probability), nên câu giải thích luôn khớp với con số gợi ý:

1. Ngày đó dự kiến bao nhiêu ly và xếp người đủ cho bao nhiêu ly.
2. Giờ đông nhất của ca với vị trí này: bao nhiêu việc trong giờ đó, một người làm được bao nhiêu việc mỗi giờ.
3. Với số người đề xuất, bao nhiêu phần trăm việc được làm trong thời gian chờ chuẩn; bớt một người thì còn bao
   nhiêu, so với mục tiêu. Đây là lý do không thể bớt.
4. Khi ca khác chồng giờ đông nhất, phần người còn lại do ca đó gánh; khi tải thấp, số người là mức tối thiểu.

Hàm thuần, không đọc cơ sở dữ liệu.
"""

from apps.core import numbers

from . import staffing


def _pct(p):
    return f"{numbers.fmt(max(min(p, 1.0), 0.0) * 100, 0)}%"


# Cách nói việc của từng vị trí cho Chủ quán: (việc trong giờ đông, việc được bắt đầu kịp).
WORDS = {"tải": ("món quy đổi (món khó pha như đá xay tính nặng hơn)", "món được bắt đầu pha"),
         "lượt": ("lượt phục vụ (nhận đơn, mang món)", "lượt phục vụ có người làm"),
         "giao dịch": ("giao dịch thu tiền", "giao dịch có người làm")}
# Sức làm chưa đo được ở quán thì nói rõ là số giả định.
RATE_NOTE = {"standard": "số giả định, chưa đo được ở quán", "conservative": "ước tính thận trọng, có thể dư người"}


def _hour(h):
    return f"{h}–{h + 1} giờ"


def explain(n, basis, role_label):
    """{"short": câu ngắn, "lines": [câu giải thích], "peak": giờ đông nhất} hoặc None khi chưa có căn cứ."""
    if n is None or not basis or "hours" not in basis:
        return None
    label = role_label.lower()
    unit, rate = basis.get("unit", "việc"), float(basis.get("rate") or 0)
    work_noun, done_noun = WORDS.get(unit, (unit, f"{unit} có người làm"))
    short_unit = work_noun.split(" (")[0]
    wait, target = basis.get("wait_minutes"), basis.get("service_percent")
    scv, minimum = float(basis.get("scv") or 1.0), int(basis.get("minimum") or 0)
    hours = [(int(h), float(load), int(need)) for h, load, need in basis["hours"]]
    lines = []
    cups, mean = basis.get("cups"), basis.get("cups_mean", basis.get("cups"))
    if cups is not None:
        extra = (f"; xếp người đủ cho {numbers.fmt(cups, 0)} ly để ngày đông hơn dự báo vẫn kịp"
                 if mean is not None and round(cups) > round(mean) else "")
        lines.append(f"Ngày này dự kiến bán khoảng {numbers.fmt(mean, 0)} ly ({basis.get('cups_source', '').lower()}){extra}.")
    if not hours:
        return {"short": "Ca nằm ngoài giờ mở cửa.", "lines": lines, "peak": None}
    # Giờ cần nhiều người nhất trong ca; hòa thì giờ nhiều việc hơn.
    peak_h, peak_load, peak_need = max(hours, key=lambda x: (x[2], x[1]))
    if rate > 0:
        note = RATE_NOTE.get(basis.get("rate_kind"))
        source = basis.get("rate_source", "").lower() + (f"; {note}" if note else "")
        lines.append(f"Giờ đông nhất của ca là {_hour(peak_h)}: khoảng {numbers.fmt(peak_load, 1)} {work_noun}; "
                     f"một {label} làm được khoảng {numbers.fmt(rate, 1)} {short_unit} mỗi giờ ({source}).")
    t = (wait or 0) / 60
    busy_one = peak_load / rate if rate > 0 else 0
    by_load = staffing.servers_needed(peak_load, rate, t, (target or 0) / 100, scv) if rate > 0 else 0
    if by_load < peak_need:  # tải thấp: số người là mức tối thiểu khi quán mở, không phải do hàng đợi
        lines.append(f"Theo lượng việc chỉ cần {by_load} {label}, nhưng quán giữ tối thiểu {minimum} {label} "
                     f"mỗi giờ mở cửa.")
        short = f"Mức tối thiểu {minimum} người; giờ đông nhất {_hour(peak_h)} vẫn trong sức {by_load} người."
    else:
        ok = staffing.wait_ok_probability(peak_need, peak_load, rate, t, scv)
        sentence = (f"Với {peak_need} {label} trong giờ đó, khoảng {_pct(ok)} {done_noun} trong {numbers.fmt(wait, 0)} "
                    f"phút sau khi đến (mục tiêu {target}%)")
        if peak_need - 1 >= 1:
            fewer = staffing.wait_ok_probability(peak_need - 1, peak_load, rate, t, scv)
            sentence += (f"; còn {peak_need - 1} người thì " + ("không kịp, hàng chờ dài mãi"
                         if peak_need - 1 <= busy_one else f"chỉ còn {_pct(fewer)}"))
        lines.append(sentence + ".")
        short = (f"Giờ đông nhất {_hour(peak_h)} cần {peak_need} {label} để {_pct(ok)} {done_noun} "
                 f"trong {numbers.fmt(wait, 0)} phút.")
    if n < peak_need:
        lines.append(f"Ca khác chồng giờ {_hour(peak_h)} góp {peak_need - n} người, nên ca này chỉ cần {n}.")
        short = f"{n} người; ca chồng giờ góp thêm {peak_need - n} vào giờ đông nhất {_hour(peak_h)}."
    if n == 0:
        short = "Các giờ của ca đã có ca khác chồng giờ phủ đủ."
    if basis.get("uncovered"):
        lines.append("Có giờ mở cửa chưa ca nào phủ: " + ", ".join(_hour(int(h)) for h in basis["uncovered"]) + ".")
    return {"short": short, "lines": lines, "peak": peak_h}
