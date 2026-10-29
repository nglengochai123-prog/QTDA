"""Thu tiền trước khi pha chế: tạo đơn kèm thu tiền, thu ngân xác nhận pha xong, giao nước và hoàn tất,
điều chỉnh sau khi đã thu trước và kết ca."""

import json
import uuid
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.audit.models import Action, AuditLog
from apps.core.integrity import problems
from apps.inventory.models import StockMovement
from apps.orders import adjustments, payments, prepaid, services
from apps.orders.models import AdjustmentReason, AdjustmentRequest, Order, OrderLine, Payment, PrepaidCharge
from apps.shifts import services as shift_services
from apps.shifts.models import Refund, Shift
from apps.staff.models import Attendance

from .helpers import PASSWORD, D, build_menu, cart, levels


def key():
    return uuid.uuid4().hex


def cash(given=None):
    return {"mode": "truoc", "method": "tien_mat", "cash_received": given}


def transfer(confirmed):
    return {"mode": "truoc", "method": "chuyen_khoan", "transfer_confirmed": confirmed}


class Base(TestCase):
    def setUp(self):
        self.d = build_menu()
        self.owner = self.d["owner"]
        self.cashier = User.objects.create_user("thungan", password=PASSWORD, role=Role.THU_NGAN)
        now = timezone.now()
        self.shift = Shift.objects.create(store=self.d["store"], name="Ca chiều", starts_at=now - timedelta(hours=1),
                                          ends_at=now + timedelta(hours=4), approver=self.owner)
        # Thu ngân đang trong ca với vai trò Thu ngân: phân công hợp lệ để thu trước.
        Attendance.objects.create(store=self.d["store"], user=self.cashier, role=Role.THU_NGAN,
                                  clock_in=now - timedelta(minutes=30))
        self.reason = AdjustmentReason.objects.get(name="Khách đổi ý")

    def prepay(self, quantity=1, spec=None, user=None, op=None, **kw):
        payload = cart(self.d, quantity=quantity, **kw)
        payload["payment"] = spec or cash()
        result, repeated = services.submit_order(user or self.cashier, op or key(), payload)
        return Order.objects.get(pk=result["order_id"]), result, repeated

    def submit_json(self, user, payload, op=None):
        self.client.force_login(user)
        return self.client.post("/don/gui/", json.dumps({"operation_key": op or key(), "order": payload}),
                                content_type="application/json")

    def done(self, user, line, cups, expected=None):
        line.refresh_from_db()
        fn = prepaid.cashier_complete_line if user == self.cashier else services.complete_line
        return fn(user, key(), line.pk, cups, line.done_quantity if expected is None else expected)[0]

    def adjust(self, order, kind, **fields):
        payload = {"order": order.pk, "kind": kind, "reason": self.reason.pk, **fields}
        result, _ = adjustments.create_request(self.d["waiter"], key(), payload)
        req = AdjustmentRequest.objects.get(pk=result["request"])
        adjustments.decide(self.owner, key(), req.pk, True)
        req.refresh_from_db()
        return req


