"""Chạy mô phỏng khép kín kế hoạch mua (apps/forecast/simulation.py) để so cách tính hiện tại với cách cũ.

Không đọc hay ghi cơ sở dữ liệu. Một năm mô phỏng mất khoảng một phút rưỡi mỗi hạt giống.
"""

from django.core.management.base import BaseCommand

from apps.forecast import simulation as sim


class Command(BaseCommand):
    help = "Mô phỏng một năm mua nguyên liệu trên quán giả lập; in số lần thiếu mỗi tháng, ly mất, tỷ lệ hết hạn."

    def add_arguments(self, parser):
        parser.add_argument("--cach", choices=["hien-tai", "truoc-2610", "thoi-quen"], default="hien-tai",
                            help="hien-tai: EWA và mức phục vụ theo nhóm; truoc-2610: cách tính cũ; "
                                 "thoi-quen: Chủ quán đặt theo thói quen, không dùng hệ thống")
        parser.add_argument("--ngay", type=int, default=364, help="Số ngày mô phỏng (mặc định 364)")
        parser.add_argument("--hat-giong", default="1", help="Các hạt giống ngẫu nhiên, cách nhau dấu phẩy")

    def handle(self, *args, **o):
        rules = sim.BEFORE_2610 if o["cach"] == "truoc-2610" else sim.Rules()
        owner = "habit" if o["cach"] == "thoi-quen" else "system"
        for seed in [int(x) for x in o["hat_giong"].split(",") if x.strip()]:
            r = sim.simulate(rules, owner=owner, seed=seed, days=o["ngay"])
            self.stdout.write(f"\n{r['label']}, hạt giống {seed}: {r['stockouts_per_month']:.2f} lần thiếu mỗi tháng "
                              f"trên {len(r['ingredients'])} nguyên liệu, mất {r['lost_cup_share'] * 100:.2f}% số ly")
            self.stdout.write(f"{'Nguyên liệu':18} {'Nhóm':>4} {'CSL':>5} {'Ngày thiếu':>10} {'Hết hạn %':>9} "
                              f"{'Đủ dùng (ngày)':>14} {'Lần đặt':>7}")
            for name, k in r["ingredients"].items():
                csl = "" if k["csl"] is None else f"{k['csl']:g}"
                cover = "" if k["cover_days"] is None else f"{k['cover_days']:.1f}"
                self.stdout.write(f"{name[:18]:18} {k['group']:>4} {csl:>5} {k['stockout_days']:>10} "
                                  f"{k['expired_share'] * 100:>9.1f} {cover:>14} {k['orders']:>7}")
