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
        self.assertContains(self.client.get(reverse("control:exception_detail", args=[exc.pk])), "Ghi kết quả")
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
