"""Tạo bộ dữ liệu NGHIỆM THU: 14 ngày vận hành mẫu đi qua đúng các hàm nghiệp vụ của hệ thống.

Chạy trên một cơ sở dữ liệu trống riêng để không đụng dữ liệu đang dùng, ví dụ (PowerShell):

    $env:SQLITE_NAME = "nghiem_thu.sqlite3"
    .venv\\Scripts\\python.exe manage.py migrate
    .venv\\Scripts\\python.exe manage.py tao_du_lieu_nghiem_thu
    .venv\\Scripts\\python.exe manage.py runserver

Đồng hồ được lùi về 14 ngày trước rồi tiến dần theo từng thao tác, nên mọi giao dịch có thời điểm thật:
nhập hàng, mở ca, nhận đơn, pha, phục vụ, thu tiền, điều chỉnh, hủy hóa đơn và hoàn tiền, phiếu dự phòng,
kiểm kê, kết ca và báo cáo cuối ca. Đây là dữ liệu mẫu, không phải số liệu thật của quán.
"""

import random
import tempfile
import uuid
from datetime import timedelta
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.test import override_settings
from django.utils import timezone

DAYS = 14
# Lịch nhập mẫu: tên nguyên liệu → (nhà cung cấp, chu kỳ ngày, ngày lệch, lượng mỗi lần, hạn in trên bao bì tính từ
# ngày nhập (các giá trị có thể), đơn giá mỗi đơn vị). Kem muối nhập dư so với lượng dùng để báo cáo thấy hao hụt
# do hết hạn; đào ngâm mỗi lô một hạn nên lô nhập sau có thể hết hạn trước (FEFO khác FIFO).
SUPPLY = {
    "Sữa tươi": ("Đại lý sữa An Phát", 2, 1, 3000, (6, 7, 8), 32),
    "Sữa đặc": ("Đại lý sữa An Phát", 7, 4, 2660, (150, 180, 200), 62),
    "Kem muối": ("Đại lý sữa An Phát", 5, 3, 1000, (5,), 115),
    "Cà phê rang xay": ("Xưởng rang Hồng Lam", 6, 3, 2000, (45, 60), 260),
    "Trà đen": ("Xưởng rang Hồng Lam", 10, 6, 1000, (200, 365), 210),
    "Bột matcha": ("Xưởng rang Hồng Lam", 7, 5, 200, (150,), 1150),
    "Đào ngâm": ("Tạp hóa Bích Ngọc", 5, 2, 2460, (35, 90, 240), 95),
    "Trân châu": ("Tạp hóa Bích Ngọc", 7, 3, 1000, (150, 180), 45),
    "Ly nhựa": ("Bao bì Thành Công", 7, 4, 250, (None,), 900),
}
# Sự cố hao hụt mẫu: ngày thứ → (nguyên liệu, lượng, lý do, ghi chú).
SPILLS = {3: ("Sữa tươi", 500, "do_vo", "Rơi hộp sữa khi xếp tủ"), 6: ("Đào ngâm", 300, "hu_hong", "Hộp móp, phồng nắp"),
          9: ("Cà phê rang xay", 60, "pha_hong", "Chỉnh cối xay, bỏ ba lần chiết")}


def key():
    return uuid.uuid4().hex


class Clock:
    def __init__(self, start):
        self.now = start

    def __call__(self):
        return self.now

    def at(self, day, hour, minute=0):
        self.now = timezone.make_aware(timezone.datetime.combine(day, timezone.datetime.min.time())
                                       + timedelta(hours=hour, minutes=minute))
        return self.now

    def tick(self, minutes):
        self.now += timedelta(minutes=minutes)
        return self.now


