import threading
import uuid

from django.core.exceptions import ValidationError
from django.db import DatabaseError, IntegrityError, connection, connections, transaction
from django.test import TestCase, TransactionTestCase

from apps.core.idempotency import OperationKeyError
from apps.core.models import OperationRecord
from apps.inventory import stock
from apps.inventory.models import IngredientStock, StockMovement
from apps.orders import services
from apps.orders.models import Order, OrderLine

from .helpers import D, build_menu, cart, levels


def key():
    return uuid.uuid4().hex


class StockLedgerTests(TestCase):
    def setUp(self):
        self.d = build_menu()

    def test_opening_recorded_with_source_actor_and_time(self):
        movement = StockMovement.objects.get(ingredient=self.d["coffee"])
        self.assertEqual(movement.kind, StockMovement.Kind.OPENING)
        self.assertEqual(movement.quantity, D(2000))
        self.assertEqual(movement.balance_after, D(2000))
        self.assertEqual(movement.actor, self.d["owner"])
        self.assertEqual(movement.source_type, "ton_dau_ky")
        self.assertIsNotNone(movement.created_at)
        self.assertEqual(levels(self.d["coffee"]), (D(2000), D(0), D(2000)))

    def test_opening_only_once(self):
        with self.assertRaises(ValidationError):
            stock.record_opening(self.d["coffee"], 100, self.d["owner"])

    def test_movements_are_append_only(self):
        movement = StockMovement.objects.first()
        with self.assertRaises(ValidationError):
            movement.save()
        with self.assertRaises(ValidationError):
            movement.delete()
        with self.assertRaises((IntegrityError, DatabaseError)):
            with transaction.atomic(), connection.cursor() as cursor:
                cursor.execute("UPDATE inventory_stockmovement SET quantity = 0")


class OrderFlowTests(TestCase):
    def setUp(self):
        self.d = build_menu()

    def submit(self, payload, op=None, user=None):
        return services.submit_order(user or self.d["waiter"], op or key(), payload)

    def test_reserve_then_complete_exactly_once(self):
        # AC-48: gửi 3 ly, tồn có thể dùng giảm, tồn vật lý giữ nguyên; pha 2 ly thì trừ vật lý.
        result, repeated = self.submit(cart(self.d, quantity=3))
        self.assertFalse(repeated)
        self.assertEqual(levels(self.d["coffee"]), (D(2000), D(60), D(1940)))
        line = OrderLine.objects.get(order_id=result["order_id"])
        op = key()
        services.complete_line(self.d["barista"], op, line.pk, cups=2, expected_done=0)
        self.assertEqual(levels(self.d["coffee"]), (D(1960), D(20), D(1940)))
        # Bấm lại cùng nút (cùng mã): trả kết quả cũ, không trừ thêm.
        again, repeated = services.complete_line(self.d["barista"], op, line.pk, cups=2, expected_done=0)
        self.assertTrue(repeated)
        # Bấm lại từ màn hình cũ (mã mới, số đã pha cũ): không trừ thêm.
        stale, _ = services.complete_line(self.d["barista"], key(), line.pk, cups=2, expected_done=0)
        self.assertEqual(stale["applied"], 0)
        self.assertEqual(levels(self.d["coffee"]), (D(1960), D(20), D(1940)))
        self.assertEqual(StockMovement.objects.filter(kind="pha_che", ingredient=self.d["coffee"]).count(), 1)
        # Pha nốt ly cuối, bấm "xong" thêm nhiều lần cũng không trừ.
        services.complete_line(self.d["barista"], key(), line.pk, cups=1, expected_done=2)
        for _ in range(3):
            services.complete_line(self.d["barista"], key(), line.pk, cups=1, expected_done=3)
        line.refresh_from_db()
        self.assertEqual(line.status, OrderLine.Status.DONE)
        self.assertEqual(levels(self.d["coffee"]), (D(1940), D(0), D(1940)))
        self.assertEqual(levels(self.d["milk"]), (D(910), D(0), D(910)))

    def test_options_add_ingredients_and_price(self):
        result, _ = self.submit(cart(self.d, quantity=2, options=[self.d["cream"], self.d["less_ice"]], note="ít ngọt"))
        line = OrderLine.objects.get(order_id=result["order_id"])
        self.assertEqual(line.unit_price, 33000)
        self.assertEqual(result["total"], 66000)
        self.assertEqual(line.note, "ít ngọt")
        self.assertEqual(levels(self.d["milk"]), (D(1000), D(90), D(910)))
        self.assertEqual(sorted(o.name for o in line.options.all()), ["Kem muối", "Ít đá"])

    def test_shortage_rejects_whole_order(self):
        payload = cart(self.d, quantity=1)
        for _ in range(3):  # 1 + 3 × 40 = 121 ly × 20 g > 2.000 g cà phê
            payload["lines"].append({"item": self.d["item"].pk, "size": self.d["size_m"].pk, "options": [],
                                     "quantity": 40, "note": ""})
        op = key()
        with self.assertRaises(stock.InsufficientStock) as ctx:
            self.submit(payload, op)
        self.assertEqual(ctx.exception.shortages[0]["ingredient"], "Cà phê")
        self.assertEqual(Order.objects.count(), 0)
        self.assertEqual(levels(self.d["coffee"]), (D(2000), D(0), D(2000)))
        self.assertFalse(OperationRecord.objects.filter(key=op).exists())

    def test_resend_after_lost_response_does_not_duplicate(self):
        op = key()
        first, repeated1 = self.submit(cart(self.d, quantity=2), op)
        second, repeated2 = self.submit(cart(self.d, quantity=2), op)
        self.assertEqual((repeated1, repeated2), (False, True))
        self.assertEqual(first, second)
        self.assertEqual(Order.objects.count(), 1)
        self.assertEqual(levels(self.d["coffee"]), (D(2000), D(40), D(1960)))

    def test_same_key_different_content_rejected(self):
        op = key()
        self.submit(cart(self.d, quantity=1), op)
        with self.assertRaises(OperationKeyError):
            self.submit(cart(self.d, quantity=5), op)
        self.assertEqual(Order.objects.count(), 1)

    def test_price_and_recipe_change_while_waiting(self):
        # AC-46, AC-114: dòng đang chờ giữ giá và định mức đã lưu; đơn mới dùng bản mới.
        old, _ = self.submit(cart(self.d, quantity=1))
        self.d["size_m"].price = 28000
        self.d["size_m"].save()
        draft = self.d["v1"].copy_as_draft()
        line = draft.lines.get(ingredient=self.d["coffee"])
        line.quantity = 25
        line.save()
        draft.publish(self.d["owner"])
        new, _ = self.submit(cart(self.d, quantity=1))
        old_line = OrderLine.objects.get(order_id=old["order_id"])
        new_line = OrderLine.objects.get(order_id=new["order_id"])
        self.assertEqual((old_line.unit_price, old_line.recipe_version), (25000, self.d["v1"]))
        self.assertEqual((new_line.unit_price, new_line.recipe_version), (28000, draft))
        self.assertEqual(levels(self.d["coffee"]), (D(2000), D(45), D(1955)))
        services.complete_line(self.d["barista"], key(), old_line.pk, 1, 0)
        self.assertEqual(levels(self.d["coffee"]), (D(1980), D(25), D(1955)))

    def test_lines_are_locked_after_send(self):
        result, _ = self.submit(cart(self.d))
        line = OrderLine.objects.get(order_id=result["order_id"])
        line.quantity = 9
        with self.assertRaises(ValidationError):
            line.save()

    def test_reserved_matches_waiting_lines(self):
        self.submit(cart(self.d, quantity=3))
        r2, _ = self.submit(cart(self.d, quantity=2, options=[self.d["cream"]]))
        services.complete_line(self.d["barista"], key(), OrderLine.objects.get(order_id=r2["order_id"]).pk, 1, 0)
        expected = {}
        for line in OrderLine.objects.all():
            for ingredient_id, amount in line.usage_for(line.pending_quantity).items():
                expected[ingredient_id] = expected.get(ingredient_id, D(0)) + amount
        for row in IngredientStock.objects.all():
            self.assertEqual(row.reserved, expected.get(row.ingredient_id, D(0)), row)

    def test_invalid_cart_rejected(self):
        bad = cart(self.d)
        bad["lines"][0]["size"] = 999999
        with self.assertRaises(ValidationError):
            self.submit(bad)
        with self.assertRaises(OperationKeyError):
            services.submit_order(self.d["waiter"], "", cart(self.d))

    def test_availability_counts_cups(self):
        self.assertEqual(services.availability()[self.d["size_m"].pk], 33)  # 1000 ml sữa / 30 ml
        self.submit(cart(self.d, quantity=3))
        self.assertEqual(services.availability()[self.d["size_m"].pk], 30)


