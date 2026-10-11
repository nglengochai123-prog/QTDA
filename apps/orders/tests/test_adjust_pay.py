import uuid
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.audit.models import AuditLog
from apps.catalog.models import ItemSize, MenuItem, Table
from apps.inventory.models import RecipeLine, RecipeVersion
from apps.orders import adjustments, payments, services
from apps.control.models import ExceptionCase
from apps.orders.models import (AdjustmentReason, AdjustmentRequest, Order, OrderLine,
                                Payment, PostPrepCancellation)
from apps.shifts.models import Shift

from .helpers import PASSWORD, D, build_menu, cart, levels


def key():
    return uuid.uuid4().hex


class Base(TestCase):
    def setUp(self):
        self.d = build_menu()
        mk = lambda name, role: User.objects.create_user(name, password=PASSWORD, role=role)  # noqa: E731
        self.manager = mk("qlca", Role.QUAN_LY_CA)
        self.backup = mk("duphong", Role.PHUC_VU)
        self.cashier = mk("thungan", Role.THU_NGAN)
        self.authorizer = mk("uyquyen", Role.THU_NGAN)
        now = timezone.now()
        self.shift = Shift.objects.create(store=self.d["store"], name="Ca chiều", starts_at=now - timedelta(hours=1),
                                          ends_at=now + timedelta(hours=4), approver=self.manager,
                                          backup_approver=self.backup, payment_authorizer=self.authorizer)
        self.reason = AdjustmentReason.objects.get(name="Khách đổi ý")
        self.other_table = Table.objects.create(store=self.d["store"], code="7")

    def order(self, quantity=1, **kw):
        result, _ = services.submit_order(self.d["waiter"], key(), cart(self.d, quantity=quantity, **kw))
        order = Order.objects.get(pk=result["order_id"])
        return order, order.lines.get()

    def request(self, user, order, kind, **fields):
        payload = {"order": order.pk, "kind": kind, "reason": self.reason.pk, **fields}
        result, _ = adjustments.create_request(user, key(), payload)
        return AdjustmentRequest.objects.get(pk=result["request"])

    def finish(self, line, cups=None):
        services.complete_line(self.d["barista"], key(), line.pk, cups or line.pending_quantity, line.done_quantity)
        services.serve_line(self.d["waiter"], key(), line.pk)