class PrepayAtCreateTests(Base):
    def test_prepay_cash_records_money_reserves_stock_and_keeps_order_open(self):
        # 1. Tiền mặt: khách đưa 100.000 đ cho đơn 2 ly 50.000 đ; doanh thu chỉ là 50.000 đ.
        order, result, _ = self.prepay(quantity=2, spec=cash(100000))
        payment = order.payment
        self.assertEqual((payment.kind, payment.method, payment.amount, payment.cash_received, payment.change_due),
                         (Payment.Kind.PREPAID, Payment.Method.CASH, 50000, 100000, 50000))
        self.assertEqual((payment.cashier, payment.shift), (self.cashier, self.shift))
        self.assertEqual(result["prepaid"]["change"], 50000)
        # Tiền và tiến độ tách riêng: đã thu nhưng chưa pha.
        self.assertEqual(order.status, Order.Status.SENT)
        self.assertEqual((order.payment_label(), order.progress_label()), ("Đã thu trước", "Chờ pha chế"))
        # Kho: chỉ giữ khi gửi, thanh toán không trừ.
        self.assertEqual(levels(self.d["coffee"]), (D(2000), D(40), D(1960)))
        self.assertFalse(StockMovement.objects.filter(kind=StockMovement.Kind.CONSUME).exists())
        figures = shift_services.figures(self.shift)
        self.assertEqual((figures["revenue_cash"], figures["expected_cash"]), (50000, 50000))
        self.assertEqual(problems(), [])

    def test_prepay_through_screen_returns_change(self):
        payload = cart(self.d)
        payload["payment"] = cash(30000)
        page = self.submit_json(self.cashier, payload)
        self.assertEqual(page.status_code, 200, page.content)
        data = page.json()
        self.assertEqual((data["prepaid"]["amount"], data["prepaid"]["change"]), (25000, 5000))
        create = self.client.get("/don/moi/")
        self.assertContains(create, "Thanh toán ngay")
        self.assertContains(create, "Tiền khách đưa")

    def test_cash_given_less_than_total_is_refused(self):
        with self.assertRaises(ValidationError):
            self.prepay(quantity=2, spec=cash(20000))
        self.assertFalse(Order.objects.exists())
        self.assertEqual(levels(self.d["coffee"]), (D(2000), D(0), D(2000)))

    def test_transfer_needs_explicit_confirmation(self):
        # 2. Chuyển khoản chưa đánh dấu đã thấy tiền về: không có đơn, không có tiền, không giữ kho.
        op = key()
        with self.assertRaises(ValidationError):
            self.prepay(spec=transfer(False), op=op)
        self.assertFalse(Order.objects.exists())
        self.assertFalse(Payment.objects.exists())
        self.assertEqual(levels(self.d["coffee"]), (D(2000), D(0), D(2000)))
        # Xác nhận rồi gửi lại: được ghi đúng một lần.
        order, _, repeated = self.prepay(spec=transfer(True))
        self.assertFalse(repeated)
        self.assertEqual((order.payment.method, order.payment.cash_received), (Payment.Method.TRANSFER, None))
        self.assertEqual(shift_services.figures(self.shift)["revenue_transfer"], 25000)

    def test_no_payment_permission_is_denied_at_server_and_logged(self):
        # 3. Phục vụ gửi thẳng yêu cầu thu trước: 403, ghi nhật ký, không có đơn. Đơn trả sau vẫn gửi được.
        payload = cart(self.d)
        payload["payment"] = cash()
        page = self.submit_json(self.d["waiter"], payload)
        self.assertEqual(page.status_code, 403)
        self.assertFalse(Order.objects.exists())
        self.assertTrue(AuditLog.objects.filter(action=Action.ACCESS_DENIED, actor=self.d["waiter"]).exists())
        self.assertNotContains(self.client.get("/don/moi/"), "Thanh toán ngay")
        page = self.submit_json(self.d["waiter"], cart(self.d))
        self.assertEqual(page.status_code, 200)
        self.assertIsNone(Order.objects.get().payment)

    def test_cashier_without_valid_assignment_cannot_prepay(self):
        other = User.objects.create_user("thungan2", password=PASSWORD, role=Role.THU_NGAN)
        payload = cart(self.d)
        payload["payment"] = cash()
        page = self.submit_json(other, payload)
        self.assertEqual(page.status_code, 403)
        self.assertIn("chưa được phân công Thu ngân", page.json()["error"])
        self.assertFalse(Order.objects.exists())
        # Có lịch phân công Thu ngân đang diễn ra thì được.
        from apps.schedule.models import Assignment, WorkShift

        local = timezone.localtime()
        start = (local - timedelta(minutes=5)).time().replace(second=0, microsecond=0)
        work = WorkShift.objects.create(store=self.d["store"], date=local.date(), name="Ca thử", start=start,
                                        end=(local + timedelta(hours=1)).time().replace(second=0, microsecond=0)
                                        if local.hour < 23 else start.replace(hour=0, minute=0))
        Assignment.objects.create(shift=work, user=other, role=Role.THU_NGAN, source="chu_quan", assigned_by=self.owner)
        self.assertEqual(prepaid.duty_problem(other), "")

    def test_no_operating_shift_blocks_prepay(self):
        self.shift.status = Shift.Status.CLOSED
        self.shift.save()
        with self.assertRaises(prepaid.PrepayDenied):
            self.prepay()
        self.assertFalse(Order.objects.exists())

    def test_repeated_submit_creates_one_order_and_one_payment(self):
        # 6a. Bấm Thu tiền và gửi pha chế hai lần (cùng mã): một đơn, một khoản thu.
        op = key()
        first, _, repeated1 = self.prepay(op=op)
        second, _, repeated2 = self.prepay(op=op)
        self.assertEqual((first.pk, repeated1, repeated2), (second.pk, False, True))
        self.assertEqual((Order.objects.count(), Payment.objects.count()), (1, 1))
        # Cùng mã mà đổi sang chuyển khoản: bị từ chối, không trả nhầm kết quả cũ.
        from apps.core.idempotency import OperationKeyError

        with self.assertRaises(OperationKeyError):
            self.prepay(op=op, spec=transfer(True))


