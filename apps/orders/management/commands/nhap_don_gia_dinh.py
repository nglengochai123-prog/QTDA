"""Nhập đơn hàng giả định từ tệp Excel (sheet Don_hang và Chi_tiet_mon) thành đơn đã thanh toán.

Chỉ dùng cho cơ sở dữ liệu chạy thử: mỗi ngày tạo một ca đã kết kèm báo cáo cuối ca, đơn và thanh toán giữ đúng giờ
trong tệp, dòng món lưu định mức hiện hành. Không ghi biến động kho (tệp không có nhập hàng và kiểm kê).
"""

import random
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime, time, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.catalog.models import ItemSize, Option, Table
from apps.core import xlsx_read
from apps.core.models import Store
from apps.inventory.models import RecipeVersion
from apps.inventory.services import ingredient_usage
from apps.orders.models import Order, OrderLine, OrderLineOption, Payment
from apps.shifts.models import Shift, ShiftReport

PREFIX = "GD-"
NOTE = "Dữ liệu giả định nhập từ tệp"


def _when(serial):
    base = datetime(1899, 12, 30) + timedelta(days=float(serial))
    return timezone.make_aware(base.replace(microsecond=0), timezone.get_current_timezone())


@contextmanager
def _keep_timestamps(*models):
    """Cho phép ghi created_at/updated_at theo giờ trong tệp thay vì giờ chạy lệnh."""
    saved = []
    for model in models:
        for f in model._meta.concrete_fields:
            if getattr(f, "auto_now_add", False) or getattr(f, "auto_now", False):
                saved.append((f, f.auto_now_add, f.auto_now))
                f.auto_now_add = f.auto_now = False
    try:
        yield
    finally:
        for f, add, now in saved:
            f.auto_now_add, f.auto_now = add, now