class AdjustmentTests(Base):
    def test_order_attached_to_current_shift(self):
        order, _ = self.order()
        self.assertEqual(order.shift, self.shift)

    def test_reason_required(self):
        # AC-20
        order, line = self.order()
        with self.assertRaises(ValidationError):
            adjustments.create_request(self.d["waiter"], key(), {"order": order.pk, "kind": "huy_mon",
                                                                 "line": line.pk, "cups": 1})

    def test_cancel_after_prep_does_not_touch_stock_twice(self):
        # AC-21: 1.000 ml sữa, pha 1 ly 30 ml còn 970; hủy sau pha chế không trừ lần nữa.
        order, line = self.order()
        services.complete_line(self.d["barista"], key(), line.pk, 1, 0)
        self.assertEqual(levels(self.d["milk"])[0], D(970))
        req = self.request(self.d["waiter"], order, "huy_mon", line=line.pk, cups=1)
        adjustments.decide(self.manager, key(), req.pk, True)
        line.refresh_from_db()
        order.refresh_from_db()
        self.assertEqual(levels(self.d["milk"]), (D(970), D(0), D(970)))
        ppc = PostPrepCancellation.objects.get(line=line)
        self.assertEqual((ppc.cups, D(ppc.usage[str(self.d["milk"].pk)]), ppc.reason), (1, D(30), self.reason))
        self.assertEqual((line.status, order.status, order.total), (OrderLine.Status.CANCELLED, Order.Status.CANCELLED, 0))
        log = AuditLog.objects.filter(object_type="orders.AdjustmentRequest").first()
        self.assertIn("Khách đổi ý", log.reason)
        self.assertEqual(log.actor, self.manager)

    def test_cancel_waiting_cup_returns_available(self):
        # AC-49: hủy ly chờ pha trả lại tồn có thể dùng, tồn vật lý không đổi.
        order, line = self.order(quantity=3)
        services.complete_line(self.d["barista"], key(), line.pk, 2, 0)
        req = self.request(self.d["waiter"], order, "huy_mon", line=line.pk, cups=1)
        adjustments.decide(self.manager, key(), req.pk, True)
        self.assertEqual(levels(self.d["coffee"]), (D(1960), D(0), D(1960)))
        order.refresh_from_db()
        line.refresh_from_db()
        self.assertEqual((order.total, line.status), (50000, OrderLine.Status.DONE))
        self.assertFalse(PostPrepCancellation.objects.exists())

    def test_requester_cannot_self_approve(self):
        # AC-22
        order, line = self.order()
        req = self.request(self.manager, order, "chuyen_ban", target_table=self.other_table.pk)
        self.assertEqual(req.level, AdjustmentRequest.Level.BACKUP)
        self.assertFalse(adjustments.can_decide(self.manager, req))
        with self.assertRaises(ValidationError):
            adjustments.decide(self.manager, key(), req.pk, True)
        adjustments.decide(self.backup, key(), req.pk, True)
        order.refresh_from_db()
        self.assertEqual(order.table, self.other_table)

    def test_paid_invoice_cancel_only_owner(self):
        # AC-23
        order, line = self.order()
        self.finish(line)
        payments.pay_table(self.cashier, key(), order.table_id, "tien_mat")
        req = self.request(self.cashier, Order.objects.get(pk=order.pk), "huy_hoa_don")
        self.assertEqual(req.level, AdjustmentRequest.Level.OWNER)
        self.assertFalse(adjustments.can_decide(self.manager, req))
        adjustments.decide(self.d["owner"], key(), req.pk, True)
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.CANCELLED)
        self.assertEqual(order.payment.status, Payment.Status.VOIDED)

    def test_escalation_every_level_logged(self):
        # AC-24: 3 phút lên dự phòng, thêm 3 phút lên Chủ quán.
        order, line = self.order()
        req = self.request(self.d["waiter"], order, "huy_mon", line=line.pk, cups=1)
        self.assertFalse(adjustments.can_decide(self.backup, req))
        start = req.level_since
        adjustments.escalate_due(start + timedelta(minutes=3, seconds=1))
        req.refresh_from_db()
        self.assertEqual(req.level, AdjustmentRequest.Level.BACKUP)
        self.assertTrue(adjustments.can_decide(self.backup, req))
        adjustments.escalate_due(start + timedelta(minutes=6, seconds=1))
        req.refresh_from_db()
        self.assertEqual(req.level, AdjustmentRequest.Level.OWNER)
        adjustments.escalate_due(start + timedelta(minutes=9, seconds=1))
        req.refresh_from_db()
        self.assertEqual(req.level, AdjustmentRequest.Level.EXHAUSTED)
        self.assertEqual(AuditLog.objects.filter(object_type="orders.AdjustmentRequest",
                                                 reason__startswith="Chuyển cấp").count(), 3)

    def test_change_item_and_reject(self):
        order, line = self.order()
        other = MenuItem.objects.create(store=self.d["store"], group=self.d["item"].group, name="Cà phê đen")
        size = ItemSize.objects.create(item=other, name="M", price=20000)
        v = RecipeVersion.objects.create(item=other)
        RecipeLine.objects.create(version=v, size=size, ingredient=self.d["coffee"], quantity=18)
        v.publish(self.d["owner"])
        other.status = MenuItem.Status.ON_SALE
        other.save()
        new_line = {"item": other.pk, "size": size.pk, "quantity": 1, "options": []}
        req = self.request(self.d["waiter"], order, "doi_mon", line=line.pk, cups=1, new_line=new_line)
        self.assertIn("Cà phê đen M", req.summary())
        with self.assertRaises(ValidationError):  # một đơn chỉ một yêu cầu chờ duyệt
            self.request(self.d["waiter"], order, "chuyen_ban", target_table=self.other_table.pk)
        op = key()
        adjustments.decide(self.manager, op, req.pk, True)
        again, repeated = adjustments.decide(self.manager, op, req.pk, True)
        self.assertTrue(repeated)
        order.refresh_from_db()
        self.assertEqual(order.total, 20000)
        self.assertEqual(levels(self.d["coffee"]), (D(2000), D(18), D(1982)))
        req2 = self.request(self.d["waiter"], order, "chuyen_ban", target_table=self.other_table.pk)
        adjustments.decide(self.manager, key(), req2.pk, False, "Khách vẫn ngồi bàn cũ")
        order.refresh_from_db()
        self.assertEqual(order.table, self.d["table"])


