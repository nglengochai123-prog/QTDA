"""Cho quán có khách ngay lúc chạy lệnh để thử màn Tổng quan ca, trên dữ liệu mô phỏng (cần tài khoản demo_*).

    .venv\\Scripts\\python.exe manage.py tao_ban_co_khach

Dùng bàn đang trống, đi qua chính các hàm nghiệp vụ: hai bàn chờ pha (một bàn đã chờ lâu), một bàn có món pha xong
chờ mang ra, hai bàn đã phục vụ chờ thu tiền, một bàn có yêu cầu đổi món chờ Chủ quán duyệt. Chưa có ca trong giờ
hiện tại thì mở "Ca ngày" và cho nhân viên demo chấm công vào. Chạy lại lúc nào cũng được; hết bàn trống thì dừng.
Đây là dữ liệu giả lập.
"""

import random
from datetime import timedelta
from unittest import mock

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from .tao_du_lieu_nghiem_thu import Clock, key

# (phút trước khi chạy lệnh lúc gửi đơn, đến bước nào): pha xong sau 8 phút, mang ra sau 2 phút nữa.
STAGES = [(22, "cho_pha"), (3, "cho_pha"), (9, "mang_ra"), (34, "thanh_toan"), (52, "thanh_toan"), (6, "doi_mon")]


class Command(BaseCommand):
    help = "Tạo vài bàn đang có khách ở các bước khác nhau ngay lúc chạy lệnh (dữ liệu mô phỏng)."

    def handle(self, *args, **options):
        from apps.accounts.models import User

        self.u = {u.username.removeprefix("demo_"): u for u in User.objects.filter(username__startswith="demo_")}
        if not {"chuquan", "phucvu", "phache", "thungan"} <= set(self.u):
            raise CommandError("Chỉ chạy trên dữ liệu mô phỏng (thiếu tài khoản demo_*).")
        self.rnd = random.Random()
        now = timezone.now()
        clock = Clock(now - timedelta(minutes=max(m for m, _ in STAGES) + 5))
        with mock.patch("django.utils.timezone.now", clock):
            self._shift_and_people(now, clock)
            made = []
            for minutes, stage in STAGES:
                table = self._free_table()
                if table is None:
                    break
                clock.now = now - timedelta(minutes=minutes)
                if self._order(table, stage, clock, now):
                    made.append(f"Bàn {table.code}")
        if not made:
            raise CommandError("Không tạo được bàn nào: hết bàn trống, thiếu nguyên liệu, hoặc thực đơn mới tạo chưa tới "
                               "một giờ (đơn được ghi lùi giờ để có bàn đã ngồi lâu).")
        self.stdout.write(self.style.SUCCESS(f"Đã có khách ở {', '.join(made)}. Mở Bán hàng, Tổng quan ca để xem."))

    def _shift_and_people(self, now, clock):
        from apps.core.models import Store
        from apps.shifts import services as shifts
        from apps.shifts.models import CashEntry, Shift
        from apps.staff.models import Attendance

        shift = Shift.objects.current(now)
        if shift is None:
            local = timezone.localtime(now)
            start = local.replace(hour=6, minute=0, second=0, microsecond=0)
            if not 6 <= local.hour < 22:  # chạy ngoài giờ mở cửa: ca bắt đầu một tiếng trước
                start = local - timedelta(hours=1)
            shift = Shift.objects.create(store=Store.get_default(), name="Ca ngày", starts_at=start,
                                         ends_at=start + timedelta(hours=16), approver=self.u["chuquan"],
                                         payment_authorizer=self.u["thungan"])
        if not shift.cash_entries.filter(kind=CashEntry.Kind.OPENING).exists():
            shifts.add_cash_entry(self.u["thungan"], key(), shift.pk, CashEntry.Kind.OPENING, 500000)
        for name, role in (("thungan", "thu_ngan"), ("phache", "pha_che"), ("phucvu", "phuc_vu")):
            if not Attendance.objects.filter(user=self.u[name], clock_out__isnull=True).exists():
                Attendance.objects.create(store=Store.get_default(), user=self.u[name], role=role, clock_in=clock.now)

    def _free_table(self):
        from apps.catalog.models import Table
        from apps.orders.models import Order

        busy = (Order.objects.filter(payment__isnull=True)
                .exclude(status__in=[Order.Status.PAID, Order.Status.CANCELLED]).values("table_id"))
        free = list(Table.objects.filter(is_active=True).exclude(pk__in=busy))
        return self.rnd.choice(free) if free else None

    def _lines(self, n):
        from apps.catalog.models import ItemSize, MenuItem
        from apps.orders.services import availability

        left = availability()
        sizes = [s for s in ItemSize.objects.filter(item__status=MenuItem.Status.ON_SALE, is_active=True)
                 if left.get(s.pk) is None or left[s.pk] >= 2]
        return [{"item": s.item_id, "size": s.pk, "options": [], "quantity": self.rnd.choice([1, 1, 2])}
                for s in self.rnd.sample(sizes, min(n, len(sizes)))]

    def _order(self, table, stage, clock, now):
        from apps.orders import adjustments, services
        from apps.orders.models import AdjustmentReason, OrderLine

        lines = self._lines(self.rnd.choice([1, 2, 2, 3]))
        if not lines:
            return False
        try:
            result, _ = services.submit_order(self.u["phucvu"], key(), {"table": table.pk, "note": "", "lines": lines})
        except Exception:
            return False  # thiếu nguyên liệu: bỏ qua bàn này
        order_lines = list(OrderLine.objects.filter(order_id=result["order_id"]))
        if stage == "doi_mon":
            clock.now += timedelta(minutes=1)
            other = self._lines(1)
            reason = AdjustmentReason.objects.filter(name="Khách đổi ý").first() or AdjustmentReason.objects.first()
            if other and reason:
                other[0]["quantity"] = order_lines[0].quantity
                try:
                    adjustments.create_request(self.u["phucvu"], key(), {
                        "order": result["order_id"], "kind": "doi_mon", "line": order_lines[0].pk,
                        "cups": order_lines[0].quantity, "new_line": other[0], "reason": reason.pk})
                except Exception:
                    pass
            return True
        if stage == "cho_pha":
            return True
        clock.now += timedelta(minutes=8)
        for line in order_lines:
            services.complete_line(self.u["phache"], key(), line.pk, line.quantity, 0)
        if stage == "thanh_toan":
            clock.now += timedelta(minutes=2)
            for line in order_lines:
                services.serve_line(self.u["phucvu"], key(), line.pk)
        return True