class Command(BaseCommand):
    help = "Nhập đơn hàng giả định (sheet Don_hang, Chi_tiet_mon) vào cơ sở dữ liệu CHẠY THỬ."

    def add_arguments(self, parser):
        parser.add_argument("tep")
        parser.add_argument("--chay-thu", action="store_true",
                            help="Xác nhận đây là cơ sở dữ liệu chạy thử, không phải dữ liệu thật của quán.")

    def handle(self, tep, chay_thu, **options):
        if not chay_thu:
            raise CommandError("Thêm --chay-thu để xác nhận đang nhập dữ liệu giả định vào cơ sở dữ liệu chạy thử.")
        if Order.objects.filter(code__startswith=PREFIX).exists():
            raise CommandError("Đã có đơn giả định trong cơ sở dữ liệu này.")
        sheets = {e[0]: e for e in xlsx_read.sheets(tep)}
        if "Don_hang" not in sheets or "Chi_tiet_mon" not in sheets:
            raise CommandError("Tệp cần có sheet Don_hang và Chi_tiet_mon.")

        orders = []
        it = xlsx_read.rows(sheets["Don_hang"])
        next(it)
        for r in it:
            if r and r[0]:
                orders.append({"code": r[0], "created": _when(r[1]), "paid": _when(r[2]), "method": r[3],
                               "total": int(float(r[7]))})
        lines = defaultdict(list)
        it = xlsx_read.rows(sheets["Chi_tiet_mon"])
        next(it)
        for r in it:
            if r and r[1]:
                lines[r[1]].append({"item": r[4], "size": r[5], "qty": int(float(r[6])), "price": int(float(r[7])),
                                    "topping": r[8], "extra": int(float(r[9] or 0)), "sugar": r[10], "ice": r[11]})
        self._import(orders, lines)

    @transaction.atomic
    def _import(self, orders, lines):
        store = Store.get_default()
        owner = User.objects.filter(role=Role.CHU_QUAN).first()
        server = User.objects.filter(role=Role.PHUC_VU).first() or owner
        cashier = User.objects.filter(role=Role.THU_NGAN).first() or owner
        tables = list(Table.objects.filter(store=store, is_active=True))
        if owner is None or not tables:
            raise CommandError("Cần có tài khoản Chủ quán và bàn (chạy tao_du_lieu_mau trước).")
        sizes = {(s.item.name, s.name): s for s in ItemSize.objects.select_related("item")}
        opts = {(o.group.name, o.name): o for o in Option.objects.select_related("group")}
        versions = {}
        usage_cache = {}
        rng = random.Random(20260401)
        missing = defaultdict(int)

        by_day = defaultdict(list)
        for o in orders:
            by_day[timezone.localtime(o["created"]).date()].append(o)

        with _keep_timestamps(Shift, ShiftReport, Order, OrderLine, Payment):
            n_orders = n_lines = 0
            for day in sorted(by_day):
                tz = timezone.get_current_timezone()
                start = timezone.make_aware(datetime.combine(day, time(6)), tz)
                end = max([timezone.make_aware(datetime.combine(day, time(23)), tz)]
                          + [o["paid"] + timedelta(minutes=5) for o in by_day[day]])
                cash = sum(o["total"] for o in by_day[day] if o["method"] == "Tiền mặt")
                transfer = sum(o["total"] for o in by_day[day] if o["method"] != "Tiền mặt")
                shift = Shift.objects.create(
                    store=store, name="Ca cả ngày (giả định)", starts_at=start, ends_at=end, approver=owner,
                    payment_authorizer=cashier, status=Shift.Status.CLOSED, closed_at=end, closed_by=cashier,
                    closed_cash_revenue=cash, closed_transfer_revenue=transfer, created_at=start, updated_at=end)
                ShiftReport.objects.create(store=store, shift=shift, counted_cash=cash, transfer_received=transfer,
                                           incidents=NOTE, submitted_by=cashier, created_at=end, updated_at=end)
                for o in by_day[day]:
                    table = rng.choice(tables)
                    method = Payment.Method.CASH if o["method"] == "Tiền mặt" else Payment.Method.TRANSFER
                    payment = Payment.objects.create(
                        store=store, table=table, method=method, amount=o["total"], cashier=cashier, shift=shift,
                        operation_key=f"gd-tt-{o['code']}", created_at=o["paid"], updated_at=o["paid"])
                    order = Order.objects.create(
                        store=store, code=o["code"], table=table, status=Order.Status.PAID, note=NOTE,
                        created_by=server, operation_key=f"gd-{o['code']}", total=o["total"], shift=shift,
                        payment=payment, created_at=o["created"], updated_at=o["paid"])
                    n_orders += 1
                    done = o["created"] + (o["paid"] - o["created"]) / 3
                    for pos, l in enumerate(lines.get(o["code"], []), start=1):
                        size = sizes.get((l["item"], l["size"]))
                        if size is None:
                            missing[f"{l['item']} {l['size']}"] += l["qty"]
                            continue
                        chosen = []
                        for group, name in (("Đường", l["sugar"]), ("Đá", l["ice"])):
                            if (group, name) in opts:
                                chosen.append(opts[(group, name)])
                        if l["topping"] and l["topping"] != "Không":
                            for name in l["topping"].split(" + "):
                                if ("Topping", name.strip()) in opts:
                                    chosen.append(opts[("Topping", name.strip())])
                                else:
                                    missing[f"Topping {name}"] += l["qty"]
                        if size.item_id not in versions:
                            versions[size.item_id] = RecipeVersion.objects.current_for(size.item)
                        version = versions[size.item_id]
                        ukey = (size.pk, tuple(sorted(x.pk for x in chosen)))
                        if ukey not in usage_cache:
                            usage_cache[ukey] = ({str(k): str(v) for k, v in
                                                  ingredient_usage(version, size, chosen).items()} if version else {})
                        line = OrderLine.objects.create(
                            order=order, position=pos, item=size.item, size=size, item_name=size.item.name,
                            size_name=size.name, unit_price=l["price"] + l["extra"], quantity=l["qty"],
                            done_quantity=l["qty"], status=OrderLine.Status.SERVED, done_at=done,
                            served_at=done + timedelta(minutes=2), served_by=server, recipe_version=version,
                            usage_per_unit=usage_cache[ukey], created_at=o["created"], updated_at=o["paid"])
                        OrderLineOption.objects.bulk_create([
                            OrderLineOption(line=line, option=x, name=x.name,
                                            extra_price=l["extra"] if x.group.name == "Topping" and
                                            " + " not in l["topping"] else x.extra_price)
                            for x in chosen])
                        n_lines += 1
        self.stdout.write(self.style.WARNING(
            f"Đã nhập {n_orders} đơn giả định, {n_lines} dòng món, {len(by_day)} ca đã kết."))
        if missing:
            self.stdout.write("Không khớp thực đơn (bỏ qua): " + ", ".join(f"{k}: {v}" for k, v in missing.items()))
