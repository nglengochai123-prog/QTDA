import uuid
from datetime import datetime, time, timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.catalog.models import Table
from apps.orders import adjustments, services
from apps.orders.models import AdjustmentReason
from apps.orders.overview import shift_overview
from apps.shifts.models import Shift
from apps.staff.models import Attendance

from .helpers import PASSWORD, build_menu, cart


def key():
    return uuid.uuid4().hex


class ShiftOverviewTests(TestCase):
    def setUp(self):
        self.d = build_menu()
        self.cashier = User.objects.create_user("thungan", password=PASSWORD, role=Role.THU_NGAN)
        now = timezone.now()
        self.shift = Shift.objects.create(store=self.d["store"], name="Ca chiều", starts_at=now - timedelta(hours=1),
                                          ends_at=now + timedelta(hours=4), approver=self.d["owner"])
        self.tables = {code: Table.objects.create(store=self.d["store"], code=code, area="Sân vườn")
                       for code in ("6", "7", "8", "9")}

    def order(self, table, quantity=1):
        payload = cart(self.d, quantity=quantity)
        payload["table"] = table.pk
        result, _ = services.submit_order(self.d["waiter"], key(), payload)
        return result["order_id"]

    def lines(self, order_id):
        from apps.orders.models import OrderLine

        return list(OrderLine.objects.filter(order_id=order_id))

    def build_floor(self):
        """Bàn 5 chờ pha 2 ly, bàn 6 pha xong chờ mang ra, bàn 7 đã phục vụ chờ thu, bàn 8 có yêu cầu chờ duyệt."""
        self.order(self.d["table"], quantity=2)
        ready = self.order(self.tables["6"])
        for line in self.lines(ready):
            services.complete_line(self.d["barista"], key(), line.pk, 1, 0)
        served = self.order(self.tables["7"])
        for line in self.lines(served):
            services.complete_line(self.d["barista"], key(), line.pk, 1, 0)
            services.serve_line(self.d["waiter"], key(), line.pk)
        pending = self.order(self.tables["8"])
        adjustments.create_request(self.d["waiter"], key(), {
            "order": pending, "kind": "huy_mon", "line": self.lines(pending)[0].pk, "cups": 1,
            "reason": AdjustmentReason.objects.get(name="Khách đổi ý").pk})

    def test_tables_queue_and_approvals(self):
        self.build_floor()
        view = shift_overview(self.d["owner"])
        states = {t["table"].code: t["state"] for t in view["tables"]}
        self.assertEqual(states, {"5": "pha", "6": "mang_ra", "7": "thanh_toan", "8": "duyet", "9": ""})
        self.assertEqual((view["tables_busy"], view["tables_free"]), (4, 1))
        self.assertEqual(view["bar"]["cups"], 3)  # 2 ly bàn 5 và 1 ly bàn 8 chưa pha
        self.assertEqual((view["ready"]["cups"], view["ready"]["tables"]), (1, ["6"]))
        self.assertEqual(view["to_pay"], {"tables": 1, "amount": 25000})
        self.assertEqual(len(view["approvals"]), 1)
        self.assertTrue(view["approvals"][0]["mine"])
        self.assertFalse(shift_overview(self.d["waiter"])["approvals"][0]["mine"])
        self.assertEqual(view["sales"]["orders"], 4)

    def test_slow_table_flagged_after_wait_standard(self):
        self.order(self.d["table"])
        later = shift_overview(self.d["owner"], now=timezone.now() + timedelta(minutes=25))
        self.assertEqual([t["table"].code for t in later["slow_tables"]], ["5"])
        self.assertEqual(shift_overview(self.d["owner"])["slow_tables"], [])

    def test_money_only_for_cash_roles(self):
        self.assertIsNotNone(shift_overview(self.d["owner"])["money"])
        self.assertIsNotNone(shift_overview(self.cashier)["money"])
        self.assertIsNone(shift_overview(self.d["waiter"])["money"])

    def test_people_on_shift_and_scheduled_but_absent(self):
        from apps.schedule.models import Assignment, WeekPublish, WorkShift
        from apps.schedule.services import week_start

        noon = timezone.make_aware(datetime.combine(timezone.localdate(), time(12, 0)))
        Attendance.objects.create(store=self.d["store"], user=self.cashier, role=Role.THU_NGAN,
                                  clock_in=noon - timedelta(hours=2))
        work = WorkShift.objects.create(store=self.d["store"], date=noon.date(), name="Ca sáng", start=time(8),
                                        end=time(14))
        Assignment.objects.create(shift=work, user=self.d["barista"], role=Role.PHA_CHE, source="chu_quan",
                                  assigned_by=self.d["owner"])
        WeekPublish.objects.create(week_start=week_start(noon.date()), published_by=self.d["owner"])
        people = {str(p["user"]): p["absent"] for p in shift_overview(self.d["owner"], now=noon)["people"]}
        self.assertEqual(people, {str(self.cashier): False, str(self.d["barista"]): True})

    def test_page_partial_and_permission(self):
        self.build_floor()
        url = reverse("orders:overview")
        self.client.login(username="phucvu", password=PASSWORD)
        page = self.client.get(url)
        self.assertContains(page, "Tổng quan ca")
        self.assertContains(page, "Bàn 8")
        self.assertNotContains(page, "Doanh thu ca")  # phục vụ không xem tiền ca
        part = self.client.get(url, {"phan": "1"})
        self.assertContains(part, "Chờ mang ra")
        self.assertNotContains(part, "<html")
        self.client.login(username="chuquan", password=PASSWORD)
        self.assertContains(self.client.get(url), "Doanh thu ca")
        self.client.login(username="phache", password=PASSWORD)
        self.assertEqual(self.client.get(url).status_code, 403)


class BusyFloorCommandTests(TestCase):
    def test_command_fills_free_tables_through_business_functions(self):
        from io import StringIO
        from unittest import mock

        from django.core.management import call_command

        from apps.core.management.commands.tao_du_lieu_nghiem_thu import Clock

        with mock.patch("django.utils.timezone.now", Clock(timezone.now() - timedelta(hours=3))):
            call_command("tao_du_lieu_mau", stdout=StringIO())
        call_command("tao_ban_co_khach", stdout=StringIO())
        owner = User.objects.get(username="demo_chuquan")
        view = shift_overview(owner)
        self.assertEqual(view["tables_busy"], 6)
        self.assertEqual({label: n for label, _, n in view["states"]},
                         {"Chờ duyệt": 1, "Có món chờ mang ra": 1, "Đang pha": 2, "Chờ thanh toán": 2})
        self.assertEqual(len(view["slow_tables"]), 1)  # bàn gọi 22 phút trước vẫn chưa có món
        call_command("kiem_tra_toan_ven", stdout=(out := StringIO()))
        self.assertIn("Không phát hiện sai lệch", out.getvalue())


class LargeIdRenderTests(TestCase):
    def test_ids_above_a_thousand_have_no_thousand_separator(self):
        from apps.orders.models import OrderLine

        d = build_menu()
        services.submit_order(d["waiter"], key(), cart(d))
        OrderLine.objects.update(id=5243)
        self.client.login(username="phache", password=PASSWORD)
        html = self.client.get(reverse("orders:bar_queue")).content.decode()
        self.assertIn('data-line="5243"', html)
        self.assertNotIn("5.243", html)
