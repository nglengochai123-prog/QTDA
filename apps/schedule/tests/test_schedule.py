"""Đăng ký ca và lập lịch (FR-38, FR-39, AC-84 đến AC-88, BRU-28 đến BRU-30)."""

from datetime import time, timedelta
from unittest import mock

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.audit.models import AuditLog
from apps.core.models import Store
from apps.schedule import services as sv
from apps.schedule.models import Assignment, RoleNeed, WeekPublish, WorkShift
from apps.staff.models import Employee

PASSWORD = "matkhau-thu-123"


class ScheduleTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("chuquan", password=PASSWORD, role=Role.CHU_QUAN)

        def emp(name, phone, roles):
            e = Employee.create_with_account(full_name=name, phone=phone, roles=roles)
            e.user.set_password(PASSWORD)
            e.user.save()
            return e.user

        self.waiter = emp("Nguyễn An", "0900000001", [Role.PHUC_VU])
        self.b1 = emp("Trần Bình", "0900000002", [Role.PHA_CHE])
        self.b2 = emp("Lê Cường", "0900000003", [Role.PHA_CHE, Role.PHUC_VU])
        self.b3 = emp("Phạm Dung", "0900000004", [Role.PHA_CHE])
        self.week = sv.next_week()
        self.before_deadline = sv.deadline_for(self.week) - timedelta(hours=1)
        store = Store.get_default()
        self.saturday = self.week + timedelta(days=5)
        self.evening = WorkShift.objects.create(store=store, date=self.saturday, name="Ca tối", start=time(17), end=time(22))
        self.afternoon = WorkShift.objects.create(store=store, date=self.saturday, name="Ca chiều", start=time(16), end=time(21))

    def test_ac84_register_only_own_roles(self):
        sv.register(self.waiter, {self.evening.pk: Role.PHUC_VU}, now=self.before_deadline)
        self.assertEqual(self.evening.registrations.get().role, Role.PHUC_VU)
        with self.assertRaises(ValidationError):
            sv.register(self.waiter, {self.evening.pk: Role.PHA_CHE}, now=self.before_deadline)
        self.client.login(username=self.waiter.username, password=PASSWORD)
        page = self.client.get(reverse("schedule:register"), {"tuan": self.week.isoformat()})
        self.assertContains(page, "Phục vụ")
        self.assertNotContains(page, 'value="pha_che"')

    def test_ac85_after_deadline_only_owner_and_logged(self):
        late = sv.deadline_for(self.week) + timedelta(minutes=1)
        with self.assertRaises(ValidationError):
            sv.register(self.b1, {self.evening.pk: Role.PHA_CHE}, now=late)
        sv.assign(self.owner, self.evening, self.b1, Role.PHA_CHE)
        self.assertTrue(AuditLog.objects.filter(object_type="schedule.Assignment").exists())

    def test_ac86_short_and_surplus_per_role(self):
        RoleNeed.objects.create(shift=self.evening, role=Role.PHA_CHE, needed=3)
        RoleNeed.objects.create(shift=self.evening, role=Role.PHUC_VU, needed=2)
        for u, role in ((self.b1, Role.PHA_CHE), (self.b3, Role.PHA_CHE), (self.waiter, Role.PHUC_VU),
                        (self.b2, Role.PHUC_VU)):
            Assignment.objects.create(shift=self.evening, user=u, role=role, source="chu_quan", assigned_by=self.owner)
        extra = User.objects.create_user("phucvu2", password=PASSWORD, role=Role.PHUC_VU)
        Assignment.objects.create(shift=self.evening, user=extra, role=Role.PHUC_VU, source="chu_quan", assigned_by=self.owner)
        rows, gaps = sv.coverage(self.week)
        cells = {c["role"]: c for c in rows[[r["shift"] for r in rows].index(self.evening)]["cells"]}
        self.assertEqual((cells[Role.PHA_CHE]["short"], cells[Role.PHUC_VU]["surplus"]), (1, 1))  # tổng 5 = 5 vẫn báo
        self.assertTrue(any("thiếu 1 pha chế" in g for g in gaps))

    def test_ac87_no_overlap_and_replacement_suggestions(self):
        sv.assign(self.owner, self.afternoon, self.b2, Role.PHA_CHE)  # 16–21
        with self.assertRaises(ValidationError):
            sv.assign(self.owner, self.evening, self.b2, Role.PHA_CHE)  # 17–22 trùng giờ
        a = sv.assign(self.owner, self.evening, self.b1, Role.PHA_CHE)
        sv.unassign(self.owner, a, "Báo nghỉ")
        names = [x["user"] for x in sv.replacements(self.evening, Role.PHA_CHE)]
        self.assertIn(self.b1, names)
        self.assertIn(self.b3, names)
        self.assertNotIn(self.b2, names)  # có ca trùng giờ
        self.assertNotIn(self.waiter, names)  # không có kỹ năng pha chế

    def test_auto_assign_from_registrations_scarce_first_keeps_manual(self):
        RoleNeed.objects.create(shift=self.evening, role=Role.PHA_CHE, needed=2)
        RoleNeed.objects.create(shift=self.afternoon, role=Role.PHA_CHE, needed=1)
        RoleNeed.objects.create(shift=self.evening, role=Role.PHUC_VU, needed=1)
        for u, shift, role in ((self.b1, self.evening, Role.PHA_CHE), (self.b2, self.evening, Role.PHA_CHE),
                               (self.b2, self.afternoon, Role.PHA_CHE), (self.waiter, self.evening, Role.PHUC_VU)):
            sv.register(u, {shift.pk: role}, now=self.before_deadline)
        manual = sv.assign(self.owner, self.evening, self.b3, Role.PHA_CHE)
        made = sv.auto_assign(self.owner, self.week)
        rows, gaps = sv.coverage(self.week)
        active = Assignment.objects.filter(removed_at__isnull=True)
        self.assertIn(manual, active)
        # b2 đăng ký cả hai ca trùng giờ: chỉ được xếp một ca
        self.assertEqual(active.filter(user=self.b2).count(), 1)
        self.assertEqual(active.filter(shift=self.evening, role=Role.PHA_CHE).count(), 2)
        self.assertTrue(made >= 2)
        sv.auto_assign(self.owner, self.week)  # chạy lại không nhân đôi
        self.assertEqual(Assignment.objects.filter(removed_at__isnull=True, shift=self.evening, role=Role.PHA_CHE).count(), 2)

    def test_ac88_publish_needs_confirmation_and_notifies(self):
        RoleNeed.objects.create(shift=self.evening, role=Role.PHA_CHE, needed=2)
        sv.assign(self.owner, self.evening, self.b1, Role.PHA_CHE)
        self.client.login(username=self.owner.username, password=PASSWORD)
        url = reverse("schedule:board") + f"?tuan={self.week.isoformat()}"
        self.client.post(url, {"action": "publish", "tuan": self.week.isoformat()})
        self.assertFalse(WeekPublish.objects.exists())
        with mock.patch("apps.core.push.send_to_user", return_value=(1, "")) as send:
            with self.captureOnCommitCallbacks(execute=True):
                self.client.post(url, {"action": "publish", "tuan": self.week.isoformat(), "confirm": "1"})
        pub = WeekPublish.objects.get()
        self.assertTrue(pub.gaps)  # còn thiếu 1 pha chế lúc công bố
        self.assertEqual([c.args[0] for c in send.call_args_list], [self.b1])
        self.client.login(username=self.b1.username, password=PASSWORD)
        self.assertContains(self.client.get(reverse("schedule:mine")), "Ca tối")

    def test_need_suggestion_queue_model_and_cover(self):
        inputs = {"today": timezone.localdate(), "scv": 1.0,
                  "profile": ({True: {17: 0.2, 18: 0.3, 19: 0.1}, False: {}}, 1.0),
                  "rates": {Role.PHA_CHE: {"value": 40.0, "source": "Chủ quán đặt", "kind": "owner"},
                            Role.PHUC_VU: {"value": 40.0, "source": "Chủ quán đặt", "kind": "owner"},
                            Role.THU_NGAN: None}}
        with mock.patch("apps.schedule.services._daily_cups", return_value=(100.0, "Dự báo")):
            out = sv.suggest_day(self.saturday, [self.afternoon, self.evening], inputs)
            single = sv.suggest_needs(self.evening, inputs=inputs)
        # Giờ 18: tải 30 với sức làm 40 cần 2 người để 70% ly chờ không quá 4 phút; hai ca chồng giờ 17–21 chia nhau
        # nên mỗi ca 1 người, không phải 2 + 2 như lấy giờ cao nhất của từng ca.
        self.assertEqual(out[self.afternoon.pk][Role.PHA_CHE][0], 1)
        self.assertEqual(out[self.evening.pk][Role.PHA_CHE][0], 1)
        self.assertEqual(single[Role.PHA_CHE], out[self.evening.pk][Role.PHA_CHE])
        basis = out[self.evening.pk][Role.PHA_CHE][1]
        self.assertIn([18, 30.0, 2], basis["hours"])
        self.assertEqual(basis["uncovered"], list(range(6, 16)))  # quán mở 6 giờ nhưng chưa có ca sáng
        self.assertIsNone(out[self.evening.pk][Role.THU_NGAN][0])  # thiếu sức làm: Chủ quán nhập tay
        RoleNeed.objects.create(shift=self.evening, role=Role.PHA_CHE, needed=1, suggested=1)
        with self.assertRaises(ValidationError):
            sv.set_need(self.owner, self.evening, Role.PHA_CHE, 2)  # khác gợi ý phải có lý do
        sv.set_need(self.owner, self.evening, Role.PHA_CHE, 2, "Có sự kiện")

    def test_screens_and_permissions(self):
        self.client.login(username=self.owner.username, password=PASSWORD)
        url = reverse("schedule:board") + f"?tuan={self.week.isoformat()}"
        self.client.post(url, {"action": "add_shift", "tuan": self.week.isoformat(), "name": "Ca sáng", "start": "06:00",
                               "end": "11:00", "days": [self.week.isoformat(), (self.week + timedelta(days=1)).isoformat()]})
        self.assertEqual(WorkShift.objects.filter(name="Ca sáng").count(), 2)
        self.assertContains(self.client.get(url), "Ca sáng")
        self.client.post(url, {"action": "copy_prev", "tuan": (self.week + timedelta(days=7)).isoformat()})
        self.assertEqual(WorkShift.objects.filter(date__gte=self.week + timedelta(days=7)).count(), 4)
        self.client.login(username=self.waiter.username, password=PASSWORD)
        self.assertEqual(self.client.get(reverse("schedule:board")).status_code, 403)
        self.assertEqual(self.client.get(reverse("schedule:mine")).status_code, 200)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(reverse("schedule:register")).status_code, 403)  # Chủ quán không đăng ký ca
