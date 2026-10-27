"""Tạo bộ dữ liệu MÔ PHỎNG nhiều tuần để chạy thử mọi chức năng: bán hàng, kho theo lô, dự báo, xếp lịch, báo cáo.

Chạy trên một cơ sở dữ liệu trống (PowerShell):

    $env:SQLITE_NAME = "mo_phong.sqlite3"
    .venv\\Scripts\\python.exe manage.py migrate
    .venv\\Scripts\\python.exe manage.py tao_du_lieu_mo_phong --ngay 56

Khác bộ nghiệm thu 14 ngày (`tao_du_lieu_nghiem_thu`):
- Mười món, khách đông vào giờ sáng và tối, cuối tuần đông hơn, số khách tăng nhẹ theo thời gian.
- Hai pha chế, hai phục vụ chia ca sáng và chiều; thời gian chờ dài ra khi quầy đông.
- Đặt hàng trước khi giao, lượng đặt theo lượng dùng; sữa tươi giao hai ngày một lần, kem muối dễ hết hạn.
- Đổi món, hủy món, chuyển bàn, hủy hóa đơn có hoàn tiền; hao hụt, kiểm kê có chênh lệch.
- Dự báo phát hành mỗi ngày trong hai tuần cuối, kế hoạch mua và cảnh báo chạy như thật.
- Lịch làm tuần này đã công bố, tuần sau đã có đăng ký để Chủ quán xếp thử.
- Hôm nay dừng ở giờ hiện tại: còn đơn đang mở, một yêu cầu đổi món và một kiểm kê chờ Chủ quán.

Đây là dữ liệu giả lập, không phải số liệu thật của quán. Đăng nhập bằng tài khoản demo_* (mật khẩu demo-lam-2026).
"""

import heapq
import itertools
import math
import random
import tempfile
from datetime import time, timedelta
from decimal import Decimal
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.test import override_settings
from django.utils import timezone

from .tao_du_lieu_nghiem_thu import Clock, key

PASSWORD = "demo-lam-2026"
FORECAST_DAYS = 14  # dự báo và kế hoạch mua chạy mỗi tối trong hai tuần cuối; dài hơn thì tệp dữ liệu vượt 25 MB

# Nhà cung cấp: tên nguyên liệu → (nhà cung cấp, chu kỳ giao (ngày), thời gian giao (ngày), số ngày dùng muốn có sau
# mỗi lần giao, hạn in trên bao bì (các giá trị có thể, ngày), đơn giá mỗi đơn vị tính).
SUPPLY = {
    "Sữa tươi": ("Đại lý sữa An Phát", 2, 1, 3, (6, 7, 8), 32),
    "Sữa đặc": ("Đại lý sữa An Phát", 7, 1, 9, (150, 180, 200), 62),
    "Kem muối": ("Đại lý sữa An Phát", 4, 1, 6, (5,), 115),  # đặt dư hơn hạn dùng: thấy hao hụt vì hết hạn
    "Cà phê rang xay": ("Xưởng rang Hồng Lam", 5, 2, 7, (45, 60), 260),
    "Trà đen": ("Xưởng rang Hồng Lam", 10, 2, 13, (200, 365), 210),
    "Bột matcha": ("Xưởng rang Hồng Lam", 7, 2, 10, (150,), 1150),
    "Đào ngâm": ("Tạp hóa Bích Ngọc", 5, 1, 7, (35, 90, 240), 95),
    "Trân châu": ("Tạp hóa Bích Ngọc", 7, 1, 9, (150, 180), 45),
    "Ly nhựa": ("Bao bì Thành Công", 7, 2, 10, (None,), 900),
}
# Mức bán: tỷ trọng của từng món; cuối tuần trà và matcha được gọi nhiều hơn.
POPULARITY = {"Cà phê sữa": 26, "Cà phê đen": 14, "Bạc xỉu": 15, "Cà phê muối": 12, "Trà đào": 12, "Trà sữa": 5,
              "Trà sữa trân châu": 7, "Latte": 4, "Matcha đá xay": 3, "Matcha latte": 2}
WEEKEND_BOOST = {"Trà đào": 1.5, "Trà sữa trân châu": 1.6, "Matcha đá xay": 1.6, "Matcha latte": 1.4, "Trà sữa": 1.3}
# Tỷ trọng khách theo giờ (giờ mở cửa 6:30 đến 22:00).
HOURS = {6: 2, 7: 8, 8: 11, 9: 9, 10: 6, 11: 5, 12: 7, 13: 6, 14: 5, 15: 6, 16: 7, 17: 6, 18: 7, 19: 10, 20: 9, 21: 4}
CUPS_PER_DAY = {0: 82, 1: 80, 2: 84, 3: 86, 4: 95, 5: 125, 6: 132}  # thứ Hai = 0
GROWTH_PER_DAY = 0.003
CUPS_PER_ORDER = 1.55
MINUTES_PER_CUP = 2.3  # một pha chế làm một ly