class PaymentTests(Base):
    def test_cannot_pay_before_served(self):
        # AC-07
        order, line = self.order()
        with self.assertRaises(ValidationError):
            payments.pay_table(self.cashier, key(), order.table_id, "tien_mat")
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.SENT)

    def test_transfer_needs_confirmation_and_records_once(self):
        # AC-08
        order, line = self.order(quantity=2)
        self.finish(line)
        with self.assertRaises(ValidationError):
            payments.pay_table(self.cashier, key(), order.table_id, "chuyen_khoan", transfer_confirmed=False)
        op = key()
        first, _ = payments.pay_table(self.cashier, op, order.table_id, "chuyen_khoan", transfer_confirmed=True)
        second, repeated = payments.pay_table(self.cashier, op, order.table_id, "chuyen_khoan", transfer_confirmed=True)
        self.assertTrue(repeated)
        self.assertEqual(first, second)
        self.assertEqual(Payment.objects.count(), 1)
        payment = Payment.objects.get()
        self.assertEqual((payment.amount, payment.cashier, payment.method), (50000, self.cashier, "chuyen_khoan"))
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.PAID)

    def test_pending_request_blocks_payment_with_level(self):
        # AC-09
        order, line = self.order()
        self.finish(line)
        self.request(self.d["waiter"], order, "chuyen_ban", target_table=self.other_table.pk)
        state = payments.bill(order.table)
        self.assertIn("Người duyệt trong ca", state["blockers"][0])
        with self.assertRaises(ValidationError):
            payments.pay_table(self.cashier, key(), order.table_id, "tien_mat")

    def test_pay_received_items_when_all_levels_expired(self):
        # AC-10: đổi món 50.000 đ sang món 30.000 đ, quá hạn mọi cấp, khách đã nhận món mới.
        order, line = self.order()
        self.finish(line)
        tea = MenuItem.objects.create(store=self.d["store"], group=self.d["item"].group, name="Trà đào")
        size = ItemSize.objects.create(item=tea, name="M", price=30000)
        tea.no_ingredients = True
        tea.status = MenuItem.Status.ON_SALE
        tea.save()
        req = self.request(self.d["waiter"], order, "doi_mon", line=line.pk, cups=1,
                           new_line={"item": tea.pk, "size": size.pk, "quantity": 1, "options": []})
        adjustments.escalate_due(req.level_since + timedelta(minutes=10))
        state = payments.bill(order.table)
        self.assertEqual(len(state["exhausted"]), 1)
        with self.assertRaises(ValidationError):
            payments.pay_table(self.cashier, key(), order.table_id, "tien_mat")
        with self.assertRaises(ValidationError):  # không phải người được ủy quyền
            payments.pay_received_items(self.cashier, key(), order.table_id, "tien_mat")
        result, _ = payments.pay_received_items(self.authorizer, key(), order.table_id, "tien_mat")
        self.assertEqual(result["amount"], 30000)
        req.refresh_from_db()
        self.assertEqual(req.status, AdjustmentRequest.Status.POST_AUDIT)
        self.assertTrue(PostPrepCancellation.objects.filter(line=line).exists())
        self.assertTrue(ExceptionCase.objects.filter(requests=req, kind="tt_mon_thuc_nhan", status="cho_xem_xet").exists())
        self.assertEqual(Payment.objects.get().kind, Payment.Kind.RECEIVED_ITEMS)
