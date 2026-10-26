"""Chạy mô phỏng quán theo từng sự kiện (apps/schedule/simulation.py) để so các cách gợi ý số người cần.

Không đọc hay ghi cơ sở dữ liệu. Quán giả lập chạy 8 tuần theo lịch cố định để có dữ liệu học (như quán hiện nay), rồi
chạy thử từng cách xếp người trong `--ngay` ngày với cùng chuỗi khách.
"""

import random

from django.core.management.base import BaseCommand

from apps.schedule import simulation as ss
from apps.schedule import staffing


class Command(BaseCommand):
    help = "Mô phỏng hàng đợi của quán; in tỷ lệ giờ đạt chuẩn chờ, giờ đông đạt chuẩn và giờ công mỗi ngày."

    def add_arguments(self, parser):
        parser.add_argument("--ngay", type=int, default=28, help="Số ngày chạy thử mỗi cách (mặc định 28)")
        parser.add_argument("--hat-giong", default="1", help="Các hạt giống ngẫu nhiên, cách nhau dấu phẩy")
        parser.add_argument("--tai", type=float, default=1.0, help="Hệ số khách so với bình thường, ví dụ 1.3")
        parser.add_argument("--cho", type=float, default=4, help="Số phút chờ trong hàng mục tiêu (tham số)")
        parser.add_argument("--muc", type=float, default=70, help="Phần trăm việc chờ không quá số phút trên")
        parser.add_argument("--suc-lam-phuc-vu", type=float, default=0, help="Sức làm phục vụ Chủ quán đặt; 0: tự ước lượng")
        parser.add_argument("--suc-lam-thu-ngan", type=float, default=0, help="Sức làm thu ngân Chủ quán đặt; 0: tự ước lượng")

    def handle(self, *args, **o):
        scv = (staffing.batch_scv(ss.ORDER_SIZES) + 0.25) / 2
        for seed in [int(x) for x in o["hat_giong"].split(",") if x.strip()]:
            hist = ss.history(56, random.Random(seed))
            shares, load_per_cup = ss.load_profile(hist)
            old = ss.old_productivity(hist)
            rates = ss.estimate_rates(hist)
            rates["phuc_vu"] = o["suc_lam_phuc_vu"] or rates["phuc_vu"]
            rates["thu_ngan"] = o["suc_lam_thu_ngan"] or rates["thu_ngan"]
            self.stdout.write(f"\nHạt giống {seed}. Năng suất cách cũ (trung vị): "
                              + ", ".join(f"{r} {v:.1f}" for r, v in old.items())
                              + ". Sức làm cách mới: " + ", ".join(f"{r} {v:.1f}" for r, v in rates.items()))

            def loads(weekend):
                return ss.hourly_load(ss.CUPS_PER_DAY[weekend] * o["tai"], shares[weekend], load_per_cup)

            ways = [("Lịch cố định hiện nay", ss.as_is_staff)]
            for label, shifts in (("2 ca", ss.SHIFTS_BASIC), ("4 ca có ca cao điểm", ss.SHIFTS_PEAK)):
                ways.append((f"Gợi ý trước 26/10, {label}",
                             lambda w, s=shifts: ss.plan_old(s, loads(w), old)))
                ways.append((f"Gợi ý mới, {label}",
                             lambda w, s=shifts: ss.plan_staff(s, loads(w), rates, o["cho"], o["muc"] / 100, scv)))
            self.stdout.write(f"{'Cách':38} {'Giờ đạt chuẩn':>13} {'Giờ đông đạt':>12} {'Giờ công/ngày':>13}")
            for label, fn in ways:
                r = ss.evaluate(fn, o["ngay"], random.Random(seed * 100 + 7), scale=o["tai"])
                self.stdout.write(f"{label:38} {r['ok_share'] * 100:>12.1f}% {r['peak_ok_share'] * 100:>11.1f}% "
                                  f"{r['staff_hours_per_day']:>13.1f}")
