"""Lịch đã công bố: nhân viên thấy ai làm cùng ca với mình, ở Lịch của tôi và trong thông báo công bố."""

from datetime import time, timedelta
from unittest import mock

from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import Role, User
from apps.core.models import Store
from apps.schedule import pages
from apps.schedule import services as sv
from apps.schedule.models import RoleNeed, WeekPublish, WorkShift
from apps.staff.models import Employee

PASSWORD = "matkhau-thu-123"


class CoworkerTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("chuquan", password=PASSWORD, role=Role.CHU_QUAN)

        def emp(name, phone, roles):
            e = Employee.create_with_account(full_name=name, phone=phone, roles=roles)
            e.user.set_password(PASSWORD)
            e.user.save()
            return e.user

        self.binh = emp("Trần Văn Bình", "0900000002", [Role.PHA_CHE])
        self.lan = emp("Nguyễn Thị Lan", "0900000003", [Role.PHUC_VU])
        self.an = emp("Phạm An", "0900000004", [Role.THU_NGAN])
        self.lan2 = emp("Đỗ Ngọc Lan", "0900000005", [Role.PHA_CHE])
        self.other = emp("Võ Minh", "0900000006", [Role.PHA_CHE])
        self.week = sv.next_week()
        store = Store.get_default()
        self.morning = WorkShift.objects.create(store=store, date=self.week, name="Ca sáng", start=time(6, 30),
                                                end=time(14, 30))
        self.evening = WorkShift.objects.create(store=store, date=self.week, name="Ca chiều", start=time(14, 30),
                                                end=time(22))
        for s in (self.morning, self.evening):
            RoleNeed.objects.create(shift=s, role=Role.PHA_CHE, needed=2, suggested=2)
        sv.assign(self.owner, self.morning, self.binh, Role.PHA_CHE)
        sv.assign(self.owner, self.morning, self.lan, Role.PHUC_VU)
        sv.assign(self.owner, self.morning, self.an, Role.THU_NGAN)
        sv.assign(self.owner, self.evening, self.other, Role.PHA_CHE)

    def publish(self):
        return WeekPublish.objects.create(week_start=self.week, published_by=self.owner)

    def team(self, user):
        ctx = pages.my_page(user)
        return [x["team"] for w in ctx["weeks"] for x in w["items"]]

    def test_coworkers_listed_by_role_without_self(self):
        self.publish()
        (team,) = self.team(self.binh)
        self.assertEqual([(p["name"], p["role"]) for p in team],
                         [("Nguyễn Thị Lan", "Phục vụ"), ("Phạm An", "Thu ngân")])
        self.assertEqual([p["short"] for p in team], ["Lan", "An"])
        # Người ca khác không lọt vào danh sách.
        self.assertNotIn("Võ Minh", [p["name"] for p in team])
        (evening,) = self.team(self.other)
        self.assertEqual(evening, [])

    def test_hidden_until_published_and_removed_people_drop_out(self):
        self.assertEqual(self.team(self.binh), [])  # chưa công bố: chưa thấy ca, cũng chưa thấy ai cùng ca
        self.publish()
        a = self.morning.assignments.get(user=self.an, removed_at__isnull=True)
        with mock.patch("apps.core.push.notify_later"):
            sv.unassign(self.owner, a, "Đổi người")
        (team,) = self.team(self.binh)
        self.assertEqual([p["name"] for p in team], ["Nguyễn Thị Lan"])

    def test_only_own_shifts_are_returned(self):
        # Hỏi cả ca mình không làm: chỉ ca mình được xếp mới có danh sách.
        teams = sv.coworkers([self.morning.pk, self.evening.pk], self.binh)
        self.assertEqual(set(teams), {self.morning.pk})
        self.assertEqual(sv.coworkers([self.morning.pk], self.lan2), {})

    def test_same_given_name_uses_full_name(self):
        sv.assign(self.owner, self.morning, self.lan2, Role.PHA_CHE)
        team = sv.coworkers([self.morning.pk], self.binh)[self.morning.pk]
        self.assertEqual([p["short"] for p in team], ["Đỗ Ngọc Lan", "Nguyễn Thị Lan", "An"])

    def test_my_schedule_page_shows_coworkers(self):
        self.publish()
        self.client.force_login(self.binh)
        page = self.client.get(reverse("schedule:mine"))
        self.assertContains(page, "Cùng ca với bạn")
        self.assertContains(page, "Nguyễn Thị Lan")
        self.assertContains(page, "Phạm An")
        self.assertNotContains(page, "Võ Minh")
        self.client.force_login(self.other)
        self.assertContains(self.client.get(reverse("schedule:mine")), "Chưa có ai khác được xếp vào ca này")

    def test_publish_notification_names_coworkers(self):
        with mock.patch("apps.core.push.notify_later") as notify:
            sv.publish(self.owner, self.week)
        bodies = {c.args[0][0]: c.args[2] for c in notify.call_args_list}
        self.assertIn("cùng ca: Lan (phục vụ), An (thu ngân)", bodies[self.binh.pk])
        self.assertIn("cùng ca: Bình (pha chế), An (thu ngân)", bodies[self.lan.pk])
        self.assertNotIn("cùng ca", bodies[self.other.pk])
        self.assertNotIn("Minh", bodies[self.binh.pk])

    def test_added_after_publish_is_told_who_is_on_the_shift(self):
        self.publish()
        with mock.patch("apps.core.push.notify_later") as notify:
            sv.assign(self.owner, self.morning, self.lan2, Role.PHA_CHE)
        body = notify.call_args.args[2]
        self.assertTrue(body.startswith("Thêm ca"))
        self.assertIn("cùng ca: Bình (pha chế), Lan (phục vụ), An (thu ngân)", body)
