"""Bán hàng dự phòng và nhập bù (FR-06, BRU-03, AC-12, AC-13)."""

from datetime import timedelta

from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.control.models import ExceptionCase
from apps.inventory import stock
from apps.inventory.models import RecipeLine, RecipeVersion, StockMovement
from apps.orders import backup, services
from apps.orders.models import BackupSlip, Order, Payment
from apps.orders.tests.helpers import D, cart, levels
from apps.orders.tests.test_adjust_pay import Base, key
from apps.shifts import services as shift_services


class BackupSlipTests(Base):
    def setUp(self):
        super().setUp()
        self.sold_at = timezone.now()
        # Định mức mới áp dụng sau thời điểm bán: phiếu nhập bù phải dùng bản cũ (BRU-39).
        v2 = RecipeVersion.objects.create(item=self.d["item"])
        RecipeLine.objects.create(version=v2, size=self.d["size_m"], ingredient=self.d["coffee"], quantity=25)
        RecipeLine.objects.create(version=v2, size=self.d["size_m"], ingredient=self.d["milk"], quantity=30)
        v2.publish(self.d["owner"], effective_from=self.sold_at + timedelta(seconds=1))

    def issue(self, first=151, last=156):
        return backup.issue_range(self.d["owner"], self.shift.pk, first, last, self.manager.pk)

    def enter(self, number, code="", op=None, restored=None, method="tien_mat"):
        payload = {"number": number, "operation_code": code, "sold_at": self.sold_at.isoformat(),
                   "restored_at": (restored or self.sold_at).isoformat(), "method": method,
                   "table": self.d["table"].pk, "lines": cart(self.d)["lines"]}
        result, _ = backup.enter_slip(self.manager, op or key(), payload)
        return result

    def test_ac12_link_existing_and_create_new_orders_once(self):
        self.issue()
        online_key = key()
        result, _ = services.submit_order(self.d["waiter"], online_key, cart(self.d))  # lưu rồi mất phản hồi
        online = Order.objects.get(pk=result["order_id"])
        line = online.lines.get()
        services.complete_line(self.d["barista"], key(), line.pk, 1, 0)  # đã ghi pha chế
        consumed = StockMovement.objects.filter(kind=StockMovement.Kind.CONSUME).count()

        op = key()
        first = self.enter(151, code=online_key, op=op)
        self.assertTrue(first["linked"])
        self.assertEqual(first["order_id"], online.pk)
        self.assertEqual(StockMovement.objects.filter(kind=StockMovement.Kind.CONSUME).count(), consumed)  # không trừ lại
        for number in range(152, 157):
            self.assertTrue(self.enter(number)["ok"])
        self.assertEqual(self.enter(151, code=online_key, op=op), first)  # gửi lại phiếu 0151 trả kết quả cũ
        again, repeated = services.submit_order(self.d["waiter"], online_key, cart(self.d))  # nháp gửi lại
        self.assertTrue(repeated)
        self.assertEqual(again["order_id"], online.pk)

        self.assertEqual(Order.objects.count(), 6)
        self.assertEqual(Payment.objects.count(), 6)
        self.assertEqual(sum(Payment.objects.values_list("amount", flat=True)), 6 * 25000)
        self.assertTrue(all(o.status == Order.Status.PAID for o in Order.objects.all()))
        new_line = BackupSlip.objects.get(number=152).order.lines.get()
        self.assertEqual(new_line.recipe_version, self.d["v1"])  # định mức lúc bán
        # Cà phê: 2.000 − 6 ly × 20 g theo bản cũ; không còn giữ chỗ.
        self.assertEqual(levels(self.d["coffee"]), (D(1880), D(0), D(1880)))
        self.assertEqual(stock.ledger_problems(), [])

    def test_ac13_missing_number_blocks_close_until_voided(self):
        self.issue(151, 158)
        shift_services.add_cash_entry(self.manager, key(), self.shift.pk, "dau_ca", 0)
        for number in (151, 152, 153, 154, 155, 156, 158):
            self.enter(number)
        with self.assertRaises(ValidationError) as caught:
            shift_services.close_shift(self.manager, self.shift.pk)
        self.assertTrue(any("0157" in m for m in caught.exception.messages))
        backup.declare_last_used(self.manager, self.shift.backup_ranges.get().pk, 158)
        with self.assertRaises(ValidationError):
            backup.void_slip(self.manager, 157, "")  # phải có lý do
        backup.void_slip(self.manager, 157, "Viết hỏng")
        shift_services.close_shift(self.manager, self.shift.pk)
        self.assertTrue(ExceptionCase.objects.filter(kind="pdp_huy").exists())

    def test_unused_range_must_be_declared_before_close(self):
        self.issue()
        shift_services.add_cash_entry(self.manager, key(), self.shift.pk, "dau_ca", 0)
        with self.assertRaises(ValidationError):
            shift_services.close_shift(self.manager, self.shift.pk)
        backup.declare_last_used(self.manager, self.shift.backup_ranges.get().pk, 0)
        shift_services.close_shift(self.manager, self.shift.pk)

    def test_duplicate_out_of_range_and_late_create_exceptions(self):
        self.issue()
        self.enter(151)
        dup = self.enter(151)  # cùng số, mã khác
        self.assertFalse(dup["ok"])
        self.assertEqual(Order.objects.count(), 1)
        self.assertFalse(self.enter(999)["ok"])
        late = self.enter(152, restored=timezone.now() - timedelta(hours=2))
        self.assertTrue(late["late"])
        kinds = set(ExceptionCase.objects.values_list("kind", flat=True))
        self.assertTrue({"pdp_trung", "pdp_ngoai_day", "pdp_qua_han"} <= kinds)

    def test_overlapping_range_rejected(self):
        self.issue(151, 156)
        with self.assertRaises(ValidationError):
            self.issue(156, 160)


class BackupScreenTests(Base):
    def test_screen_flow(self):
        from django.urls import reverse

        from apps.orders.tests.helpers import PASSWORD

        self.client.login(username=self.manager.username, password=PASSWORD)
        url = reverse("orders:backup_slips")
        self.client.post(url, {"action": "issue", "shift": self.shift.pk, "first": "151", "last": "152",
                               "receiver": self.manager.pk})
        when = (timezone.localtime() + timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M")
        self.client.post(url, {"action": "enter", "operation_key": key(), "number": "151", "sold_at": when,
                               "restored_at": when, "table": self.d["table"].pk, "method": "tien_mat",
                               "item_0": f"{self.d['item'].pk}:{self.d['size_m'].pk}", "qty_0": "2"})
        self.client.post(url, {"action": "enter", "operation_key": key(), "number": "152", "sold_at": when,
                               "restored_at": when, "table": self.d["table"].pk, "method": "tien_mat"})  # thiếu món
        page = self.client.get(url)
        self.assertContains(page, "Đơn chưa có món nào")
        self.assertContains(page, "Phiếu 0151")
        self.assertEqual(BackupSlip.objects.get().order.total, 50000)
