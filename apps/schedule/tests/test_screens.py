"""Màn Lịch làm tuần, Đăng ký ca, Lịch của tôi sau khi làm lại giao diện (FR-38, FR-39)."""

from datetime import time, timedelta
from unittest import mock

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import Role, User
from apps.core.models import Store
from apps.schedule import board, pages
from apps.schedule import services as sv
from apps.schedule.models import Assignment, RoleNeed, WeekPublish, WorkShift
from apps.staff.models import Employee

PASSWORD = "matkhau-thu-123"


class ScreenTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("chuquan", password=PASSWORD, role=Role.CHU_QUAN)

        def emp(name, phone, roles):
            e = Employee.create_with_account(full_name=name, phone=phone, roles=roles)
            e.user.set_password(PASSWORD)
            e.user.save()
            return e.user

        self.barista = emp("Trần Bình", "0900000002", [Role.PHA_CHE])
        self.both = emp("Lê Cường", "0900000003", [Role.PHA_CHE, Role.PHUC_VU])
        self.week = sv.next_week()
        store = Store.get_default()
        self.shifts = []
        for k in range(3):
            day = self.week + timedelta(days=k)
            self.shifts.append(WorkShift.objects.create(store=store, date=day, name="Ca sáng", start=time(6, 30), end=time(14, 30)))
            WorkShift.objects.create(store=store, date=day, name="Ca chiều", start=time(14), end=time(22))
        for s in WorkShift.objects.all():
            RoleNeed.objects.create(shift=s, role=Role.PHA_CHE, needed=2, suggested=2)
        self.url = reverse("schedule:board") + f"?tuan={self.week.isoformat()}"

    def post(self, **data):
        self.client.force_login(self.owner)
        return self.client.post(self.url, {"tuan": self.week.isoformat(), **data})

    def need(self, shift, role=Role.PHA_CHE):
        return RoleNeed.objects.get(shift=shift, role=role).needed

    def test_set_needs_from_dialog_requires_reason_when_off_suggestion(self):
        s = self.shifts[0]
        page = self.post(action="set_needs", shift=s.pk, need_pha_che="3", need_phuc_vu="0", need_thu_ngan="0",
                         reason="")
        self.assertEqual(self.need(s), 2)  # khác gợi ý mà không có lý do: không lưu
        self.assertIn(f"mo={s.pk}", page["Location"])  # mở lại hộp của ca đó để sửa
        self.post(action="set_needs", shift=s.pk, need_pha_che="3", need_phuc_vu="1", need_thu_ngan="0",
                  reason="Có sự kiện")
        self.assertEqual((self.need(s), self.need(s, Role.PHUC_VU)), (3, 1))
        self.assertEqual(RoleNeed.objects.get(shift=s, role=Role.PHA_CHE).reason, "Có sự kiện")
        self.assertFalse(RoleNeed.objects.filter(shift=s, role=Role.THU_NGAN).exists())  # 0 thì không tạo dòng

    def test_set_needs_same_name_whole_week_and_all_or_nothing(self):
        self.post(action="set_needs", shift=self.shifts[0].pk, need_pha_che="2", need_phuc_vu="1", need_thu_ngan="1",
                  same_name="1")
        self.assertEqual([self.need(s, Role.PHUC_VU) for s in self.shifts], [1, 1, 1])
        self.assertFalse(RoleNeed.objects.filter(shift__name="Ca chiều", role=Role.PHUC_VU).exists())
        with self.assertRaises(ValidationError):
            sv.set_needs(self.owner, self.shifts, {Role.PHA_CHE: 4})  # cả ba ca khác gợi ý, không lý do
        self.assertEqual([self.need(s) for s in self.shifts], [2, 2, 2])  # không ca nào bị ghi dở

    def test_board_renders_grid_dialogs_and_people_tab(self):
        Assignment.objects.create(shift=self.shifts[0], user=self.barista, role=Role.PHA_CHE, source="chu_quan",
                                  assigned_by=self.owner)
        self.client.force_login(self.owner)
        page = self.client.get(self.url)
        self.assertContains(page, f'id="ca-{self.shifts[0].pk}"')
        self.assertContains(page, 'name="need_pha_che"')
        self.assertContains(page, "Bình")
        ctx = board.build(self.week)
        self.assertEqual(len(ctx["grid"]), 2)  # Ca sáng, Ca chiều
        self.assertEqual(ctx["short"], 11)  # 6 ca × 2 pha chế, đã xếp 1
        self.assertEqual([s["key"] for s in ctx["steps"] if s["done"]], ["ca", "can"])
        people = self.client.get(self.url + "&xem=nguoi")
        self.assertContains(people, "Trần Bình")
        self.assertContains(people, "Giờ xếp")

    def test_publish_requires_confirm_and_marks_changes(self):
        self.post(action="publish")
        self.assertFalse(WeekPublish.objects.exists())
        self.post(action="publish", confirm="1")
        self.assertTrue(WeekPublish.objects.exists())
        self.assertFalse(board.build(self.week)["changed"])
        sv.assign(self.owner, self.shifts[1], self.barista, Role.PHA_CHE)
        self.assertTrue(board.build(self.week)["changed"])

    def test_add_shift_with_days_and_needs(self):
        days = [(self.week + timedelta(days=k)).isoformat() for k in (5, 6)]
        self.post(action="add_shift", name="Ca tối", start="18:00", end="22:30", days=days, need_pha_che="1",
                  need_phuc_vu="", need_thu_ngan="")
        made = WorkShift.objects.filter(name="Ca tối")
        self.assertEqual(made.count(), 2)
        self.assertEqual({self.need(s) for s in made}, {1})
        self.post(action="add_shift", name="Ca tối", start="18:00", end="17:00", days=days)
        self.assertEqual(made.count(), 2)  # giờ kết thúc trước giờ bắt đầu: không thêm

    def test_register_page_quick_pick_data_and_overlap(self):
        ctx = pages.register_page(self.both, self.week, now=sv.deadline_for(self.week) - timedelta(days=1))
        self.assertTrue(ctx["open"])
        self.assertEqual(ctx["quick"], ["Ca sáng", "Ca chiều"])
        first = ctx["days"][0]["items"][0]
        self.assertEqual(first["best"], Role.PHA_CHE)  # vị trí đang thiếu
        self.assertEqual(first["overlap"], ["Ca chiều"])  # 06:30–14:30 và 14:00–22:00 chồng nhau
        self.assertEqual([o["role"] for o in first["options"]], [Role.PHA_CHE, Role.PHUC_VU])
        self.client.force_login(self.both)
        page = self.client.get(reverse("schedule:register"), {"tuan": self.week.isoformat()})
        self.assertEqual(page.status_code, 200)

    def test_register_closed_view_lists_own_registrations(self):
        sv.register(self.barista, {self.shifts[0].pk: Role.PHA_CHE}, now=sv.deadline_for(self.week) - timedelta(hours=1))
        ctx = pages.register_page(self.barista, self.week, now=sv.deadline_for(self.week) + timedelta(hours=1))
        self.assertFalse(ctx["open"])
        self.assertEqual((ctx["chosen"], ctx["hours"]), (1, 8.0))

    def test_my_page_next_shift_and_week_hours(self):
        sv.assign(self.owner, self.shifts[0], self.barista, Role.PHA_CHE)
        sv.assign(self.owner, self.shifts[2], self.barista, Role.PHA_CHE)
        self.assertEqual(pages.my_page(self.barista)["weeks"], [])  # chưa công bố thì chưa thấy
        WeekPublish.objects.create(week_start=self.week, published_by=self.owner)
        ctx = pages.my_page(self.barista)
        self.assertEqual(ctx["upcoming"]["shift"], self.shifts[0])
        self.assertEqual(ctx["weeks"][0]["hours"], 16.0)
        self.assertTrue(ctx["next_published"])
        self.client.force_login(self.barista)
        self.assertContains(self.client.get(reverse("schedule:mine")), "Ca tiếp theo")

    def test_register_skips_shift_deleted_while_page_open(self):
        before = sv.deadline_for(self.week) - timedelta(hours=1)
        gone = WorkShift.objects.create(store=Store.get_default(), date=self.week, name="Ca tối", start=time(18),
                                        end=time(22))
        gone_id = gone.pk
        gone.delete()
        changed = sv.register(self.barista, {self.shifts[0].pk: Role.PHA_CHE, gone_id: Role.PHA_CHE}, now=before)
        self.assertEqual(len(changed), 1)
        with self.assertRaises(ValidationError):
            sv.register(self.barista, {gone_id: Role.PHA_CHE}, now=before)
        self.client.force_login(self.barista)
        with mock.patch("apps.schedule.services.deadline_for", return_value=before + timedelta(days=30)):
            page = self.client.post(reverse("schedule:register"), {"tuan": self.week.isoformat(),
                                                                   f"ca_{self.shifts[1].pk}": Role.PHA_CHE,
                                                                   f"ca_{gone_id}": Role.PHA_CHE}, follow=True)
        self.assertContains(page, "1 ca vừa bị Chủ quán xóa")

    def test_add_shift_without_time_shows_message(self):
        page = self.post(action="add_shift", name="Ca tối", start="", end="22:00", days=[self.week.isoformat()])
        self.assertEqual(page.status_code, 302)
        page = self.client.get(page["Location"])
        self.assertContains(page, "Nhập giờ bắt đầu và giờ kết thúc của ca")
        self.assertFalse(WorkShift.objects.filter(name="Ca tối").exists())

    def test_employee_leaving_is_removed_from_upcoming_shifts(self):
        sv.assign(self.owner, self.shifts[0], self.both, Role.PHUC_VU)
        sv.assign(self.owner, self.shifts[1], self.both, Role.PHA_CHE)
        sv.register(self.both, {self.shifts[2].pk: Role.PHA_CHE}, now=sv.deadline_for(self.week) - timedelta(hours=1))
        emp = Employee.objects.get(user=self.both)
        url = reverse("masterdata:edit", kwargs={"key": "nhan-vien", "pk": emp.pk})
        self.client.force_login(self.owner)
        data = {"full_name": emp.full_name, "phone": emp.phone, "roles": [Role.PHA_CHE], "hourly_wage": "25000",
                "status": "dang_lam"}
        page = self.client.post(url, data, follow=True)  # bớt vai trò Phục vụ: chỉ bỏ lượt Phục vụ
        self.assertContains(page, "ra khỏi 1 lượt ca từ hôm nay")
        self.assertEqual(list(Assignment.objects.filter(user=self.both, removed_at__isnull=True)
                              .values_list("role", flat=True)), [Role.PHA_CHE])
        page = self.client.post(url, {**data, "status": "nghi_viec"}, follow=True)
        self.assertContains(page, "nghỉ việc")
        self.assertFalse(Assignment.objects.filter(user=self.both, removed_at__isnull=True).exists())
        self.assertEqual(Assignment.objects.filter(user=self.both).last().remove_reason, "Nghỉ việc")
        self.assertFalse(self.both.__class__.objects.get(pk=self.both.pk).is_active)
        from apps.schedule.models import Registration

        self.assertFalse(Registration.objects.filter(user=self.both, cancelled_at__isnull=True).exists())

    def test_changes_after_publish_are_sent_to_the_person(self):
        with mock.patch("apps.core.push.notify_later") as notify:
            sv.assign(self.owner, self.shifts[0], self.barista, Role.PHA_CHE)
            notify.assert_not_called()  # chưa công bố: không báo
            WeekPublish.objects.create(week_start=self.week, published_by=self.owner)
            a = sv.assign(self.owner, self.shifts[1], self.barista, Role.PHA_CHE)
            sv.unassign(self.owner, a, "Đổi người")
        bodies = [c.args[2] for c in notify.call_args_list]
        self.assertEqual(len(bodies), 2)
        self.assertTrue(bodies[0].startswith("Thêm ca") and bodies[1].startswith("Bỏ ca"))
        self.assertEqual(notify.call_args_list[0].args[0], [self.barista.pk])