class CashierPrepTests(Base):
    def test_cashier_confirms_partial_done_and_stock_moves_once(self):
        # 4. Thu ngân xác nhận pha xong 1 trong 3 ly: trừ tồn đúng 1 ly, bỏ giữ 1 ly, ghi ai, lúc nào, bao nhiêu.
        order, _, _ = self.prepay(quantity=3)
        line = order.lines.get()
        result = self.done(self.cashier, line, 1)
        self.assertEqual(result["applied"], 1)
        self.assertEqual(levels(self.d["coffee"]), (D(1980), D(40), D(1940)))
        order.refresh_from_db()
        self.assertEqual(order.progress_label(), "Đang pha, xong 1/3 ly")
        log = AuditLog.objects.filter(object_type="orders.OrderLine", object_id=str(line.pk)).latest("created_at")
        self.assertEqual((log.actor, log.after["so_ly"], log.after["done"]), (self.cashier, 1, 1))
        self.assertIsNotNone(log.created_at)

    def test_cashier_cannot_mark_postpaid_lines_done(self):
        result, _ = services.submit_order(self.d["waiter"], key(), cart(self.d))
        line = Order.objects.get(pk=result["order_id"]).lines.get()
        with self.assertRaises(ValidationError):
            prepaid.cashier_complete_line(self.cashier, key(), line.pk, 1, 0)

    def test_cashier_and_barista_at_the_same_time_never_exceed_quantity(self):
        # 5. Cả hai cùng thấy "đã xong 0"; pha chế ghi trước 2 ly, thu ngân gửi sau với số cũ: không trừ thêm.
        order, _, _ = self.prepay(quantity=2)
        line = order.lines.get()
        services.complete_line(self.d["barista"], key(), line.pk, 2, 0)
        late = prepaid.cashier_complete_line(self.cashier, key(), line.pk, 2, 0)[0]
        self.assertEqual(late["applied"], 0)
        # Gửi số ly vượt phần còn lại cũng chỉ nhận phần còn lại.
        order2, _, _ = self.prepay(quantity=2)
        line2 = order2.lines.get()
        self.assertEqual(self.done(self.cashier, line2, 5)["applied"], 2)
        line.refresh_from_db()
        line2.refresh_from_db()
        self.assertEqual((line.done_quantity, line2.done_quantity), (2, 2))
        self.assertEqual(levels(self.d["coffee"]), (D(1920), D(0), D(1920)))
        self.assertEqual(StockMovement.objects.filter(kind=StockMovement.Kind.CONSUME,
                                                      ingredient=self.d["coffee"]).count(), 2)

    def test_cashier_screen_endpoint_and_repeated_click(self):
        order, _, _ = self.prepay(quantity=2)
        line = order.lines.get()
        self.client.force_login(self.cashier)
        op = key()
        for _ in range(2):  # bấm hai lần cùng một biểu mẫu
            page = self.client.post(f"/thu-ngan/thu-truoc/mon/{line.pk}/xong/",
                                    {"operation_key": op, "cups": "1", "expected_done": "0"})
            self.assertEqual(page.status_code, 302)
        line.refresh_from_db()
        self.assertEqual(line.done_quantity, 1)
        self.assertEqual(levels(self.d["coffee"])[0], D(1980))


