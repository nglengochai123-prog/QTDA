"""Rà soát 27/10/2026 (đợt 2): ra ca qua nửa đêm, đơn chưa gắn ca, lịch làm, trang quản trị chỉ xem,
lịch sử đã trả, bộ đệm bảng điều khiển, hoàn tiền mặt khi két thiếu."""

import uuid
from datetime import datetime, time, timedelta
from unittest import mock

from django.test import Client, TestCase
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.core.models import Store
from apps.orders.tests.helpers import PASSWORD
from apps.orders.tests.test_adjust_pay import Base


def _local(day, hour, minute=0):
    return timezone.make_aware(datetime.combine(day, time(hour, minute)))


class MidnightClockOutTests(TestCase):
    def setUp(self):
        from apps.staff.models import Attendance

        self.user = User.objects.create_user("phache", password=PASSWORD, role=Role.PHA_CHE)
        self.day = timezone.localdate() - timedelta(days=1)
        self.att = Attendance.objects.create(store=Store.get_default(), user=self.user, role=Role.PHA_CHE,
                                             clock_in=_local(self.day, 17))

    def test_evening_shift_past_midnight_is_still_running(self):
        from apps.staff import timekeeping, today

        after_midnight = _local(self.day + timedelta(days=1), 0, 10)
        self.assertFalse(timekeeping.is_forgotten(self.att, after_midnight))
        self.assertNotIn(self.att, list(timekeeping.missing_clock_out(after_midnight)))
        self.assertFalse(today.staff_card(self.user, after_midnight)["stale"])
        # Tới giờ mở cửa hôm sau mà vẫn chưa ra ca thì là quên bấm Ra ca.
        morning = _local(self.day + timedelta(days=1), 7)
        self.assertTrue(timekeeping.is_forgotten(self.att, morning))
        self.assertIn(self.att, list(timekeeping.missing_clock_out(morning)))


class OrphanOrderTests(Base):
    def test_order_sent_without_shift_is_adopted_by_the_new_shift_or_blocks_closing(self):
        from apps.shifts.models import Shift
        from apps.shifts.services import close_blockers

        Shift.objects.update(status=Shift.Status.CLOSED)
        order, _ = self.order()
        self.assertIsNone(order.shift)
        # Ca đang mở nhưng đơn vẫn chưa gắn ca (đơn cũ): kết ca phải nhắc tới đơn này.
        Shift.objects.filter(pk=self.shift.pk).update(status=Shift.Status.OPEN)
        self.assertTrue(any(order.code in b and "chưa có ca" in b for b in close_blockers(self.shift)))
        Shift.objects.update(status=Shift.Status.CLOSED)
        c = Client()
        c.force_login(self.manager)
        now = timezone.localtime()
        r = c.post("/du-lieu/ca/moi/", {"name": "Ca tối", "starts_at": f"{now - timedelta(minutes=5):%Y-%m-%dT%H:%M}",
                                         "ends_at": f"{now + timedelta(hours=3):%Y-%m-%dT%H:%M}"}, follow=True)
        order.refresh_from_db()
        self.assertEqual(order.shift.name, "Ca tối")
        self.assertContains(r, f"Đã gắn 1 đơn chưa thanh toán gửi lúc chưa có ca vào Ca tối: {order.code}")


class ScheduleFixTests(TestCase):
    def setUp(self):
        from apps.schedule import services as sv
        from apps.schedule.models import WorkShift
        from apps.staff.models import Employee

        self.sv = sv
        self.owner = User.objects.create_user("chuquan", password=PASSWORD, role=Role.CHU_QUAN)
        self.b1 = Employee.create_with_account(full_name="Trần Bình", phone="0900000002", roles=[Role.PHA_CHE]).user
        self.b2 = Employee.create_with_account(full_name="Lê Cường", phone="0900000003", roles=[Role.PHA_CHE]).user
        self.week = sv.next_week()
        self.day = self.week + timedelta(days=5)
        self.evening = WorkShift.objects.create(store=Store.get_default(), date=self.day, name="Ca tối",
                                                start=time(17), end=time(22))

    def test_rerunning_suggestions_after_publish_keeps_unchanged_rows(self):
        from apps.schedule.models import Assignment, RoleNeed

        RoleNeed.objects.create(shift=self.evening, role=Role.PHA_CHE, needed=1)
        before = self.sv.deadline_for(self.week) - timedelta(hours=1)
        self.sv.register(self.b1, {self.evening.pk: Role.PHA_CHE}, now=before)
        self.assertEqual(self.sv.auto_assign(self.owner, self.week), 1)
        self.sv.publish(self.owner, self.week)
        first = Assignment.objects.get(removed_at__isnull=True)
        with mock.patch("apps.core.push.send_to_user", return_value=(1, "")) as send:
            with self.captureOnCommitCallbacks(execute=True):
                self.assertEqual(self.sv.auto_assign(self.owner, self.week), 0)
        self.assertEqual(Assignment.objects.get(removed_at__isnull=True), first)
        self.assertFalse(Assignment.objects.filter(removed_at__isnull=False).exists())
        self.assertFalse(send.called)
        c = Client()
        c.force_login(self.owner)
        self.assertNotContains(c.get(f"/lich/?tuan={self.week:%Y-%m-%d}"), "Có thay đổi chưa công bố")

    def test_shift_ending_at_midnight_counts_to_end_of_day(self):
        from apps.schedule.models import WorkShift

        c = Client()
        c.force_login(self.owner)
        c.post("/lich/", {"action": "add_shift", "tuan": f"{self.week:%Y-%m-%d}", "days": [f"{self.day:%Y-%m-%d}"],
                          "name": "Ca khuya", "start": "18:00", "end": "00:00"})
        late = WorkShift.objects.get(name="Ca khuya")
        self.assertEqual(late.hours, 6)
        self.assertTrue(late.overlaps(self.evening))
        self.assertEqual(late.end_datetime, datetime.combine(self.day + timedelta(days=1), time.min))
        c.post("/lich/", {"action": "add_shift", "tuan": f"{self.week:%Y-%m-%d}", "days": [f"{self.day:%Y-%m-%d}"],
                          "name": "Ca lỗi", "start": "18:00", "end": "17:00"})
        self.assertFalse(WorkShift.objects.filter(name="Ca lỗi").exists())

    def test_deleting_a_shift_tells_people_who_registered(self):
        before = self.sv.deadline_for(self.week) - timedelta(hours=1)
        self.sv.register(self.b1, {self.evening.pk: Role.PHA_CHE}, now=before)
        c = Client()
        c.force_login(self.owner)
        page = c.get(f"/lich/?tuan={self.week:%Y-%m-%d}")
        self.assertContains(page, "1 người đã đăng ký ca này sẽ được báo ca bị bỏ")
        with mock.patch("apps.core.push.send_to_user", return_value=(1, "")) as send:
            with self.captureOnCommitCallbacks(execute=True):
                r = c.post("/lich/", {"action": "delete_shift", "tuan": f"{self.week:%Y-%m-%d}",
                                      "shift": self.evening.pk}, follow=True)
        self.assertContains(r, "Đã báo 1 người đã đăng ký ca này")
        self.assertEqual([x.args[0] for x in send.call_args_list], [self.b1])


