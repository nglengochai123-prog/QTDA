"""Trang Tải và thời gian chờ: người đang trong ca được tính, số người có mặt so với số người cần theo lịch tuần."""

import uuid
from datetime import datetime, time, timedelta

from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Role
from apps.orders import services as order_services
from apps.orders.models import Order
from apps.orders.tests.helpers import PASSWORD, build_menu, cart
from apps.schedule.models import RoleNeed, WorkShift
from apps.staff import timekeeping
from apps.staff.models import Attendance
from apps.staff.views import _hour_ranges


def at(day, hour, minute=0):
    return timezone.make_aware(datetime.combine(day, time(hour, minute)))


class PresenceNowTests(TestCase):
    def setUp(self):
        self.d = build_menu()
        self.today = timezone.localdate()

    def test_people_still_in_shift_count_up_to_now(self):
        Attendance.objects.create(store=self.d["store"], user=self.d["barista"], role=Role.PHA_CHE,
                                  clock_in=at(self.today, 7))
        now = at(self.today, 9, 40)
        counts = [timekeeping.presence(at(self.today, h), at(self.today, h + 1), now=now)[Role.PHA_CHE]
                  for h in (6, 7, 8, 9)]
        # Khung 9–10 giờ đang diễn ra: có mặt cả 40 phút đã qua nên được tính, không ghi 0 người.
        self.assertEqual(counts, [0, 1, 1, 1])

    def test_forgotten_clock_out_is_not_counted(self):
        two_days = self.today - timedelta(days=2)
        Attendance.objects.create(store=self.d["store"], user=self.d["barista"], role=Role.PHA_CHE,
                                  clock_in=at(two_days, 7))
        self.assertEqual(timekeeping.presence(at(self.today, 9), at(self.today, 10), now=at(self.today, 9, 40))
                         [Role.PHA_CHE], 0)


class WorkloadAgainstScheduleTests(TestCase):
    def setUp(self):
        self.d = build_menu()
        self.day = timezone.localdate() - timedelta(days=1)
        shift = WorkShift.objects.create(store=self.d["store"], date=self.day, name="Ca sáng", start=time(7),
                                         end=time(12))
        RoleNeed.objects.create(shift=shift, role=Role.PHA_CHE, needed=2)
        Attendance.objects.create(store=self.d["store"], user=self.d["barista"], role=Role.PHA_CHE,
                                  clock_in=at(self.day, 7), clock_out=at(self.day, 12))

    def test_frames_with_fewer_people_than_planned_are_flagged(self):
        result, _ = order_services.submit_order(self.d["waiter"], uuid.uuid4().hex, cart(self.d))
        Order.objects.filter(pk=result["order_id"]).update(created_at=at(self.day, 8, 15))
        self.client.login(username=self.d["owner"].username, password=PASSWORD)
        page = self.client.get(reverse("staff:workload"), {"ngay": self.day.isoformat()})
        frame = next(f for f in page.context["frames"] if f["label"] == "08–09 giờ")
        cell = frame["presence_cells"][timekeeping.WORK_ROLES.index(Role.PHA_CHE)]
        self.assertEqual((cell["n"], cell["need"], cell["short"]), (1, 2, True))
        # Ly gọi lúc 8 giờ 15 chưa pha nên 9–12 giờ vẫn còn tải; cả bốn khung chỉ 1/2 pha chế, gộp thành một khoảng.
        self.assertEqual(page.context["short_frames"], ["08–12 giờ"])
        self.assertEqual(page.context["short_count"], 4)
        self.assertIn("Pha chế", page.context["short_roles"])
        self.assertContains(page, "Thiếu người so với lịch")


class HourRangeTests(SimpleTestCase):
    def test_consecutive_frames_are_merged(self):
        self.assertEqual(_hour_ranges([6, 7, 8, 13, 22, 23]), ["06–09 giờ", "13–14 giờ", "22–24 giờ"])
        self.assertEqual(_hour_ranges([]), [])