class CompleteTests(Base):
    def test_cannot_complete_until_every_cup_is_done(self):
        # 7. Còn ly chưa pha thì không hoàn tất được.
        order, _, _ = self.prepay(quantity=2)
        self.done(self.cashier, order.lines.get(), 1)
        with self.assertRaises(ValidationError) as ctx:
            prepaid.complete_order(self.cashier, key(), order.pk)
        self.assertIn("Còn 1 ly chưa pha xong.", ctx.exception.messages)
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.SENT)

    def test_pending_adjustment_blocks_completion(self):
        order, _, _ = self.prepay(quantity=2)
        line = order.lines.get()
        self.done(self.d["barista"], line, 2)
        adjustments.create_request(self.d["waiter"], key(), {"order": order.pk, "kind": "huy_mon", "line": line.pk,
                                                             "cups": 1, "reason": self.reason.pk})
        with self.assertRaises(ValidationError):
            prepaid.complete_order(self.cashier, key(), order.pk)

    def test_complete_delivers_rest_without_new_payment_or_stock(self):
        # 8. Hoàn tất: dòng đã pha thành Đã phục vụ, đơn đóng; không có khoản thu mới, không trừ kho thêm.
        order, _, _ = self.prepay(quantity=2)
        line = order.lines.get()
        self.done(self.d["barista"], line, 2)
        before = (Payment.objects.count(), StockMovement.objects.count(), shift_services.figures(self.shift))
        op = key()
        result, repeated = prepaid.complete_order(self.cashier, op, order.pk)
        self.assertEqual((result["applied"], result["delivered"], repeated), (True, 2, False))
        # 6b. Bấm hoàn tất lần nữa (cùng mã hay mã khác): không đổi gì.
        self.assertTrue(prepaid.complete_order(self.cashier, op, order.pk)[1])
        self.assertFalse(prepaid.complete_order(self.cashier, key(), order.pk)[0]["applied"])
        order.refresh_from_db()
        line.refresh_from_db()
        self.assertEqual((order.status, order.completed_by, line.status, line.served_by),
                         (Order.Status.PAID, self.cashier, OrderLine.Status.SERVED, self.cashier))
        self.assertEqual(order.progress_label(), "Đã giao, hoàn tất")
        after = (Payment.objects.count(), StockMovement.objects.count(), shift_services.figures(self.shift))
        self.assertEqual(before, after)
        self.assertEqual(levels(self.d["coffee"]), (D(1960), D(0), D(1960)))
        self.assertEqual(problems(), [])

    def test_waiter_can_serve_first_and_cashier_only_closes(self):
        order, _, _ = self.prepay()
        line = order.lines.get()
        self.done(self.d["barista"], line, 1)
        services.serve_line(self.d["waiter"], key(), line.pk)
        order.refresh_from_db()
        self.assertEqual((order.status, order.progress_label()), (Order.Status.SERVED, "Đã mang ra, chờ hoàn tất"))
        self.assertEqual(payments.tables_with_bills(), [])  # đã trả tiền nên không hiện ở phần thu theo bàn
        self.assertEqual(prepaid.complete_order(self.cashier, key(), order.pk)[0]["delivered"], 0)
        line.refresh_from_db()
        self.assertEqual(line.served_by, self.d["waiter"])

    def test_cashier_off_duty_cannot_complete(self):
        order, _, _ = self.prepay()
        self.done(self.d["barista"], order.lines.get(), 1)
        Attendance.objects.filter(user=self.cashier).update(clock_out=timezone.now())
        with self.assertRaises(prepaid.PrepayDenied):
            prepaid.complete_order(self.cashier, key(), order.pk)
        self.client.force_login(self.cashier)
        page = self.client.post(f"/thu-ngan/thu-truoc/don/{order.pk}/hoan-tat/", {"operation_key": key()})
        self.assertEqual(page.status_code, 302)
        self.assertTrue(AuditLog.objects.filter(action=Action.ACCESS_DENIED, actor=self.cashier).exists())
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.PREPARED)


