"""Màn Chấm công: đối chiếu lịch đã xếp với giờ vào thật, thẻ vào ra ca của nhân viên (FR-35, AC-77)."""

import uuid
from datetime import datetime, time, timedelta
from unittest import mock

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Role
from apps.orders.tests.helpers import build_menu
from apps.orders.workload import day_frames
from apps.schedule.models import Assignment, WorkShift
from apps.staff import timekeeping, today
from apps.staff.models import Attendance


def at(day, hour, minute=0):
    return timezone.make_aware(datetime.combine(day, time(hour, minute)))


class TodayBoardTests(TestCase):
    def setUp(self):
        self.d = build_menu()
        self.owner, self.barista, self.waiter = self.d["owner"], self.d["barista"], self.d["waiter"]
        self.day = timezone.localdate() - timedelta(days=1)
        store = self.d["store"]
        self.morning = WorkShift.objects.create(store=store, date=self.day, name="Ca sáng", start=time(7), end=time(12))
        self.evening = WorkShift.objects.create(store=store, date=self.day, name="Ca tối", start=time(17), end=time(22))
        for shift, user, role in ((self.morning, self.barista, Role.PHA_CHE), (self.morning, self.waiter, Role.PHUC_VU),
                                  (self.evening, self.barista, Role.PHA_CHE)):
            Assignment.objects.create(shift=shift, user=user, role=role, source="chu_quan", assigned_by=self.owner)

    def test_late_missing_waiting_and_off_schedule(self):
        Attendance.objects.create(store=self.d["store"], user=self.barista, role=Role.PHA_CHE,
                                  clock_in=at(self.day, 7, 12), clock_out=at(self.day, 12, 3))
        board = today.owner_board(now=at(self.day, 18))
        states = {(r["shift"].name, r["user"].pk): r["state"] for r in board["rows"]}
        self.assertEqual(states[("Ca sáng", self.barista.pk)], "late")  # trễ 12 phút > 5 phút
        self.assertEqual(states[("Ca sáng", self.waiter.pk)], "absent")  # hết ca mà không chấm công
        self.assertEqual(states[("Ca tối", self.barista.pk)], "missing")  # đã tới giờ, chưa vào
        self.assertEqual((board["late"], board["absent"]), (1, 2))
        early = today.owner_board(now=at(self.day, 6, 50))
        self.assertEqual({r["state"] for r in early["rows"]}, {"wait"})

    def test_missing_clock_out_gets_scheduled_end_as_guess(self):
        # Trưa hôm nay: trước giờ mở cửa thì lượt tối hôm qua chưa bị coi là quên (ca có thể qua nửa đêm).
        noon = mock.patch("django.utils.timezone.now", return_value=at(timezone.localdate(), 12))
        noon.start()
        self.addCleanup(noon.stop)
        att = Attendance.objects.create(store=self.d["store"], user=self.barista, role=Role.PHA_CHE,
                                        clock_in=at(self.day, 16, 58))
        board = today.owner_board()
        miss = [m for m in board["missing"] if m["att"] == att][0]
        self.assertEqual(miss["shift"], self.evening)
        self.assertEqual(timezone.localtime(miss["guess"]).time(), time(22))
        card = today.staff_card(self.barista)
        self.assertTrue(card["stale"])  # lượt từ hôm trước: nhắc báo Chủ quán bổ sung
        self.client.force_login(self.owner)
        page = self.client.get(reverse("staff:attendance"))
        self.assertContains(page, f'value="{miss["guess"]:%Y-%m-%dT%H:%M}"')
        self.client.post(reverse("staff:attendance"), {"action": "supplement", "attendance": att.pk,
                                                       "clock_out": f"{self.day:%Y-%m-%d}T22:00", "reason": "Quên bấm ra ca"})
        att.refresh_from_db()
        self.assertEqual(timezone.localtime(att.clock_out).time(), time(22))

    def test_staff_card_preselects_role_of_todays_shift(self):
        store = self.d["store"]
        now = timezone.now()
        shift = WorkShift.objects.create(store=store, date=timezone.localdate(), name="Ca hôm nay",
                                         start=time(0, 0), end=time(23, 59))
        Assignment.objects.create(shift=shift, user=self.barista, role=Role.PHA_CHE, source="chu_quan",
                                  assigned_by=self.owner)
        card = today.staff_card(self.barista, now=now)
        self.assertEqual(card["default_role"], Role.PHA_CHE)
        self.assertEqual(card["upcoming"]["shift"], shift)
        timekeeping.clock_in(self.barista, uuid.uuid4().hex, Role.PHA_CHE)
        card = today.staff_card(self.barista)
        self.assertFalse(card["stale"])
        self.assertEqual(card["current_shift"]["shift"], shift)

    def test_workload_hides_hours_not_yet_reached(self):
        frames = day_frames(timezone.localdate(), now=at(timezone.localdate(), 9, 30))["frames"]
        self.assertTrue(all(f["start"] < at(timezone.localdate(), 9, 30) for f in frames))
