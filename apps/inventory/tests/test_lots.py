"""Kho theo lô: tạo lô khi nhập, thứ tự lấy lô FEFO, FIFO, LIFO, hao hụt và kiểm kê theo lô, dự kiến dùng kịp."""

import tempfile
import uuid
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.inventory import lots, operations as ops, stock
from apps.inventory.models import IssueRule, StockLot, StockMovement, Supplier, Waste
from apps.orders.tests.helpers import PASSWORD, build_menu

TODAY = timezone.localdate()


def key():
    return uuid.uuid4().hex


def fake(pk, expiry, received_days_ago, remaining=10):
    received = timezone.now() - timedelta(days=received_days_ago)
    return SimpleNamespace(pk=pk, expiry_date=expiry, received_at=received, remaining=Decimal(remaining))


class OrderTests(SimpleTestCase):
    def setUp(self):
        self.old = fake(1, TODAY + timedelta(days=5), 6)       # nhập trước, hạn xa
        self.new = fake(2, TODAY + timedelta(days=2), 1)       # nhập sau, hạn gần
        self.gone = fake(3, TODAY - timedelta(days=1), 9)      # đã quá hạn
        self.undated = fake(4, None, 8)

    def ids(self, seq):
        return [l.pk for l in seq]

    def test_fefo_takes_nearest_expiry_and_leaves_expired_last(self):
        lots_ = [self.old, self.new, self.gone, self.undated]
        self.assertEqual(self.ids(lots.issue_order(lots_, IssueRule.FEFO, TODAY)), [2, 1, 4, 3])

    def test_fifo_and_lifo_follow_receipt_date(self):
        lots_ = [self.old, self.new, self.gone, self.undated]
        self.assertEqual(self.ids(lots.issue_order(lots_, IssueRule.FIFO, TODAY)), [4, 1, 2, 3])
        self.assertEqual(self.ids(lots.issue_order(lots_, IssueRule.LIFO, TODAY)), [2, 1, 4, 3])

    def test_expired_first_and_preferred_lot(self):
        lots_ = [self.old, self.new, self.gone]
        self.assertEqual(self.ids(lots.issue_order(lots_, IssueRule.FEFO, TODAY, expired_first=True)), [3, 2, 1])
        self.assertEqual(self.ids(lots.issue_order(lots_, IssueRule.FEFO, TODAY, prefer=1)), [1, 2, 3])

    def test_status_and_near_window(self):
        self.assertEqual(lots.near_days(7, 2, 20), 2)
        self.assertEqual(lots.near_days(365, 2, 20), 73)
        self.assertEqual(lots.status(self.new, TODAY, 2), lots.NEAR)
        self.assertEqual(lots.status(self.old, TODAY, 2), lots.OK)
        self.assertEqual(lots.status(self.gone, TODAY, 2), lots.EXPIRED)
        self.assertEqual(lots.status(self.undated, TODAY, 2), lots.UNKNOWN)

    def test_projection_finds_quantity_that_will_expire_unused(self):
        # Lô gần (hạn sau 2 ngày, còn 10) dùng được 3 ngày: hôm nay, mai, mốt. Lô xa (hạn sau 5 ngày) dùng tiếp sau đó.
        out = lots.project([self.new, self.old], 4, TODAY)  # 4 mỗi ngày: lô gần hết vào ngày mốt, lô xa ngày thứ tư
        self.assertEqual((out[2]["used_up"], out[2]["waste"]), (TODAY + timedelta(days=2), 0.0))
        self.assertEqual((out[1]["used_up"], out[1]["waste"]), (TODAY + timedelta(days=4), 0.0))
        out = lots.project([self.new, self.old], 3, TODAY)  # 3 mỗi ngày: lô gần dùng 9, bỏ 1
        self.assertAlmostEqual(out[2]["waste"], 1.0)
        self.assertIsNone(out[2]["used_up"])
        out = lots.project([self.new, self.old], 1, TODAY)
        self.assertAlmostEqual(out[2]["waste"], 7.0)  # 3 ngày × 1
        self.assertAlmostEqual(out[1]["waste"], 7.0)  # lô xa bắt đầu ngày thứ ba, dùng 3 ngày