class QueueTests(Base):
    def test_prepaid_orders_show_on_bar_cashier_and_overview(self):
        # 9. Đơn đã thu vẫn hiện ở quầy pha chế, màn Thu ngân và tổng quan cho đến khi hoàn tất.
        order, _, _ = self.prepay(quantity=2)
        self.assertIn(order.lines.get(), list(services.waiting_lines()))
        self.client.force_login(self.owner)
        bar = self.client.get("/quay/")
        self.assertContains(bar, order.code)
        self.assertContains(bar, "Đã thu tiền")
        cashier = self.client.get("/thu-ngan/")
        self.assertContains(cashier, "Đơn đã thu trước")
        self.assertContains(cashier, "Giao nước và hoàn tất đơn")
        self.assertContains(cashier, "Đã thu trước")
        self.assertContains(self.client.get("/don/dang-mo/"), order.code)
        from apps.orders.overview import shift_overview

        view = shift_overview(self.owner)
        tile = next(t for t in view["tables"] if t["table"] == order.table)
        self.assertEqual((tile["state"], tile["amount"], tile["prepaid"]), ("pha", 0, 1))
        self.done(self.d["barista"], order.lines.get(), 2)
        self.assertIn(order.lines.get(), list(services.ready_lines()))
        prepaid.complete_order(self.cashier, key(), order.pk)
        self.assertNotContains(self.client.get("/thu-ngan/"), "Giao nước và hoàn tất đơn")

    def test_postpaid_flow_unchanged_next_to_prepaid_order(self):
        # 12. Đơn trả sau cùng bàn: bàn chỉ thu phần trả sau, không thu lại đơn đã thu trước.
        self.prepay()
        result, _ = services.submit_order(self.d["waiter"], key(), cart(self.d))
        line = Order.objects.get(pk=result["order_id"]).lines.get()
        services.complete_line(self.d["barista"], key(), line.pk, 1, 0)
        services.serve_line(self.d["waiter"], key(), line.pk)
        bills = payments.tables_with_bills()
        self.assertEqual((len(bills), bills[0]["amount"], bills[0]["blockers"]), (1, 25000, []))
        paid, _ = payments.pay_table(self.cashier, key(), self.d["table"].pk, "tien_mat", expected=25000)
        self.assertEqual(paid["orders"], [Order.objects.get(pk=result["order_id"]).code])
        self.assertEqual(shift_services.figures(self.shift)["revenue_cash"], 50000)


