"""Ca quỹ lấy từ lịch làm tuần: tạo khi công bố, cập nhật khi công bố lại, thu ngân mở đúng ca trong lịch."""

from datetime import datetime, time, timedelta

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.core.models import Store
from apps.schedule import services as sv
from apps.schedule.models import RoleNeed, WeekPublish, WorkShift
from apps.shifts import from_schedule
from apps.shifts.models import Shift
from apps.staff.models import Employee

PASSWORD = "matkhau-thu-123"


def emp(name, phone, roles):
    e = Employee.create_with_account(full_name=name, phone=phone, roles=roles)
    e.user.set_password(PASSWORD)
    e.user.save()
    return e.user


class SyncOnPublishTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("chuquan", password=PASSWORD, role=Role.CHU_QUAN)
        self.cashier = emp("Phạm An", "0900000004", [Role.THU_NGAN])
        self.barista = emp("Trần Bình", "0900000002", [Role.PHA_CHE])
        self.week = sv.next_week()
        store = Store.get_default()
        self.morning = WorkShift.objects.create(store=store, date=self.week, name="Ca sáng", start=time(6),
                                                end=time(14))
        self.bar_only = WorkShift.objects.create(store=store, date=self.week, name="Ca gãy", start=time(10),
                                                 end=time(13))
        sv.assign(self.owner, self.morning, self.cashier, Role.THU_NGAN)
        sv.assign(self.owner, self.bar_only, self.barista, Role.PHA_CHE)

    def test_publish_creates_cash_shift_only_for_shifts_with_a_cashier(self):
        pub = sv.publish(self.owner, self.week)
        self.assertEqual(pub.cash_shifts["created"], 1)
        cash = Shift.objects.get(work_shift=self.morning)
        start = timezone.make_aware(datetime.combine(self.week, time(6)))
        self.assertEqual((cash.name, cash.starts_at, cash.ends_at - cash.starts_at), ("Ca sáng", start, timedelta(hours=8)))
        self.assertEqual((cash.approver, cash.payment_authorizer), (self.owner, self.cashier))
        self.assertFalse(Shift.objects.filter(work_shift=self.bar_only).exists())  # ca chỉ có pha chế không giữ quỹ

    def test_republish_updates_future_cash_shift_and_does_not_duplicate(self):
        sv.publish(self.owner, self.week)
        self.morning.end = time(15)
        self.morning.save()
        pub = sv.publish(self.owner, self.week)
        self.assertEqual((pub.cash_shifts["created"], pub.cash_shifts["updated"]), (0, 1))
        cash = Shift.objects.get(work_shift=self.morning)
        self.assertEqual(timezone.localtime(cash.ends_at).hour, 15)
        self.assertEqual(Shift.objects.count(), 1)

    def test_manual_shift_with_same_name_and_start_is_linked_not_duplicated(self):
        start = timezone.make_aware(datetime.combine(self.week, time(6)))
        manual = Shift.objects.create(store=Store.get_default(), name="Ca sáng", starts_at=start, ends_at=start + timedelta(hours=8),
                                      approver=self.owner)
        sv.publish(self.owner, self.week)
        manual.refresh_from_db()
        self.assertEqual(manual.work_shift, self.morning)
        self.assertEqual(Shift.objects.count(), 1)

    def test_removing_cashier_drops_empty_future_cash_shift(self):
        sv.publish(self.owner, self.week)
        sv.unassign(self.owner, self.morning.assignments.get(user=self.cashier), "đổi lịch")
        pub = sv.publish(self.owner, self.week)
        self.assertEqual(pub.cash_shifts["removed"], 1)
        self.assertFalse(Shift.objects.exists())

    def test_need_without_assignment_still_makes_cash_shift(self):
        RoleNeed.objects.create(shift=self.bar_only, role=Role.THU_NGAN, needed=1)
        sv.publish(self.owner, self.week)
        cash = Shift.objects.get(work_shift=self.bar_only)
        self.assertIsNone(cash.payment_authorizer)


class OpenFromScheduleTests(TestCase):
    """Thu ngân mở ca khi ca trong lịch đã tới giờ mà ca quỹ còn thiếu (ví dụ lịch công bố trước khi có tính năng)."""

    def setUp(self):
        self.owner = User.objects.create_user("chuquan", password=PASSWORD, role=Role.CHU_QUAN)
        self.cashier = emp("Phạm An", "0900000004", [Role.THU_NGAN])
        self.waiter = emp("Lê Hà", "0900000005", [Role.PHUC_VU])
        self.now = timezone.localtime().replace(hour=9, minute=0, second=0, microsecond=0)
        day = self.now.date()
        self.ws = WorkShift.objects.create(store=Store.get_default(), date=day, name="Ca sáng", start=time(8),
                                           end=time(14))
        sv.assign(self.owner, self.ws, self.cashier, Role.THU_NGAN)
        WeekPublish.objects.create(week_start=sv.week_start(day), published_by=self.owner)  # công bố, chưa có ca quỹ

    def test_cashier_opens_exactly_the_scheduled_shift(self):
        self.assertEqual(from_schedule.openable(self.now), [self.ws])
        shift, created = from_schedule.open_from_schedule(self.cashier, self.ws.pk, now=self.now)
        self.assertTrue(created)
        self.assertEqual((shift.approver, shift.payment_authorizer, shift.work_shift), (self.owner, self.cashier, self.ws))
        self.assertEqual(timezone.localtime(shift.starts_at).hour, 8)
        again, created = from_schedule.open_from_schedule(self.cashier, self.ws.pk, now=self.now)
        self.assertEqual((again.pk, created), (shift.pk, False))  # bấm hai lần không tạo hai ca
        self.assertEqual(from_schedule.openable(self.now), [])

    def test_waiter_cannot_open_even_by_posting_directly(self):
        with self.assertRaises(ValidationError):
            from_schedule.open_from_schedule(self.waiter, self.ws.pk, now=self.now)
        self.client.login(username=self.waiter.username, password=PASSWORD)
        r = self.client.post(reverse("shifts:open_from_schedule"), {"work_shift": self.ws.pk})
        self.assertEqual(r.status_code, 403)
        self.assertFalse(Shift.objects.exists())

    def test_not_before_time_and_not_when_unpublished(self):
        early = self.now.replace(hour=7, minute=0)
        with self.assertRaisesMessage(ValidationError, "Chưa tới giờ"):
            from_schedule.open_from_schedule(self.cashier, self.ws.pk, now=early)
        WeekPublish.objects.all().delete()
        with self.assertRaises(ValidationError):
            from_schedule.open_from_schedule(self.cashier, self.ws.pk, now=self.now)
        self.assertFalse(Shift.objects.exists())

    def test_not_when_a_cash_shift_is_already_running(self):
        Shift.objects.create(store=Store.get_default(), name="Ca tay", starts_at=self.now - timedelta(hours=1), ends_at=self.now + timedelta(hours=3),
                             approver=self.owner)
        self.assertEqual(from_schedule.openable(self.now), [])
        with self.assertRaisesMessage(ValidationError, "Đang có ca quỹ"):
            from_schedule.open_from_schedule(self.cashier, self.ws.pk, now=self.now)

    def test_button_shows_on_my_shift_page_for_cashier(self):
        from unittest import mock

        self.client.login(username=self.cashier.username, password=PASSWORD)
        with mock.patch("django.utils.timezone.now", return_value=self.now):
            html = self.client.get(reverse("shifts:my_shift")).content.decode()
        self.assertIn("Mở ca sáng 08:00–14:00 theo lịch", html)
