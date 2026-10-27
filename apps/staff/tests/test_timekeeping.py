"""Chấm công (FR-35, AC-76 đến AC-78) và tải theo khung giờ (FR-36, AC-79)."""

import uuid
from datetime import datetime, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import Role
from apps.catalog.models import ItemSize, MenuGroup, MenuItem
from apps.core import periodic
from apps.orders.models import Order, OrderLine
from apps.orders.tests.helpers import build_menu
from apps.orders.workload import day_frames
from apps.staff import timekeeping
from apps.staff.models import Attendance


def key():
    return uuid.uuid4().hex


def at(day, hour, minute=0):
    return timezone.make_aware(datetime.combine(day, datetime.min.time()) + timedelta(hours=hour, minutes=minute))


class AttendanceTests(TestCase):
    def setUp(self):
        self.d = build_menu()
        self.barista = self.d["barista"]
        self.owner = self.d["owner"]
        self.yesterday = timezone.localdate() - timedelta(days=1)

    def test_clock_in_with_own_role_and_out_once(self):
        with self.assertRaises(ValidationError):
            timekeeping.clock_in(self.barista, key(), Role.THU_NGAN)  # không đảm nhận vai trò này
        op = key()
        timekeeping.clock_in(self.barista, op, Role.PHA_CHE)
        timekeeping.clock_in(self.barista, op, Role.PHA_CHE)  # gửi lại
        with self.assertRaises(ValidationError):
            timekeeping.clock_in(self.barista, key(), Role.PHA_CHE)  # đang trong ca
        timekeeping.clock_out(self.barista, key())
        self.assertEqual(Attendance.objects.count(), 1)

    def test_ac76_presence_by_role(self):
        Attendance.objects.create(store=self.d["store"], user=self.barista, role=Role.PHA_CHE,
                                  clock_in=at(self.yesterday, 16, 55), clock_out=at(self.yesterday, 22, 5))
        present = [h for h in range(24) if timekeeping.presence(at(self.yesterday, h), at(self.yesterday, h + 1))[Role.PHA_CHE]]
        self.assertEqual(present, [17, 18, 19, 20, 21])

    def test_ac77_ac78_missing_out_then_supplemented(self):
        att = Attendance.objects.create(store=self.d["store"], user=self.barista, role=Role.PHA_CHE,
                                        clock_in=at(self.yesterday, 17))
        self.assertEqual(list(timekeeping.missing_clock_out()), [att])
        self.assertEqual(timekeeping.valid_hours(att), Decimal(0))
        periodic.run_all()
        periodic.run_all()
        from apps.audit.models import AuditLog

        self.assertEqual(AuditLog.objects.filter(reason=timekeeping.MISSING_OUT).count(), 1)
        with self.assertRaises(ValidationError):
            timekeeping.supplement_clock_out(self.owner, att.pk, at(self.yesterday, 22), "")
        with self.assertRaises(ValidationError):
            timekeeping.supplement_clock_out(self.barista, att.pk, at(self.yesterday, 22), "Quên")
        older = Attendance.objects.create(store=self.d["store"], user=self.owner, role=Role.PHA_CHE,
                                          clock_in=at(self.yesterday - timedelta(days=2), 17))
        with self.assertRaisesMessage(ValidationError, "kiểm tra lại ngày giờ ra"):  # chọn nhầm sang ngày sau
            timekeeping.supplement_clock_out(self.owner, older.pk, at(self.yesterday - timedelta(days=1), 22), "Quên")
        att = timekeeping.supplement_clock_out(self.owner, att.pk, at(self.yesterday, 22), "Quên thao tác")
        self.assertEqual(timekeeping.valid_hours(att), Decimal("5.00"))
        self.assertEqual(list(timekeeping.missing_clock_out()), [older])


    def test_clock_out_from_page_left_open_overnight_is_refused(self):
        att = Attendance.objects.create(store=self.d["store"], user=self.barista, role=Role.PHA_CHE,
                                        clock_in=timezone.now() - timedelta(hours=20))
        with self.assertRaisesMessage(ValidationError, "báo Chủ quán bổ sung giờ ra"):
            timekeeping.clock_out(self.barista, key())
        att.refresh_from_db()
        self.assertIsNone(att.clock_out)  # không tính 20 giờ vào giờ công
        att.clock_in = timezone.now() - timedelta(hours=9)
        att.save()
        timekeeping.clock_out(self.barista, key())
        att.refresh_from_db()
        self.assertIsNotNone(att.clock_out)


class WorkloadTests(TestCase):
    def test_ac79_load_and_overload(self):
        d = build_menu()
        day = timezone.localdate() - timedelta(days=1)
        groups = {name: MenuGroup.objects.create(store=d["store"], name=name, load_factor=Decimal(f))
                  for name, f in (("Pha máy", "1.0"), ("Đá xay", "1.5"), ("Đóng chai", "0.3"))}
        sent = at(day, 19, 10)
        waits = iter([14] * 26 + [5] * 24)
        for name, cups in (("Pha máy", 30), ("Đá xay", 10), ("Đóng chai", 10)):
            item = MenuItem.objects.create(store=d["store"], group=groups[name], name=name)
            size = ItemSize.objects.create(item=item, name="M", price=10000)
            for _ in range(cups):
                order = Order.objects.create(store=d["store"], code=key()[:12], table=d["table"], created_by=d["waiter"],
                                             operation_key=key(), total=10000)
                Order.objects.filter(pk=order.pk).update(created_at=sent)
                served = sent + timedelta(minutes=next(waits))
                OrderLine.objects.create(order=order, position=1, item=item, size=size, item_name=name, size_name="M",
                                         unit_price=10000, quantity=1, done_quantity=1, status=OrderLine.Status.SERVED,
                                         done_at=served, served_at=served)
        frame = [f for f in day_frames(day)["frames"] if f["start"] == at(day, 19)][0]
        self.assertEqual(frame["load"], Decimal("48.0"))
        self.assertEqual(frame["median_wait"], Decimal("14.0"))
        self.assertTrue(frame["overloaded"])

    def test_waiting_cup_left_overnight_is_not_load_after_closing(self):
        d = build_menu()
        day = timezone.localdate() - timedelta(days=2)
        order = Order.objects.create(store=d["store"], code=key()[:12], table=d["table"], created_by=d["waiter"],
                                     operation_key=key(), total=10000)
        Order.objects.filter(pk=order.pk).update(created_at=at(day, 21, 50))
        size = ItemSize.objects.first()
        OrderLine.objects.create(order=order, position=1, item=size.item, size=size, item_name="Món", size_name="M",
                                 unit_price=10000, quantity=1)
        hours = [timezone.localtime(f["start"]).hour for f in day_frames(day + timedelta(days=1))["frames"]]
        self.assertTrue(hours)
        self.assertTrue(all(6 <= h < 22 for h in hours), hours)  # ly chờ từ tối trước không tạo khung lúc 0–5 giờ