class Command(BaseCommand):
    help = "Tạo 14 ngày vận hành mẫu qua các hàm nghiệp vụ để nghiệm thu trên máy cá nhân (chỉ cơ sở dữ liệu trống)."

    def handle(self, *args, **options):
        from apps.catalog.models import MenuItem

        if MenuItem.objects.exists():
            raise CommandError("Chỉ chạy trên cơ sở dữ liệu trống (đặt SQLITE_NAME sang tệp mới rồi migrate).")
        real_now = timezone.now()
        first_day = timezone.localdate() - timedelta(days=DAYS)
        clock = Clock(real_now)
        clock.at(first_day, 6, 0)
        with mock.patch("django.utils.timezone.now", clock):
            call_command("tao_du_lieu_mau", stdout=self.stdout)
            self.simulate(clock, first_day, real_now)
        self.stdout.write(self.style.SUCCESS(
            f"Đã tạo {DAYS} ngày vận hành mẫu đến hôm nay. Đăng nhập bằng tài khoản demo_* (mật khẩu demo-lam-2026)."))

    def simulate(self, clock, first_day, real_now):
        from apps.accounts.models import User
        from apps.catalog.models import ItemSize, MenuItem, Table
        from apps.core import periodic
        from apps.catalog.models import Option
        from apps.inventory import operations as ops
        from apps.inventory.models import Ingredient, StockLot, Supplier
        from apps.orders import adjustments, backup, payments, services
        from apps.orders.models import AdjustmentReason, Order
        from apps.shifts import services as shifts
        from apps.shifts.models import Refund, Shift
        from apps.staff.models import Attendance

        rnd = random.Random(2026)
        u = {name: User.objects.get(username=f"demo_{name}") for name in
             ("chuquan", "thungan", "phucvu", "phache")}
        from apps.core.models import Store

        store = Store.get_default()
        suppliers = {name: Supplier.objects.create(store=store, name=name)
                     for name in dict.fromkeys(v[0] for v in SUPPLY.values())}
        by_name = {i.name: i for i in Ingredient.objects.all()}
        toppings = list(Option.objects.filter(group__name="Topping"))
        tables = list(Table.objects.all())
        sizes = list(ItemSize.objects.select_related("item").filter(item__status=MenuItem.Status.ON_SALE))
        changed = AdjustmentReason.objects.get(name="Khách đổi ý")
        critical = list(Ingredient.objects.filter(is_critical=True))
        media = tempfile.mkdtemp()

        for offset in range(DAYS + 1):
            day = first_day + timedelta(days=offset)
            is_today = offset == DAYS
            clock.at(day, 6, 0)
            if is_today and clock.now > real_now:
                clock.now = real_now - timedelta(minutes=30)
            shift = Shift.objects.filter(starts_at__date=day).first() or Shift.objects.create(
                store=store, name="Ca ngày", starts_at=clock.now, ends_at=clock.now + timedelta(hours=16), approver=u["chuquan"],
                payment_authorizer=u["thungan"])
            shift.ends_at = clock.now + timedelta(hours=16)
            shift.name = "Ca ngày"
            shift.save()
            for role, name in (("pha_che", "phache"), ("phuc_vu", "phucvu"), ("thu_ngan", "thungan")):
                Attendance.objects.create(store=store, user=u[name], role=role, clock_in=clock.tick(1))
            shifts.add_cash_entry(u["thungan"], key(), shift.pk, "dau_ca", 500000)
            if not is_today:  # đầu ngày hủy lô đã quá hạn (hôm nay để lại cho Chủ quán thấy cảnh báo)
                for lot in StockLot.objects.filter(remaining__gt=0, expiry_date__lt=day):
                    ops.dispose_lot(u["phache"], key(), lot.pk)
            due = {}
            for name, (sup, cycle, phase, qty, shelf, price) in SUPPLY.items():
                if offset % cycle == phase and name in by_name:
                    days_left = rnd.choice(shelf)
                    due.setdefault(sup, []).append({
                        "ingredient": by_name[name].pk, "quantity": str(qty), "unit_price": price,
                        "expiry_date": (day + timedelta(days=days_left)).isoformat() if days_left else None,
                        "supplier_lot": f"{rnd.randint(10, 99)}{day:%m%d}" if days_left else ""})
            with override_settings(MEDIA_ROOT=media):  # nhập hàng buổi sáng, có ảnh hóa đơn
                for sup, lines in due.items():
                    clock.tick(5)
                    ops.create_receipt(u["phache"], key(), suppliers[sup].pk, lines,
                                       "tra_ngay" if offset % 2 else "tra_sau",
                                       invoice_photo=SimpleUploadedFile("hd.jpg", b"\xff\xd8\xffjpeg", content_type="image/jpeg"),
                                       paid_source="chuyen_khoan")
            if offset in SPILLS:
                name, qty, reason, note = SPILLS[offset]
                clock.at(day, 10, 15)
                ops.record_waste(u["phache"], key(), by_name[name].pk, qty, reason, note)
            last_hour = min(20, timezone.localtime(real_now).hour - 1) if is_today else 20
            busy = 3 if day.weekday() >= 5 else 2
            orders = []
            for hour in range(7, last_hour + 1):  # hôm nay chỉ tới giờ hiện tại, không tạo giao dịch tương lai
                for _ in range(rnd.randint(0, busy + (2 if hour in (8, 9, 19, 20) else 0))):
                    clock.at(day, hour, rnd.randint(0, 50))
                    size = rnd.choice(sizes)
                    extra = ([rnd.choice(toppings).pk] if toppings and rnd.random() < 0.25
                             and size.item.option_groups.filter(name="Topping").exists() else [])
                    payload = {"table": rnd.choice(tables).pk, "note": "",
                               "lines": [{"item": size.item_id, "size": size.pk, "options": extra,
                                          "quantity": rnd.randint(1, 2)}]}
                    try:
                        result, _ = services.submit_order(u["phucvu"], key(), payload)
                    except Exception:  # thiếu nguyên liệu: bỏ qua đơn này như khách đổi ý
                        continue
                    orders.append(Order.objects.get(pk=result["order_id"]))
            for order in sorted(orders, key=lambda o: o.created_at):
                if is_today and rnd.random() < 0.3:
                    continue  # một số đơn hôm nay còn đang mở
                line = order.lines.get()
                clock.now = order.created_at + timedelta(minutes=rnd.randint(4, 16))
                services.complete_line(u["phache"], key(), line.pk, line.quantity, 0)
                clock.tick(2)
                services.serve_line(u["phucvu"], key(), line.pk)
                clock.tick(rnd.randint(10, 40))
                try:
                    payments.pay_table(u["thungan"], key(), order.table_id, rnd.choice(["tien_mat", "chuyen_khoan"]),
                                       transfer_confirmed=True)
                except Exception:
                    pass  # bàn còn đơn khác chưa phục vụ: thu cùng lần sau
            for order in Order.objects.filter(shift=shift, status=Order.Status.SERVED):
                try:
                    payments.pay_table(u["thungan"], key(), order.table_id, "tien_mat")
                except Exception:
                    pass
            paid = list(Order.objects.filter(shift=shift, status=Order.Status.PAID))
            if offset % 5 == 2 and paid:  # hủy hóa đơn đã thanh toán, hoàn tiền trong ca
                clock.at(day, 21, 0)
                req = adjustments.create_request(u["thungan"], key(), {"order": paid[0].pk, "kind": "huy_hoa_don",
                                                                       "reason": changed.pk})[0]
                adjustments.decide(u["chuquan"], key(), req["request"], True)
                refund = Refund.objects.get(request_id_ref=req["request"])
                shifts.confirm_refund(u["thungan"], key(), refund.pk, "Đã trả khách")
            if offset == 4:  # một lần mất mạng, bán bằng phiếu dự phòng
                clock.at(day, 15, 0)
                rng = backup.issue_range(u["chuquan"], shift.pk, 101, 110, u["thungan"].pk)
                size = sizes[0]
                backup.enter_slip(u["chuquan"], key(), {
                    "number": 101, "sold_at": clock.now - timedelta(minutes=30), "restored_at": clock.now,
                    "method": "tien_mat", "table": tables[0].pk,
                    "lines": [{"item": size.item_id, "size": size.pk, "options": [], "quantity": 2}]})
                backup.declare_last_used(u["chuquan"], rng.pk, 101)
            if is_today:
                break
            clock.at(day, 21, 30)
            for ing in critical:  # kiểm kê nhóm trọng yếu cuối ngày, khớp sổ
                ing.stock.refresh_from_db()
                if ing.stock.physical >= 0:
                    ops.submit_count(u["phache"], key(), ing.pk, str(ing.stock.physical))
                else:  # sổ âm (ví dụ nhập bù phiếu dự phòng bán lúc mất mạng): đếm thật được 0
                    ops.submit_count(u["phache"], key(), ing.pk, "0", "Sổ âm sau khi nhập bù phiếu dự phòng; đếm thật được 0")
            for att in Attendance.objects.filter(clock_out__isnull=True):
                att.clock_out = clock.tick(1)
                att.save(update_fields=["clock_out"])
            clock.at(day, 22, 0)
            shifts.close_shift(u["thungan"], shift.pk)
            f = shifts.figures(shift)
            short = 20000 if offset % 6 == 3 else 0  # vài ngày thiếu tiền nhỏ
            clock.tick(20)
            shifts.submit_report(u["thungan"], shift.pk, f["expected_cash"] - short, f["revenue_transfer"],
                                 f["refunds_transfer"])
        clock.now = real_now
        periodic.run_all(real_now)