class Command(BaseCommand):
    help = "Tạo nhiều tuần vận hành mô phỏng để chạy thử mọi chức năng (chỉ chạy trên cơ sở dữ liệu trống)."

    def add_arguments(self, parser):
        parser.add_argument("--ngay", type=int, default=56, help="Số ngày lùi về trước (mặc định 56, tức 8 tuần).")
        parser.add_argument("--hat-giong", type=int, default=2026, help="Đổi số này để có bộ số liệu khác.")

    def handle(self, *args, **options):
        from apps.catalog.models import MenuItem

        if MenuItem.objects.exists():
            raise CommandError("Chỉ chạy trên cơ sở dữ liệu trống (đặt SQLITE_NAME sang tệp mới rồi migrate).")
        days = max(14, options["ngay"])
        real_now = timezone.now()
        first_day = timezone.localdate() - timedelta(days=days)
        clock = Clock(real_now)
        clock.at(first_day, 6, 0)
        with mock.patch("django.utils.timezone.now", clock), override_settings(MEDIA_ROOT=tempfile.mkdtemp()):
            call_command("tao_du_lieu_mau", stdout=self.stdout)
            sim = Simulation(clock, first_day, days, real_now, random.Random(options["hat_giong"]), self.stdout)
            sim.setup()
            for offset in range(days + 1):
                sim.run_day(offset)
            sim.finish()
        self.stdout.write(self.style.SUCCESS(
            f"Đã tạo {days} ngày vận hành mô phỏng đến hôm nay: {sim.stats['orders']} đơn, {sim.stats['cups']} ly. "
            f"Đăng nhập bằng tài khoản demo_* (mật khẩu {PASSWORD})."))


def compact_history():
    """Thu gọn phần dữ liệu suy ra để tệp cơ sở dữ liệu nhỏ (8 tuần chạy thử sinh khoảng 200 MB, gần hết ở đây).

    Mỗi biến động kho tính lại kế hoạch mua và giữ bản cũ; mỗi lần phát hành dự báo lưu nhu cầu nguyên liệu kèm mẫu
    đường mô phỏng. Ứng dụng chỉ đọc bản kế hoạch đang dùng, bản đã có quyết định và nhu cầu nguyên liệu của lần phát
    hành mới nhất, nên chỉ giữ những bản đó. Không đụng tới dữ liệu nghiệp vụ."""
    from django.db import connection

    from apps.forecast.models import ForecastRelease, IngredientForecast, IngredientPlan

    latest = ForecastRelease.objects.order_by("-issued_at", "-id").first()
    if latest is not None:
        IngredientForecast.objects.exclude(release=latest).delete()
    IngredientPlan.objects.filter(is_current=False, decisions__isnull=True).delete()
    if connection.vendor == "sqlite":
        with connection.cursor() as cursor:
            cursor.execute("VACUUM")