class PaidHistoryTests(Base):
    def test_paid_list_filters_by_month_and_supplier(self):
        from apps.inventory.models import Payable, Receipt, Supplier, SupplierPayment

        a = Supplier.objects.create(store=self.d["store"], name="Sữa An Phú")
        b = Supplier.objects.create(store=self.d["store"], name="Cà phê Bình")
        today = timezone.localdate()
        last_month = (today.replace(day=1) - timedelta(days=1)).replace(day=10)
        for i, (sup, day, amount) in enumerate(((a, today, 111000), (b, today, 222000), (a, last_month, 450000))):
            receipt = Receipt.objects.create(store=self.d["store"], code=f"PN-{i}", supplier=sup, payment_type="no",
                                             total=amount, created_by=self.manager, operation_key=uuid.uuid4().hex)
            p = Payable.objects.create(store=self.d["store"], receipt=receipt, supplier=sup, amount=amount, due_date=today)
            SupplierPayment.objects.create(payable=p, amount=amount, paid_on=day, source="chuyen_khoan", actor=self.manager)
        c = Client()
        c.force_login(self.manager)
        page = c.get("/kho/phai-tra/")
        self.assertContains(page, "111.000 đ")
        self.assertContains(page, "222.000 đ")
        self.assertNotContains(page, "450.000 đ")
        page = c.get(f"/kho/phai-tra/?thang={last_month:%Y-%m}&ncc={a.pk}")
        self.assertContains(page, "450.000 đ")
        self.assertNotContains(page, "111.000 đ")


class DashboardCacheTests(Base):
    def test_second_view_reuses_figures_until_money_moves(self):
        from apps.orders import payments
        from apps.reports import services as reports

        c = Client()
        c.force_login(self.manager)
        c.get("/bang-dieu-khien/")
        with mock.patch.object(reports, "paid_lines", wraps=reports.paid_lines) as spy:
            c.get("/bang-dieu-khien/")
            self.assertFalse(spy.called)
            order, line = self.order()
            self.finish(line)
            payments.pay_table(self.cashier, uuid.uuid4().hex, order.table_id, "tien_mat")
            c.get("/bang-dieu-khien/")
            self.assertTrue(spy.called)


class CashRefundWarningTests(Base):
    def test_cash_refund_larger_than_drawer_is_recorded_with_a_warning(self):
        from apps.shifts import services as shifts
        from apps.shifts.models import Refund

        payment_order, line = self.order()
        self.finish(line)
        from apps.orders import payments

        payments.pay_table(self.cashier, uuid.uuid4().hex, payment_order.table_id, "tien_mat")
        payment_order.refresh_from_db()
        refund = Refund.objects.create(store=self.d["store"], payment=payment_order.payment, order_code=payment_order.code,
                                       method=Refund.Method.CASH, amount=900000, approved_by=self.manager,
                                       request_id_ref=1)
        rows = shifts.refund_rows(self.shift)
        self.assertIn("ít hơn khoản hoàn 900.000 đ", rows[0][2])
        result, _ = shifts.confirm_refund(self.cashier, uuid.uuid4().hex, refund.pk)
        self.assertIn("theo sổ chỉ còn", result["warning"])
        refund.refresh_from_db()
        self.assertEqual(refund.status, Refund.Status.PAID)


class AdminReadOnlyTests(TestCase):
    def test_app_managed_data_is_view_only_in_admin(self):
        owner = User.objects.create_user("chu", password=PASSWORD, role=Role.CHU_QUAN)
        c = Client()
        c.force_login(owner)
        for model in ("catalog/table", "catalog/menuitem", "inventory/ingredient", "shifts/shift", "staff/employee"):
            self.assertEqual(c.get(f"/quan-tri/{model}/add/").status_code, 403, model)
            self.assertEqual(c.get(f"/quan-tri/{model}/").status_code, 200, model)
