"""Kiểm thử đồng thời (NFR-04): nhiều luồng thật cùng ghi một lúc, chạy được trên SQLite và PostgreSQL.

Tình huống: hai đơn tranh phần tồn cuối; gửi lại cùng mã nghiệp vụ cùng lúc; hoàn thành một món nhiều lần;
thanh toán một bàn cùng lúc; hai người duyệt cùng một yêu cầu. Sau mỗi tình huống: không âm kho, không ghi
trùng tiền, không phát sinh hiệu lực hai lần, và `kiem_tra_toan_ven` không báo sai lệch.
"""

import importlib
import threading
import uuid
from datetime import timedelta

from django.db import connection, connections, transaction
from django.test import TransactionTestCase
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.core import integrity
from apps.core.idempotency import OperationKeyError
from apps.inventory import stock
from apps.orders import adjustments, payments, services
from apps.orders.models import AdjustmentReason, AdjustmentRequest, Order, Payment
from apps.orders.tests.helpers import PASSWORD, D, build_menu, cart, levels
from apps.shifts.models import Shift

THREADS = 6


def key():
    return uuid.uuid4().hex


def run_parallel(fn, n=THREADS):
    """Chạy `fn(i)` trên n luồng xuất phát cùng lúc; trả danh sách kết quả hoặc lỗi theo thứ tự luồng."""
    barrier = threading.Barrier(n)
    results = [None] * n

    def worker(i):
        try:
            barrier.wait()
            results[i] = ("ok", fn(i))
        except Exception as error:  # noqa: BLE001 - ghi lại để kiểm tra
            results[i] = ("err", error)
        finally:
            connections.close_all()

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    return results