class AdjustAfterPrepayTests(Base):
    def test_decrease_creates_refund_and_keeps_original_payment(self):
        # 10a. Hủy 1 trong 2 ly chưa pha sau khi đã thu: trả phần giữ kho, ghi khoản trả lại 25.000 đ chờ hoàn.
        order, _, _ = self.prepay(quantity=2)
        line = order.lines.get()
        req = self.adjust(order, "huy_mon", line=line.pk, cups=1)
        self.assertEqual(req.status, AdjustmentRequest.Status.APPROVED)
        order.refresh_from_db()
        self.assertEqual((order.total, order.payment.amount), (25000, 50000))
        self.assertEqual(levels(self.d["coffee"]), (D(2000), D(20), D(1980)))
        refund = Refund.objects.get()
        self.assertEqual((refund.kind, refund.amount, refund.status, refund.method),
                         (Refund.Kind.PREPAID_DECREASE, 25000, Refund.Status.APPROVED, Refund.Method.CASH))
        self.done(self.d["barista"], line, 1)
        with self.assertRaises(ValidationError) as ctx:
            prepaid.complete_order(self.cashier, key(), order.pk)
        self.assertIn("Còn khoản trả lại 25.000 đ chưa hoàn cho khách.", ctx.exception.messages)
        shift_services.confirm_refund(self.cashier, key(), refund.pk)
        prepaid.complete_order(self.cashier, key(), order.pk)
        figures = shift_services.figures(self.shift)
        self.assertEqual((figures["revenue_cash"], figures["refunds_cash"], figures["expected_cash"]),
                         (50000, 25000, 25000))
        from apps.reports.services import revenue

        today = timezone.localdate()
        report = revenue(today, today)
        self.assertEqual((report["total"], report["refunds"], report["net"]), (25000, 0, 25000))
        self.assertEqual(problems(), [])

    def test_increase_creates_charge_collected_into_shift(self):
        # 10b. Đổi sang món đắt hơn: khoản thu thêm 8.000 đ, thu xong mới hoàn tất; thanh toán gốc không đổi.
        order, _, _ = self.prepay()
        line = order.lines.get()
        new_line = {"item": self.d["item"].pk, "size": self.d["size_m"].pk, "options": [self.d["cream"].pk],
                    "quantity": 1, "note": ""}
        self.adjust(order, "doi_mon", line=line.pk, cups=1, new_line=new_line)
        order.refresh_from_db()
        charge = PrepaidCharge.objects.get()
        self.assertEqual((order.total, order.payment.amount, charge.amount, charge.status),
                         (33000, 25000, 8000, PrepaidCharge.Status.PENDING))
        new = order.lines.exclude(pk=line.pk).get()
        self.done(self.d["barista"], new, 1)
        with self.assertRaises(ValidationError):
            prepaid.complete_order(self.cashier, key(), order.pk)
        with self.assertRaises(ValidationError):
            prepaid.collect_charge(self.cashier, key(), charge.pk, "chuyen_khoan", False)
        op = key()
        prepaid.collect_charge(self.cashier, op, charge.pk, "tien_mat")
        self.assertTrue(prepaid.collect_charge(self.cashier, op, charge.pk, "tien_mat")[1])
        self.assertFalse(prepaid.collect_charge(self.cashier, key(), charge.pk, "tien_mat")[0]["applied"])
        charge.refresh_from_db()
        self.assertEqual((charge.status, charge.payment.kind, charge.payment.shift, charge.collected_by),
                         (PrepaidCharge.Status.COLLECTED, Payment.Kind.EXTRA, self.shift, self.cashier))
        self.assertEqual(Payment.objects.count(), 2)
        prepaid.complete_order(self.cashier, key(), order.pk)
        self.assertEqual(shift_services.figures(self.shift)["revenue_cash"], 33000)
        self.assertEqual(problems(), [])

    def test_cancel_after_prep_on_prepaid_goes_through_waste_flow(self):
        order, _, _ = self.prepay(quantity=2)
        line = order.lines.get()
        self.done(self.d["barista"], line, 2)
        self.adjust(order, "huy_mon", line=line.pk, cups=1)
        from apps.orders.models import PostPrepCancellation

        self.assertEqual(PostPrepCancellation.objects.get(line=line).cups, 1)
        self.assertEqual(levels(self.d["coffee"]), (D(1960), D(0), D(1960)))  # không trừ lần nữa
        self.assertEqual(Refund.objects.get().amount, 25000)


class ShiftCloseTests(Base):
    def test_open_prepaid_order_blocks_close_until_completed_or_carried_over(self):
        # 11. Kết ca không bỏ qua đơn đã thu trước chưa giao; không tự hoàn tất hộ.
        order, _, _ = self.prepay()
        blockers = shift_services.close_blockers(self.shift)
        self.assertTrue(any("đã thu trước nhưng chưa giao nước và hoàn tất" in b for b in blockers))
        self.assertFalse(any("chưa thanh toán" in b and order.code in b for b in blockers))
        with self.assertRaises(ValidationError):
            shift_services.close_shift(self.owner, self.shift.pk)
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.SENT)
        # Chuyển sang ca sau kèm lý do: hết chặn ở ca này, tiền vẫn ở ca đã thu.
        later = Shift.objects.create(store=self.d["store"], name="Ca tối", starts_at=self.shift.ends_at,
                                     ends_at=self.shift.ends_at + timedelta(hours=4), approver=self.owner)
        with self.assertRaises(ValidationError):
            shift_services.carry_over(self.owner, order.pk, later.pk, " ")
        shift_services.carry_over(self.owner, order.pk, later.pk, "Khách ngồi lại, giao ở ca tối")
        self.assertFalse(any(order.code in b for b in shift_services.close_blockers(self.shift)))
        order.refresh_from_db()
        self.assertEqual((order.shift, order.payment.shift), (later, self.shift))
        self.assertEqual(shift_services.figures(self.shift)["revenue_cash"], 25000)