class ConcurrentOrderTests(TransactionTestCase):
    """Hai đơn gửi cùng lúc cần phần tồn cuối: chỉ một đơn được nhận (NFR-04)."""

    APPEND_ONLY = ("audit_auditlog", "inventory_stockmovement")

    def tearDown(self):
        # Dọn dữ liệu kiểm thử cần tạm bỏ trigger chỉ-thêm-mới; tạo lại ngay ở lần kiểm thử sau.
        with connection.cursor() as cursor:
            for table in self.APPEND_ONLY:
                cursor.execute(f"DROP TRIGGER IF EXISTS {table}_no_update")
                cursor.execute(f"DROP TRIGGER IF EXISTS {table}_no_delete")
        super().tearDown()

    def setUp(self):
        with connection.cursor() as cursor:
            for table in self.APPEND_ONLY:
                for op in ("update", "delete"):
                    cursor.execute(
                        f"CREATE TRIGGER IF NOT EXISTS {table}_no_{op} BEFORE {op.upper()} ON {table} "
                        f"BEGIN SELECT RAISE(ABORT, 'chi duoc them moi'); END;")
        self.d = build_menu(coffee_opening=20, milk_opening=1000)  # vừa đủ một ly

    def test_two_orders_compete_for_last_stock(self):
        barrier = threading.Barrier(2)
        outcomes = []

        def worker():
            try:
                barrier.wait()
                with transaction.atomic():
                    services.submit_order(self.d["waiter"], key(), cart(self.d, quantity=1))
                outcomes.append("nhan")
            except stock.InsufficientStock:
                outcomes.append("thieu")
            except Exception as error:  # pragma: no cover - để báo rõ khi lỗi khác
                outcomes.append(f"loi: {error!r}")
            finally:
                connections.close_all()

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(30)
        self.assertEqual(sorted(outcomes), ["nhan", "thieu"])
        self.assertEqual(Order.objects.count(), 1)
        self.assertEqual(levels(self.d["coffee"]), (D(20), D(20), D(0)))