@override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix="lam-test-media-"))
class LotFlowTests(TestCase):
    def setUp(self):
        self.d = build_menu(coffee_opening=None, milk_opening=None)
        self.milk = self.d["milk"]
        self.milk.shelf_life_days = 7
        self.milk.save()
        self.owner = self.d["owner"]
        self.supplier = Supplier.objects.create(store=self.d["store"], name="NCC Sữa")

    def receive(self, qty, expiry=None, price=30, supplier_lot=""):
        result, _ = ops.create_receipt(self.owner, key(), self.supplier.pk, [
            {"ingredient": self.milk.pk, "quantity": str(qty), "unit_price": price,
             "expiry_date": expiry.isoformat() if expiry else None, "supplier_lot": supplier_lot}],
            "tra_ngay", invoice_photo=SimpleUploadedFile("hd.jpg", b"jpeg", content_type="image/jpeg"))
        return StockLot.objects.get(code=result["lots"][0])

    def use(self, qty):
        stock.move(self.milk.pk, -qty, kind=StockMovement.Kind.CONSUME, actor=self.owner, store=self.d["store"],
                   source_type="thu", source_id="1")

    def remaining(self, *lots_):
        return [StockLot.objects.get(pk=l.pk).remaining for l in lots_]

    def test_receipt_creates_lot_with_code_and_estimated_expiry(self):
        lot = self.receive(1000, supplier_lot="SX2610")
        self.assertTrue(lot.code.startswith("PN") and lot.code.endswith("/1"))
        self.assertEqual((lot.quantity, lot.remaining, lot.unit_cost, lot.supplier_lot), (1000, 1000, 30, "SX2610"))
        self.assertEqual((lot.expiry_date, lot.expiry_estimated), (TODAY + timedelta(days=6), True))
        dated = self.receive(500, expiry=TODAY + timedelta(days=3))
        self.assertEqual((dated.expiry_date, dated.expiry_estimated), (TODAY + timedelta(days=3), False))
        with self.assertRaises(ValidationError):
            self.receive(100, expiry=TODAY - timedelta(days=1))

    def test_consumption_follows_fefo_then_rule_change(self):
        far = self.receive(1000, expiry=TODAY + timedelta(days=6))
        near = self.receive(1000, expiry=TODAY + timedelta(days=2))
        self.use(1200)
        self.assertEqual(self.remaining(near, far), [0, 800])
        self.milk.shelf_life_days = None
        self.milk.issue_rule = IssueRule.LIFO
        self.milk.full_clean()
        self.milk.save()
        newest = self.receive(300)
        self.use(100)
        self.assertEqual(self.remaining(newest, far), [200, 800])
        self.assertEqual(stock.ledger_problems(), [])

    def test_lifo_refused_for_items_with_shelf_life(self):
        self.milk.issue_rule = IssueRule.LIFO
        with self.assertRaises(ValidationError):
            self.milk.full_clean()

    def test_expired_lot_is_never_suggested_but_waste_takes_it_first(self):
        old = self.receive(400, expiry=TODAY + timedelta(days=1))
        fresh = self.receive(1000, expiry=TODAY + timedelta(days=6))
        StockLot.objects.filter(pk=old.pk).update(expiry_date=TODAY - timedelta(days=1))
        view = lots.overview([self.milk])[self.milk.pk]
        self.assertEqual(view["pick"].pk, fresh.pk)
        self.assertEqual([v.pk for v in view["expired"]], [old.pk])
        self.use(100)  # pha chế không lấy lô quá hạn
        self.assertEqual(self.remaining(old, fresh), [400, 900])
        ops.record_waste(self.owner, key(), self.milk.pk, "150", Waste.Reason.EXPIRED)
        self.assertEqual(self.remaining(old, fresh), [250, 900])
        ops.dispose_lot(self.owner, key(), old.pk)
        self.assertEqual(self.remaining(old, fresh), [0, 900])
        self.assertEqual(Waste.objects.filter(reason=Waste.Reason.EXPIRED).count(), 2)
        self.assertEqual(stock.ledger_problems(), [])

    def test_waste_on_chosen_lot(self):
        a = self.receive(500, expiry=TODAY + timedelta(days=2))
        b = self.receive(500, expiry=TODAY + timedelta(days=5))
        ops.record_waste(self.owner, key(), self.milk.pk, "200", Waste.Reason.BROKEN, lot_id=b.pk)
        self.assertEqual(self.remaining(a, b), [500, 300])
        with self.assertRaises(ValidationError):
            ops.record_waste(self.owner, key(), self.milk.pk, "400", Waste.Reason.BROKEN, lot_id=b.pk)

    def test_count_shortage_takes_expired_first_and_surplus_restores(self):
        old = self.receive(300, expiry=TODAY + timedelta(days=1))
        fresh = self.receive(1000, expiry=TODAY + timedelta(days=6))
        StockLot.objects.filter(pk=old.pk).update(expiry_date=TODAY - timedelta(days=1))
        ops.submit_count(self.owner, key(), self.milk.pk, "1250", "đổ bỏ hộp cũ")
        self.assertEqual(self.remaining(old, fresh), [250, 1000])
        self.use(400)
        self.assertEqual(self.remaining(old, fresh), [250, 600])
        ops.submit_count(self.owner, key(), self.milk.pk, "870", "")  # dư 20: trả lại lô đang dùng
        self.assertEqual(self.remaining(old, fresh), [250, 620])
        self.assertEqual(stock.ledger_problems(), [])

    def test_negative_book_stock_is_covered_by_next_receipt(self):
        self.receive(100)
        self.use(150)  # pha khi sổ ghi thiếu: tồn vật lý -50
        lot = self.receive(1000)
        self.assertEqual(self.remaining(lot), [950])
        self.assertEqual(stock.ledger_problems(), [])

    def test_count_surplus_without_lots_creates_count_lot(self):
        result, _ = ops.submit_count(self.owner, key(), self.milk.pk, "200", "tìm thấy thùng chưa ghi")
        ops.confirm_count(self.owner, result["count"])  # tồn sổ 0 nên chênh lệch 100%, chờ Chủ quán xác nhận
        lot = StockLot.objects.get(ingredient=self.milk)
        self.assertEqual((lot.source, lot.remaining, lot.expiry_date), (StockLot.Source.COUNT, 200, None))
        ops.update_lot(self.owner, lot.pk, (TODAY + timedelta(days=3)).isoformat(), "A12")
        lot.refresh_from_db()
        self.assertEqual((lot.expiry_date, lot.supplier_lot, lot.expiry_estimated), (TODAY + timedelta(days=3), "A12", False))

    def test_opening_stock_is_a_lot(self):
        stock.record_opening(self.d["coffee"], 1500, self.owner, expiry_date=TODAY + timedelta(days=90))
        lot = StockLot.objects.get(ingredient=self.d["coffee"])
        self.assertEqual((lot.source, lot.remaining, lot.expiry_date), (StockLot.Source.OPENING, 1500,
                                                                        TODAY + timedelta(days=90)))

    def test_lot_screens(self):
        lot = self.receive(1000)
        self.client.login(username=self.owner.username, password=PASSWORD)
        r = self.client.get(reverse("inventory:lots"))
        self.assertContains(r, lot.code)
        r = self.client.get(reverse("inventory:lot_detail", args=[self.milk.pk]))
        self.assertContains(r, lot.code)
        r = self.client.get(reverse("inventory:pick_list"))
        self.assertContains(r, lot.code)
        self.client.login(username=self.d["waiter"].username, password=PASSWORD)
        self.assertEqual(self.client.get(reverse("inventory:lots")).status_code, 403)