class ConcurrencyTests(TransactionTestCase):
    @staticmethod
    def _triggers(direction):
        audit = importlib.import_module("apps.audit.migrations.0002_append_only_triggers")
        inventory = importlib.import_module("apps.inventory.migrations.0003_stockmovement_append_only")
        vendor = connection.vendor
        audit_sql = {"up": {"sqlite": audit.SQLITE_UP, "postgresql": audit.POSTGRES_UP},
                     "down": {"sqlite": audit.SQLITE_DOWN, "postgresql": audit.POSTGRES_DOWN}}[direction]
        return audit_sql.get(vendor, []) + (inventory.UP if direction == "up" else inventory.DOWN).get(vendor, [])

    def setUp(self):
        with connection.cursor() as cursor:
            for sql in self._triggers("down") + self._triggers("up"):
                cursor.execute(sql)
        self.d = build_menu(coffee_opening=20, milk_opening=1000)  # cà phê vừa đủ một ly
        mk = lambda name, role: User.objects.create_user(name, password=PASSWORD, role=role)  # noqa: E731
        self.manager = mk("qlca", Role.QUAN_LY_CA)
        self.backup = mk("duphong", Role.QUAN_LY_CA)
        self.cashier = mk("thungan", Role.THU_NGAN)
        now = timezone.now()
        self.shift = Shift.objects.create(store=self.d["store"], name="Ca", starts_at=now - timedelta(hours=1),
                                          ends_at=now + timedelta(hours=4), approver=self.manager,
                                          backup_approver=self.backup, payment_authorizer=self.cashier)

    def tearDown(self):
        with connection.cursor() as cursor:
            for sql in self._triggers("down"):
                cursor.execute(sql)
        super().tearDown()

    def assertClean(self):
        for row in stock.IngredientStock.objects.all():
            self.assertGreaterEqual(row.physical, 0)
            self.assertGreaterEqual(row.physical - row.reserved, 0)
        self.assertEqual(integrity.problems(), [])

    def test_orders_compete_for_last_stock(self):
        results = run_parallel(lambda i: services.submit_order(self.d["waiter"], key(), cart(self.d)))
        ok = [r for r in results if r[0] == "ok"]
        self.assertEqual(len(ok), 1, results)
        self.assertTrue(all(isinstance(r[1], stock.InsufficientStock) for r in results if r[0] == "err"), results)
        self.assertEqual(Order.objects.count(), 1)
        self.assertEqual(levels(self.d["coffee"]), (D(20), D(20), D(0)))
        self.assertClean()

    def test_same_operation_key_sent_concurrently(self):
        op = key()
        results = run_parallel(lambda i: services.submit_order(self.d["waiter"], op, cart(self.d)))
        self.assertEqual(Order.objects.count(), 1)
        ids = {r[1][0]["order_id"] for r in results if r[0] == "ok"}
        self.assertEqual(len(ids), 1, results)
        errors = [r[1] for r in results if r[0] == "err"]
        self.assertEqual(errors, [])  # mọi lần gửi lại đều nhận đúng kết quả của lần đầu
        self.assertEqual(levels(self.d["coffee"]), (D(20), D(20), D(0)))
        self.assertClean()

    def test_complete_line_many_times(self):
        with transaction.atomic():
            stock.move(self.d["coffee"].pk, 100, kind="nhap_hang", actor=self.d["owner"], store=self.d["store"],
                       source_type="thu", source_id="1")
        result, _ = services.submit_order(self.d["waiter"], key(), cart(self.d, quantity=3))
        line = Order.objects.get(pk=result["order_id"]).lines.get()
        run_parallel(lambda i: services.complete_line(self.d["barista"], key(), line.pk, 3, 0))
        line.refresh_from_db()
        self.assertEqual(line.done_quantity, 3)
        self.assertEqual(levels(self.d["coffee"]), (D(60), D(0), D(60)))  # 120 − 3 ly × 20 g, trừ đúng một lần
        self.assertEqual(stock.StockMovement.objects.filter(kind="pha_che", ingredient=self.d["coffee"]).count(), 1)
        self.assertClean()

    def test_pay_same_table_concurrently(self):
        result, _ = services.submit_order(self.d["waiter"], key(), cart(self.d))
        line = Order.objects.get(pk=result["order_id"]).lines.get()
        services.complete_line(self.d["barista"], key(), line.pk, 1, 0)
        services.serve_line(self.d["waiter"], key(), line.pk)
        results = run_parallel(lambda i: payments.pay_table(self.cashier, key(), self.d["table"].pk, "tien_mat"))
        self.assertEqual(Payment.objects.count(), 1, results)
        self.assertEqual(Payment.objects.get().amount, 25000)
        self.assertEqual(Order.objects.get().status, Order.Status.PAID)
        self.assertClean()

    def test_two_approvers_decide_same_request(self):
        with transaction.atomic():
            stock.move(self.d["coffee"].pk, 100, kind="nhap_hang", actor=self.d["owner"], store=self.d["store"],
                       source_type="thu", source_id="1")
        result, _ = services.submit_order(self.d["waiter"], key(), cart(self.d, quantity=2))
        order = Order.objects.get(pk=result["order_id"])
        req, _ = adjustments.create_request(self.d["waiter"], key(), {
            "order": order.pk, "kind": "huy_mon", "line": order.lines.get().pk, "cups": 1,
            "reason": AdjustmentReason.objects.get_or_create(store=self.d["store"], name="Khách đổi ý")[0].pk})
        approvers = [self.manager, self.d["owner"]]
        run_parallel(lambda i: adjustments.decide(approvers[i % 2], key(), req["request"], True), n=4)
        decided = AdjustmentRequest.objects.get(pk=req["request"])
        self.assertEqual(decided.status, AdjustmentRequest.Status.APPROVED)
        line = order.lines.get()
        self.assertEqual(line.cancelled_quantity, 1)  # hủy đúng một ly, không hai
        self.assertEqual(levels(self.d["coffee"]), (D(120), D(20), D(100)))  # giữ chỗ trả lại đúng một lần
        order.refresh_from_db()
        self.assertEqual(order.total, 25000)
        self.assertClean()
