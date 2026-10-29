"""Chạy mô phỏng khép kín kế hoạch mua (apps/forecast/simulation.py) để so cách tính hiện tại với cách cũ.

Không đọc hay ghi cơ sở dữ liệu. Một năm mô phỏng mất khoảng một phút rưỡi mỗi hạt giống.
"""

from django.core.management.base import BaseCommand

from apps.forecast import simulation as sim


class Command(BaseCommand):
    help = "Mô phỏng một năm mua nguyên liệu trên quán giả lập; in số lần thiếu mỗi tháng, ly mất, tỷ lệ hết hạn."

    def add_arguments(self, parser):
        parser.add_argument("--cach", choices=["hien-tai", "khong-phan-cap", "truoc-2610", "thoi-quen"],
                            default="hien-tai",
                            help="hien-tai: dự báo phân cấp, EWA và mức phục vụ theo nhóm; khong-phan-cap: chỉ dự "
                                 "báo trực tiếp trên chuỗi nguyên liệu; truoc-2610: cách tính chính sách cũ; "
                                 "thoi-quen: Chủ quán đặt theo thói quen, không dùng hệ thống")
        parser.add_argument("--ngay", type=int, default=364, help="Số ngày mô phỏng (mặc định 364)")
        parser.add_argument("--hat-giong", default="1", help="Các hạt giống ngẫu nhiên, cách nhau dấu phẩy")

    def handle(self, *args, **o):
        rules = {"truoc-2610": sim.BEFORE_2610, "khong-phan-cap": sim.NO_HIERARCHY}.get(o["cach"], sim.Rules())
        owner = "habit" if o["cach"] == "thoi-quen" else "system"
        for seed in [int(x) for x in o["hat_giong"].split(",") if x.strip()]:
            r = sim.simulate(rules, owner=owner, seed=seed, days=o["ngay"])
            self.stdout.write(f"\n{r['label']}, hạt giống {seed}: {r['stockouts_per_month']:.2f} lần thiếu mỗi tháng "
                              f"trên {len(r['ingredients'])} nguyên liệu, mất {r['lost_cup_share'] * 100:.2f}% số ly")
            t = r.get("total") or {}
            if t.get("method"):
                self.stdout.write(f"Tổng số ly cả quán: cách {t['method']}, WAPE 7 ngày {_pct(t['wape'])}, "
                                  f"WAPE theo món 1 ngày {_pct(t.get('item_wape_1'))}")
            self.stdout.write(f"{'Nguyên liệu':18} {'Nhóm':>4} {'CSL':>5} {'Ngày thiếu':>10} {'Hết hạn %':>9} "
                              f"{'Đủ dùng (ngày)':>14} {'Lần đặt':>7} {'Cách':>5} {'WAPE':>6} {'Chệch':>6}")
            for name, k in r["ingredients"].items():
                csl = "" if k["csl"] is None else f"{k['csl']:g}"
                cover = "" if k["cover_days"] is None else f"{k['cover_days']:.1f}"
                self.stdout.write(f"{name[:18]:18} {k['group']:>4} {csl:>5} {k['stockout_days']:>10} "
                                  f"{k['expired_share'] * 100:>9.1f} {cover:>14} {k['orders']:>7} "
                                  f"{k.get('method') or '':>5} {_pct(k.get('wape')):>6} {_pct(k.get('bias_share')):>6}")


def _pct(x):
    return "" if x is None else f"{x * 100:.1f}%"
