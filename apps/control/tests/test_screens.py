from django.test import TestCase
from django.urls import reverse

from apps.control import services as control
from apps.control.models import ExceptionCase
from apps.orders.tests.test_adjust_pay import Base, key
from apps.shifts import services as shift_services


class ScreenTests(Base):
    def test_manager_shift_flow_screens(self):
        self.client.force_login(self.manager)
        page = self.client.get(reverse("shifts:my_shift"))
        self.assertContains(page, "Xác nhận tiền đầu ca")
        self.client.post(reverse("shifts:cash_entry", args=[self.shift.pk]),
                         {"operation_key": key(), "kind": "dau_ca", "amount": "500.000"})
        self.assertEqual(shift_services.figures(self.shift)["opening"], 500000)
        self.client.post(reverse("shifts:close", args=[self.shift.pk]))
        self.shift.refresh_from_db()
        self.assertEqual(self.shift.status, "da_ket")
        self.client.post(reverse("shifts:report", args=[self.shift.pk]),
                         {"counted_cash": "430000", "transfer_received": "0", "incidents": "Máy xay kêu"})
        page = self.client.get(reverse("shifts:my_shift_detail", args=[self.shift.pk]))
        self.assertContains(page, "vượt ngưỡng")
        self.assertContains(page, "Gửi giải trình")

    def test_owner_screens_and_permissions(self):
        exc = control.open_exception(ExceptionCase.Kind.PAID_CANCELLED, rule="thử", employee=self.cashier,
                                     shift=self.shift, amount=120000, one_per_scope=False)
        self.client.force_login(self.d["owner"])
        for name in ("shifts:status", "control:exceptions", "control:cases", "control:parameters"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)
        self.assertContains(self.client.get(reverse("control:exception_detail", args=[exc.pk])), "Kết luận")
        self.client.post(reverse("control:parameters"), {"key": "cash_threshold", "value": "70.000"})
        from apps.core import params
        self.assertEqual(params.get("cash_threshold"), 70000)
        self.assertEqual(self.client.get(reverse("control:adjustment_report", args=[self.shift.pk])).status_code, 200)
        self.client.force_login(self.cashier)
        self.assertEqual(self.client.get(reverse("control:exceptions")).status_code, 403)
        self.assertEqual(self.client.get(reverse("control:parameters")).status_code, 403)
        self.assertEqual(self.client.get(reverse("shifts:status")).status_code, 403)
        self.client.force_login(self.d["waiter"])
        self.assertEqual(self.client.get(reverse("shifts:my_shift")).status_code, 403)


class ControlScreenReworkTests(TestCase):
    """Ngoại lệ, cảnh báo, vụ việc sau khi làm lại: không lộ mã yêu cầu nội bộ, xem lần lượt, chặn thu hồi sai."""

    def setUp(self):
        from apps.orders.tests.helpers import build_menu

        self.d = build_menu()
        self.owner = self.d["owner"]
        self.client.force_login(self.owner)

    def exc(self, **kw):
        from apps.control.models import ExceptionCase

        base = {"store": self.d["store"], "kind": ExceptionCase.Kind.PAID_CANCELLED,
                "rule": "Hóa đơn đã thanh toán bị hủy (BRU-12)", "detail": "vượt 2 gram (8.33%)", "amount": 34000}
        return ExceptionCase.objects.create(**{**base, **kw})

    def test_exception_pages_hide_codes_and_walk_through(self):
        older, newer = self.exc(), self.exc(employee=self.d["barista"])
        page = self.client.get(reverse("control:exceptions"))
        self.assertNotContains(page, "BRU-")
        self.assertEqual(page.context["pending"], 2)
        detail = self.client.get(reverse("control:exception_detail", args=[newer.pk]))
        self.assertNotContains(detail, "BRU-")
        self.assertContains(detail, "8,33%")
        self.assertEqual(detail.context["next"], older)
        res = self.client.post(reverse("control:exception_detail", args=[newer.pk]),
                               {"result": "hop_le", "measure": "Khách đổi ý", "sau": "tiep"})
        self.assertRedirects(res, reverse("control:exception_detail", args=[older.pk]))

    def test_alert_page_groups_by_kind(self):
        from apps.control import alerts

        for _ in range(7):
            self.exc()
        alerts.sync()
        page = self.client.get(reverse("control:alerts"))
        group = page.context["groups"][0]
        self.assertEqual((len(group["first"]), len(group["rest"])), (5, 2))
        self.assertNotContains(page, "BRU-")

    def test_recovery_needs_verification_and_cannot_exceed_it(self):
        import uuid

        from django.core.exceptions import ValidationError

        from apps.control import services as control

        case = control.open_case(self.owner, "VV", operation_key=uuid.uuid4().hex)
        control.add_evidence(self.owner, case, exception=self.exc())
        with self.assertRaises(ValidationError):
            control.recover(self.owner, case, 10000, operation_key=uuid.uuid4().hex)  # chưa xác minh
        url = reverse("control:case_detail", args=[case.pk])
        self.client.post(url, {"action": "verify", "amount": "34.000"})
        self.assertEqual(case.verified_amount(), 34000)
        self.client.post(url, {"action": "recover", "amount": "40.000", "operation_key": uuid.uuid4().hex})
        self.assertEqual(case.recovered_amount(), 0)  # vượt phần còn lại
        self.client.post(url, {"action": "recover", "amount": "-5000", "operation_key": uuid.uuid4().hex})
        self.assertEqual(case.recovered_amount(), 0)
        self.client.post(url, {"action": "recover", "amount": "34.000", "operation_key": uuid.uuid4().hex})
        self.assertEqual(case.remaining_amount(), 0)