class Simulation:
    def __init__(self, clock, first_day, days, real_now, rnd, out):
        self.clock, self.first_day, self.days, self.real_now, self.rnd, self.out = clock, first_day, days, real_now, rnd, out
        self.stats = {"orders": 0, "cups": 0}

    # ---------------- chuẩn bị ----------------

    def setup(self):
        from apps.accounts.models import Role, User
        from apps.catalog.models import ItemSize, MenuItem, Option, Table
        from apps.core.models import Store
        from apps.inventory.models import Ingredient, Supplier
        from apps.orders.models import AdjustmentReason
        from apps.staff.models import Employee

        self.store = Store.get_default()
        extra = {"demo_phache2": (Role.PHA_CHE, "Phạm Thu", "Trang"), "demo_phucvu2": (Role.PHUC_VU, "Đỗ Gia", "Huy")}
        for username, (role, first, last) in extra.items():
            user = User.objects.create(username=username, role=role, first_name=first, last_name=last)
            user.set_password(PASSWORD)
            user.save()
        self.u = {u.username.removeprefix("demo_"): u for u in User.objects.filter(username__startswith="demo_")}
        staff = {"thungan": ([Role.THU_NGAN, Role.PHUC_VU], 26000), "phache": ([Role.PHA_CHE], 27000),
                 "phache2": ([Role.PHA_CHE, Role.PHUC_VU], 25000), "phucvu": ([Role.PHUC_VU], 22000),
                 "phucvu2": ([Role.PHUC_VU, Role.THU_NGAN], 22000)}
        for n, (name, (roles, wage)) in enumerate(staff.items(), start=1):
            user = self.u[name]
            Employee.objects.create(store=self.store, user=user, full_name=f"{user.first_name} {user.last_name}",
                                    phone=f"09051234{n:02d}", roles=roles, hourly_wage=wage)

        self.suppliers = {name: Supplier.objects.create(store=self.store, name=name, phone=f"02693{n:06d}")
                          for n, name in enumerate(dict.fromkeys(v[0] for v in SUPPLY.values()), start=1)}
        self.ing = {i.name: i for i in Ingredient.objects.all()}
        for name, (sup, cycle, lead, *_rest) in SUPPLY.items():
            i = self.ing[name]
            i.main_supplier, i.lead_time_days, i.order_cycle_days = self.suppliers[sup], lead, cycle
            i.save(update_fields=["main_supplier", "lead_time_days", "order_cycle_days", "updated_at"])
        self.sizes = list(ItemSize.objects.select_related("item").filter(item__status=MenuItem.Status.ON_SALE))
        self.toppings = list(Option.objects.filter(group__name="Topping"))
        self.tables = list(Table.objects.all())
        self.reasons = {r.name: r for r in AdjustmentReason.objects.all()}
        self.usage = self._expected_usage()
        self.next_delivery = {name: SUPPLY[name][2] for name in SUPPLY}  # ngày giao đầu tiên (theo số ngày lệch)
        self.open_pos = {}
        self.backorders = {}  # phần giao thiếu, nhà cung cấp giao bù hôm sau: tên -> [(mã đơn, lượng, ngày)]
        self._expert_judgements()

    def _weights(self, weekend):
        out = []
        for size in self.sizes:
            w = POPULARITY.get(size.item.name, 3) * (WEEKEND_BOOST.get(size.item.name, 1) if weekend else 1)
            share = 0.65 if size.name == "M" else 0.35
            if size.item.sizes.count() == 1:
                share = 1
            out.append(w * share)
        return out

    def _expected_usage(self):
        """Lượng dùng dự kiến mỗi ngày theo định mức và tỷ trọng món: dùng cho lần đặt đầu, khi chưa có sổ kho."""
        from apps.inventory.models import RecipeLine, RecipeVersion

        weights = self._weights(False)
        total = sum(weights)
        cups = sum(CUPS_PER_DAY.values()) / 7
        usage = {}
        for size, w in zip(self.sizes, weights):
            version = size.item.recipe_versions.filter(status=RecipeVersion.Status.PUBLISHED).first()
            for line in RecipeLine.objects.filter(version=version, size=size).select_related("ingredient"):
                usage[line.ingredient.name] = usage.get(line.ingredient.name, 0) + float(line.quantity) * cups * w / total
        usage["Trân châu"] = usage.get("Trân châu", 0) + cups * 0.12 * 40
        usage["Kem muối"] = usage.get("Kem muối", 0) + cups * 0.06 * 30
        return usage

    def _expert_judgements(self):
        from apps.forecast.models import DayType, ExpertJudgement

        for weekend, day_type in ((False, DayType.WEEKDAY), (True, DayType.WEEKEND)):
            weights = self._weights(weekend)
            total = sum(weights)
            cups = (CUPS_PER_DAY[5] + CUPS_PER_DAY[6]) / 2 if weekend else sum(CUPS_PER_DAY[d] for d in range(5)) / 5
            for size, w in zip(self.sizes, weights):
                typical = round(cups * w / total * self.rnd.uniform(0.8, 1.2), 1)  # Chủ quán ước lượng, không chính xác
                ExpertJudgement.objects.create(
                    store=self.store, size=size, day_type=day_type, typical=Decimal(str(typical)),
                    low=Decimal(str(round(typical * 0.6, 1))), high=Decimal(str(round(typical * 1.5, 1))),
                    basis="Ước lượng của Chủ quán từ sổ bán tay (dữ liệu mô phỏng)", provided_by=self.u["chuquan"])

    # ---------------- một ngày ----------------

    def run_day(self, offset):
        from apps.shifts.models import Shift

        self.offset, self.day = offset, self.first_day + timedelta(days=offset)
        self.today = offset == self.days
        self.weekend = self.day.weekday() >= 5
        self.clock.at(self.day, 6, 0)
        shift = Shift.objects.filter(starts_at__date=self.day).first()
        if shift is None:
            shift = Shift.objects.create(store=self.store, name="Ca ngày", starts_at=self.clock.now,
                                         ends_at=self.clock.now + timedelta(hours=16), approver=self.u["chuquan"],
                                         payment_authorizer=self.u["thungan"])
        else:
            shift.name, shift.starts_at, shift.ends_at = "Ca ngày", self.clock.now, self.clock.now + timedelta(hours=16)
            shift.save()
        self.shift = shift
        self.queue, self.seq = [], itertools.count()
        self._roster()
        self._push(self._at(6, 5), self._open_cash)
        self._push(self._at(6, 10), self._dispose_expired)
        self._push(self._at(6, 40), self._deliveries)
        self._push(self._at(9, 0), self._pay_suppliers)
        self._push(self._at(10, 0), self._purchase_orders)
        self._orders()
        if self.rnd.random() < 0.35:
            self._push(self._at(self.rnd.randint(9, 20), self.rnd.randint(0, 59)), self._waste)
        if self.offset % 9 == 4:
            self._push(self._at(21, 10), self._cancel_paid)
        if self.offset == self.days - 20:
            self._push(self._at(15, 30), self._backup_slip)
        self._push(self._at(21, 40), self._counts)
        self._push(self._at(22, 0), self._close_day)
        if self.days - offset <= FORECAST_DAYS:
            self._push(self._at(22, 30), self._nightly)
        while self.queue:
            when, _, fn, args = heapq.heappop(self.queue)
            if self.today and when > self.real_now:
                continue  # hôm nay chỉ tới giờ hiện tại, không tạo giao dịch tương lai
            self.clock.now = when
            fn(*args)

    def _at(self, hour, minute=0):
        return timezone.make_aware(timezone.datetime.combine(self.day, time(hour, minute)))

    def _push(self, when, fn, *args):
        heapq.heappush(self.queue, (when, next(self.seq), fn, args))

    def _roster(self):
        """Ai làm ca nào hôm nay: pha chế và phục vụ chia sáng (6:30–14:30) và chiều (14:00–22:00)."""
        from apps.accounts.models import Role

        morning, evening = (6, 30), (14, 0)
        plan = [("thungan", Role.THU_NGAN, (6, 20), (22, 5)),
                ("phache", Role.PHA_CHE, morning, (14, 30)), ("phache2", Role.PHA_CHE, evening, (22, 5)),
                ("phucvu", Role.PHUC_VU, morning, (14, 30)), ("phucvu2", Role.PHUC_VU, evening, (22, 5))]
        if self.weekend:  # cuối tuần thêm người giờ đông
            plan += [("phache2", Role.PHA_CHE, (7, 0), (11, 0)), ("phucvu2", Role.PHUC_VU, (7, 0), (11, 0))]
        if self.day.weekday() == 2:  # thứ Tư phục vụ ca sáng nghỉ, thu ngân phục vụ thay
            plan = [p for p in plan if not (p[0] == "phucvu" and p[2] == morning)]
        self.on_duty = []
        for name, role, start, end in plan:
            jitter = self.rnd.randint(-6, 6)
            t_in = self._at(*start) + timedelta(minutes=jitter)
            t_out = self._at(*end) + timedelta(minutes=self.rnd.randint(0, 10))
            self.on_duty.append((name, role, t_in, t_out))
            self._push(t_in, self._clock_in, name, role)
            if not (self.today and t_out > self.real_now):
                self._push(t_out, self._clock_out, name, role)
        self.baristas = {n: t_in for n, r, t_in, _ in self.on_duty if r == Role.PHA_CHE}

    def _working(self, role, when):
        names = [n for n, r, t_in, t_out in self.on_duty if r == role and t_in <= when < t_out]
        return names or [n for n, r, *_ in self.on_duty if r == role]

    # ---------------- sự kiện ----------------

    def _clock_in(self, name, role):
        from apps.staff.models import Attendance

        Attendance.objects.create(store=self.store, user=self.u[name], role=role, clock_in=self.clock.now)

    def _clock_out(self, name, role):
        from apps.staff.models import Attendance

        att = Attendance.objects.filter(user=self.u[name], role=role, clock_out__isnull=True).order_by("-clock_in").first()
        if att:
            att.clock_out = self.clock.now
            att.save(update_fields=["clock_out"])

    def _open_cash(self):
        from apps.shifts import services as shifts

        shifts.add_cash_entry(self.u["thungan"], key(), self.shift.pk, "dau_ca", 500000)

    def _dispose_expired(self):
        from apps.inventory import operations as ops
        from apps.inventory.models import StockLot

        if self.today:
            return  # hôm nay để lại để Chủ quán thấy cảnh báo lô quá hạn
        for lot in StockLot.objects.filter(remaining__gt=0, expiry_date__lt=self.day):
            ops.dispose_lot(self.u["phache"], key(), lot.pk)

    def _rate(self, name):
        from apps.inventory import lots

        used = lots.daily_usage([self.ing[name].pk], self.day, days=14).get(self.ing[name].pk)
        return used if used and self.offset >= 7 else self.usage.get(name, 0)

    def _purchase_orders(self):
        """Đặt hàng trước ngày giao theo thời gian giao của từng nhà cung cấp; lượng đặt đủ dùng tới lần giao sau."""
        from apps.inventory import operations as ops

        for name, (sup, cycle, lead, cover, _shelf, _price) in SUPPLY.items():
            arrive = self.offset + lead
            if arrive != self.next_delivery[name]:  # đơn đặt hôm nay giao sau hôm nay vẫn tạo: thành hàng đang về
                continue
            ing = self.ing[name]
            ing.stock.refresh_from_db()
            rate = self._rate(name) * (1 + 0.15 * self.rnd.random())
            want = rate * (cover + lead) - float(ing.stock.physical) - sum(float(p.quantity) for p in self.open_pos.get(name, []))
            if name == "Kem muối":
                want = max(want, rate * cover)
            pack = float(ing.pack_size)
            packs = max(1, math.ceil(want / pack)) if want > 0 else 0
            if packs:
                po = ops.create_purchase_order(self.u["chuquan"], self.suppliers[sup].pk, ing.pk, packs * pack,
                                               self.day + timedelta(days=lead), operation_key=key())
                self.open_pos.setdefault(name, []).append(po)
            self.next_delivery[name] += cycle

    def _pay_suppliers(self):
        """Chủ quán trả các khoản mua chịu tới hạn trong hôm nay và ngày mai, bằng chuyển khoản."""
        from apps.inventory import operations as ops
        from apps.inventory.models import Payable

        for payable in Payable.objects.filter(due_date__lte=self.day + timedelta(days=1)):
            left = payable.remaining()
            if left > 0:
                ops.pay_supplier(self.u["chuquan"], payable.pk, left, "chuyen_khoan", self.day, operation_key=key())

    def _deliveries(self):
        from apps.inventory import operations as ops

        due = {}
        first = self.offset == 0
        for name, (sup, _cycle, lead, cover, shelf, price) in SUPPLY.items():
            ing = self.ing[name]
            pos = [p for p in self.open_pos.get(name, []) if p.expected_date <= self.day]
            lines = []
            for po in pos:
                qty = po.quantity
                if self.rnd.random() < 0.06:  # thỉnh thoảng giao thiếu một ít, hôm sau giao bù
                    qty = max(Decimal(1), (qty * Decimal("0.8")).quantize(Decimal(1)))
                    self.backorders.setdefault(name, []).append((po.pk, po.quantity - qty, self.day + timedelta(days=1)))
                lines.append((qty, po.pk))
                self.open_pos[name].remove(po)
            for back in [b for b in self.backorders.get(name, []) if b[2] <= self.day]:
                lines.append((back[1], back[0]))
                self.backorders[name].remove(back)
            if first:  # ngày đầu nhập đủ dùng mấy ngày đầu
                lines.append((Decimal(math.ceil(self.usage.get(name, 0) * (lead + 1) / float(ing.pack_size)) * ing.pack_size), None))
            for qty, po_id in lines:
                days_left = self.rnd.choice(shelf)
                due.setdefault(sup, []).append({
                    "ingredient": ing.pk, "quantity": str(qty),
                    "unit_price": round(price * self.rnd.uniform(0.97, 1.06)),
                    "expiry_date": (self.day + timedelta(days=days_left)).isoformat() if days_left else None,
                    "supplier_lot": f"{self.rnd.randint(10, 99)}{self.day:%m%d}" if days_left else "",
                    **({"purchase_order": po_id} if po_id else {})})
        for sup, lines in due.items():
            self.clock.tick(4)
            ops.create_receipt(self.u["phache"] if self.offset % 3 else self.u["chuquan"], key(), self.suppliers[sup].pk,
                               lines, "tra_ngay" if self.offset % 2 else "tra_sau",
                               invoice_photo=SimpleUploadedFile("hd.jpg", b"\xff\xd8\xffjpeg", content_type="image/jpeg"),
                               paid_source="chuyen_khoan")

    def _orders(self):
        cups = CUPS_PER_DAY[self.day.weekday()] * (1 + GROWTH_PER_DAY * self.offset) * self.rnd.uniform(0.88, 1.12)
        rain = self.rnd.random() < 0.08  # ngày mưa vắng khách
        if rain:
            cups *= 0.7
        orders = max(10, round(cups / CUPS_PER_ORDER))
        hours, weights = list(HOURS), list(HOURS.values())
        self.size_weights = self._weights(self.weekend)
        self.barista_free = {}
        for _ in range(orders):
            hour = self.rnd.choices(hours, weights)[0]
            minute = self.rnd.randint(30 if hour == 6 else 0, 59)
            self._push(self._at(hour, minute) + timedelta(seconds=self.rnd.randint(0, 59)), self._new_order)

    def _line(self):
        size = self.rnd.choices(self.sizes, self.size_weights)[0]
        extra = []
        if self.toppings and size.item.option_groups.filter(name="Topping").exists():
            if self.rnd.random() < 0.12:
                extra = [self.toppings[0].pk]
            elif self.rnd.random() < 0.07:
                extra = [self.toppings[1].pk]
        return {"item": size.item_id, "size": size.pk, "options": extra,
                "quantity": 2 if self.rnd.random() < 0.15 else 1}

    def _new_order(self):
        from apps.orders import services
        from apps.orders.models import Order

        n_lines = self.rnd.choices([1, 2, 3], [70, 25, 5])[0]
        table = self.rnd.choice(self.tables)
        server = self.rnd.choice(self._working("phuc_vu", self.clock.now))
        payload = {"table": table.pk, "note": "", "lines": [self._line() for _ in range(n_lines)]}
        try:
            result, _ = services.submit_order(self.u[server], key(), payload)
        except Exception:
            return  # thiếu nguyên liệu: khách chọn món khác hoặc về
        order = Order.objects.get(pk=result["order_id"])
        self.stats["orders"] += 1
        r = self.rnd.random()
        if r < 0.03:  # khách đổi món khi quầy chưa pha
            self._push(self.clock.now + timedelta(minutes=1), self._change_item, order.pk, server)
        elif r < 0.04:
            self._push(self.clock.now + timedelta(minutes=2), self._move_table, order.pk, server)
        cups = sum(line["quantity"] for line in payload["lines"])
        start = max(self.clock.now + timedelta(minutes=1), self._next_barista_slot())
        done = start + timedelta(minutes=cups * MINUTES_PER_CUP * self.rnd.uniform(0.8, 1.3) + 1)
        self._book_barista(done)
        self._push(done, self._complete, order.pk)

    def _next_barista_slot(self):
        now = self.clock.now
        working = self._working("pha_che", now)
        free = [self.barista_free.get(n, now) for n in working]
        return min(free) if free else now

    def _book_barista(self, until):
        now = self.clock.now
        working = self._working("pha_che", now)
        name = min(working, key=lambda n: self.barista_free.get(n, now))
        self.barista_free[name] = max(until, self.barista_free.get(name, now))

    def _change_item(self, order_id, server):
        from apps.orders import adjustments
        from apps.orders.models import Order

        order = Order.objects.get(pk=order_id)
        line = order.lines.filter(done_quantity=0).first()
        if line is None:
            return
        new = self._line()
        new["quantity"] = line.quantity
        pending_today = self.today and self.clock.now > self.real_now - timedelta(minutes=50)
        try:
            req, _ = adjustments.create_request(self.u[server], key(), {
                "order": order.pk, "kind": "doi_mon", "line": line.pk, "cups": line.quantity, "new_line": new,
                "reason": self.reasons["Khách đổi ý"].pk})
        except Exception:
            return
        if pending_today and not getattr(self, "left_pending", False):
            self.left_pending = True  # để lại một yêu cầu chờ Chủ quán duyệt
            return
        self.clock.tick(1)
        self._decide(req["request"])

    def _decide(self, request_id):
        from apps.orders import adjustments

        try:
            adjustments.decide(self.u["chuquan"], key(), request_id, True)
        except Exception:  # món mới không đủ nguyên liệu: Chủ quán từ chối, khách giữ món cũ
            adjustments.decide(self.u["chuquan"], key(), request_id, False, "Món mới hết nguyên liệu")

    def _move_table(self, order_id, server):
        from apps.orders import adjustments
        from apps.orders.models import Order

        order = Order.objects.get(pk=order_id)
        if order.status in (Order.Status.PAID, Order.Status.CANCELLED):
            return
        target = self.rnd.choice([t for t in self.tables if t.pk != order.table_id])
        try:
            req, _ = adjustments.create_request(self.u[server], key(), {
                "order": order.pk, "kind": "chuyen_ban", "target_table": target.pk,
                "reason": self.reasons["Khách gộp bàn"].pk})
            self.clock.tick(1)
            adjustments.decide(self.u["chuquan"], key(), req["request"], True)
        except Exception:
            pass

    def _complete(self, order_id, tries=0):
        from apps.orders import services
        from apps.orders.models import Order

        order = Order.objects.get(pk=order_id)
        if order.status == Order.Status.CANCELLED or order.pending_request() is not None:
            if order.pending_request() is not None and not self.today and tries < 10:  # chờ duyệt xong mới pha
                self._push(self.clock.now + timedelta(minutes=2), self._complete, order_id, tries + 1)
            return
        barista = self.rnd.choice(self._working("pha_che", self.clock.now))
        for line in order.lines.all():
            left = line.quantity - line.done_quantity - line.cancelled_quantity
            if left > 0:
                services.complete_line(self.u[barista], key(), line.pk, left, line.done_quantity)
                self.stats["cups"] += left
        if self.rnd.random() < 0.006:  # pha sai, khách không nhận: hủy sau pha chế
            self._push(self.clock.now + timedelta(minutes=1), self._cancel_after_prep, order_id)
            return
        self._push(self.clock.now + timedelta(minutes=self.rnd.randint(1, 3)), self._serve, order_id)

    def _cancel_after_prep(self, order_id):
        from apps.orders import adjustments
        from apps.orders.models import Order

        order = Order.objects.get(pk=order_id)
        line = order.lines.filter(done_quantity__gt=0).first()
        try:
            req, _ = adjustments.create_request(self.u["phucvu"], key(), {
                "order": order.pk, "kind": "huy_mon", "line": line.pk, "cups": 1, "reason": self.reasons["Pha hỏng"].pk})
            self.clock.tick(2)
            adjustments.decide(self.u["chuquan"], key(), req["request"], self.rnd.random() < 0.85)
        except Exception:
            pass
        self._push(self.clock.now + timedelta(minutes=1), self._serve, order_id)

    def _serve(self, order_id):
        from apps.orders import services
        from apps.orders.models import Order, OrderLine

        order = Order.objects.get(pk=order_id)
        server = self.rnd.choice(self._working("phuc_vu", self.clock.now))
        for line in order.lines.filter(status=OrderLine.Status.DONE):
            services.serve_line(self.u[server], key(), line.pk)
        self._push(self.clock.now + timedelta(minutes=self.rnd.randint(12, 45)), self._pay, order_id, 0)

    def _pay(self, order_id, tries):
        from apps.orders import payments
        from apps.orders.models import Order

        order = Order.objects.get(pk=order_id)
        if order.status in (Order.Status.PAID, Order.Status.CANCELLED):
            return
        method = self.rnd.choices(["tien_mat", "chuyen_khoan"], [55, 45])[0]
        cashier = self.rnd.choice(self._working("thu_ngan", self.clock.now))
        try:
            payments.pay_table(self.u[cashier], key(), order.table_id, method, transfer_confirmed=True)
        except Exception:
            if tries < 6:
                self._push(self.clock.now + timedelta(minutes=8), self._pay, order_id, tries + 1)

    def _waste(self):
        from apps.inventory import operations as ops

        name, qty, reason, note = self.rnd.choice([
            ("Sữa tươi", 1000, "do_vo", "Rơi hộp sữa khi xếp tủ"), ("Sữa tươi", 300, "hu_hong", "Sữa chua, bỏ phần đã mở"),
            ("Cà phê rang xay", 60, "pha_hong", "Chỉnh cối xay, bỏ ba lần chiết"),
            ("Đào ngâm", 400, "hu_hong", "Hộp móp, phồng nắp"), ("Ly nhựa", 10, "hu_hong", "Ly nứt khi tháo cây"),
            ("Trân châu", 150, "pha_hong", "Nấu quá lửa"), ("Kem muối", 200, "hu_hong", "Kem tách nước")])
        ing = self.ing[name]
        ing.stock.refresh_from_db()
        if ing.stock.physical >= qty:
            ops.record_waste(self.u["phache"], key(), ing.pk, qty, reason, note)

    def _cancel_paid(self):
        from apps.orders import adjustments
        from apps.orders.models import Order
        from apps.shifts import services as shifts
        from apps.shifts.models import Refund

        paid = list(Order.objects.filter(shift=self.shift, status=Order.Status.PAID).order_by("-created_at")[:5])
        if not paid:
            return
        try:
            req = adjustments.create_request(self.u["thungan"], key(), {
                "order": paid[0].pk, "kind": "huy_hoa_don", "reason": self.reasons["Khách đổi ý"].pk})[0]
            adjustments.decide(self.u["chuquan"], key(), req["request"], True)
            refund = Refund.objects.get(request_id_ref=req["request"])
            shifts.confirm_refund(self.u["thungan"], key(), refund.pk, "Đã trả khách")
        except Exception:
            pass

    def _backup_slip(self):
        from apps.orders import backup

        rng = backup.issue_range(self.u["chuquan"], self.shift.pk, 101, 110, self.u["thungan"].pk)
        size = self.sizes[0]
        backup.enter_slip(self.u["chuquan"], key(), {
            "number": 101, "sold_at": self.clock.now - timedelta(minutes=30), "restored_at": self.clock.now,
            "method": "tien_mat", "table": self.tables[0].pk,
            "lines": [{"item": size.item_id, "size": size.pk, "options": [], "quantity": 2}]})
        backup.declare_last_used(self.u["chuquan"], rng.pk, 101)

    def _counts(self):
        """Kiểm kê cuối ngày: nhóm trọng yếu mỗi ngày, cả kho vào Chủ nhật. Số đếm lệch sổ một chút như thật."""
        from apps.inventory import operations as ops
        from apps.inventory.models import Ingredient

        items = Ingredient.objects.all() if self.day.weekday() == 6 else Ingredient.objects.filter(is_critical=True)
        for ing in items:
            ing.stock.refresh_from_db()
            physical = ing.stock.physical
            if physical <= 0:
                continue
            drift = Decimal(str(self.rnd.uniform(-0.008, 0.004)))
            counted = (physical * (1 + drift)).quantize(Decimal(1))
            reason = ""
            if self.today and ing.name == "Sữa đặc":  # một lần lệch nhiều, chờ Chủ quán xác nhận
                counted, reason = (physical * Decimal("0.88")).quantize(Decimal(1)), "Hộp sữa bị đổ ở kho, chưa ghi hao hụt"
            try:
                ops.submit_count(self.u["phache2"], key(), ing.pk, str(counted), reason)
            except Exception:
                pass

    def _close_day(self):
        from apps.orders import payments
        from apps.orders.models import Order
        from apps.shifts import services as shifts

        if self.today:
            return
        for order in Order.objects.filter(shift=self.shift, status=Order.Status.SERVED):
            try:
                payments.pay_table(self.u["thungan"], key(), order.table_id, "tien_mat")
            except Exception:
                pass
        for order in Order.objects.filter(shift=self.shift).exclude(status__in=[Order.Status.PAID, Order.Status.CANCELLED]):
            self._finish_left_over(order)
        shifts.close_shift(self.u["thungan"], self.shift.pk)
        f = shifts.figures(self.shift)
        short = self.rnd.choice([0, 0, 0, 0, 10000, 20000, 50000]) if self.offset % 4 == 1 else 0
        self.clock.tick(15)
        shifts.submit_report(self.u["thungan"], self.shift.pk, f["expected_cash"] - short, f["revenue_transfer"],
                             f["refunds_transfer"])

    def _finish_left_over(self, order):
        from apps.orders import payments, services
        from apps.orders.models import OrderLine

        req = order.pending_request()
        if req is not None:
            self._decide(req.pk)
            order.refresh_from_db()
        for line in order.lines.all():
            left = line.quantity - line.done_quantity - line.cancelled_quantity
            if left > 0:
                services.complete_line(self.u["phache2"], key(), line.pk, left, line.done_quantity)
        for line in order.lines.filter(status=OrderLine.Status.DONE):
            services.serve_line(self.u["phucvu2"], key(), line.pk)
        try:
            payments.pay_table(self.u["thungan"], key(), order.table_id, "tien_mat")
        except Exception:
            pass

    def _nightly(self):
        from apps.core import periodic

        if not self.today:
            periodic.run_all(self.clock.now)
        if self.offset % 7 == 0:
            self.out.write(f"  {self.day:%d/%m}: {self.stats['orders']} đơn")

    # ---------------- lịch làm và kết thúc ----------------

    def finish(self):
        from apps.core import periodic

        self.clock.now = self.real_now
        self._schedule()
        self._live_now()
        periodic.run_all(self.real_now)
        compact_history()

    def _live_now(self):
        """Việc đang chờ lúc chạy lệnh để thử ngay: một yêu cầu đổi món chờ duyệt, một kiểm kê lệch chờ xác nhận."""
        from apps.inventory import operations as ops
        from apps.inventory.models import StockCount
        from apps.orders.models import Order

        servers = self._working("phuc_vu", self.clock.now)
        open_now = 7 <= timezone.localtime(self.real_now).hour < 21
        if open_now and not getattr(self, "left_pending", False):  # chỉ khi quán đang mở
            order = Order.objects.filter(shift=self.shift, status=Order.Status.SENT).order_by("-created_at").first()
            if order is None:
                self._new_order()
                order = Order.objects.filter(shift=self.shift, status=Order.Status.SENT).order_by("-created_at").first()
            if order is not None:
                self._change_item(order.pk, self.rnd.choice(servers))
        milk = self.ing["Sữa đặc"]
        if not StockCount.objects.filter(ingredient=milk, status=StockCount.Status.PENDING).exists():
            milk.stock.refresh_from_db()
            if milk.stock.physical > 0:
                ops.submit_count(self.u["phache2"], key(), milk.pk, str((milk.stock.physical * Decimal("0.88")).quantize(Decimal(1))),
                                 "Hộp sữa bị đổ ở kho, chưa ghi hao hụt")

    def _schedule(self):
        """Lịch làm: tuần này đã xếp và công bố, tuần sau nhân viên đã đăng ký, chờ Chủ quán xếp."""
        from apps.schedule import services as sched
        from apps.schedule.models import WorkShift

        this_week = sched.week_start(self.real_now.date())
        for week in (this_week, this_week + timedelta(days=7)):
            for d in range(7):
                day = week + timedelta(days=d)
                WorkShift.objects.get_or_create(store=self.store, date=day, name="Ca sáng",
                                                defaults={"start": time(6, 30), "end": time(14, 30)})
                WorkShift.objects.get_or_create(store=self.store, date=day, name="Ca chiều",
                                                defaults={"start": time(14, 0), "end": time(22, 0)})
            sched.apply_suggested_needs(week, self.u["chuquan"])
            before_deadline = sched.deadline_for(week) - timedelta(days=1)
            usual = {"phache": ("Ca sáng", "pha_che"), "phache2": ("Ca chiều", "pha_che"),
                     "phucvu": ("Ca sáng", "phuc_vu"), "phucvu2": ("Ca chiều", "phuc_vu"), "thungan": ("Ca sáng", "thu_ngan")}
            for name, (shift_name, role) in usual.items():
                choices = {}
                for ws in WorkShift.objects.filter(date__gte=week, date__lt=week + timedelta(days=7)):
                    if ws.name == shift_name and self.rnd.random() < 0.9:
                        choices[ws.pk] = role
                    elif name == "phache2" and ws.name == "Ca sáng" and ws.date.weekday() >= 5:
                        choices[ws.pk] = role
                if choices:
                    sched.register(self.u[name], choices, now=before_deadline)
            if week == this_week:
                sched.auto_assign(self.u["chuquan"], week)
                sched.publish(self.u["chuquan"], week)
