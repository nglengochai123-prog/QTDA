"""Trung tâm cảnh báo (FR-51, BRU-36, AC-102, AC-103)."""

from datetime import timedelta
from unittest import mock

from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.control import alerts
from apps.control.models import Alert
from apps.inventory import operations as ops
from apps.orders.tests.test_adjust_pay import Base, key
from apps.shifts import services as shift_services


class AlertTests(Base):
    def out_of_stock(self):
        with mock.patch("apps.inventory.operations.in_opening_hours", return_value=True), \
                mock.patch("apps.control.alerts.timezone.now", wraps=timezone.now):
            ops.quick_report(self.d["barista"], key(), self.d["milk"].pk, "da_het")

    def sync(self, now=None):
        with mock.patch("apps.inventory.operations.in_opening_hours", return_value=True):
            return alerts.sync(now)

    def test_ac102_assigned_to_owner_and_timed(self):
        # Bỏ Quản lý ca (12/10/2026): báo Đã hết giao thẳng Chủ quán; quá hạn thì nhắc lại.
        self.out_of_stock()
        self.sync()
        alert = Alert.objects.get(kind="da_het")
        self.assertEqual((alert.assignee_role, alert.level, alert.severity), ("chu_quan", 0, "khan"))
        self.assertIn(alert, alerts.visible_to(self.d["owner"]))
        self.assertNotIn(alert, alerts.visible_to(self.cashier))
        self.sync(timezone.now() + timedelta(minutes=16))
        alert.refresh_from_db()
        self.assertEqual(alert.reminded_count, 1)
        report = alert.subject.split("-")[-1]
        ops.acknowledge(self.d["owner"], int(report), "Đã mua thêm 2 hộp")
        self.sync()
        alert.refresh_from_db()
        self.assertEqual((alert.status, alert.auto_closed), ("da_dong", True))
        self.assertIsNotNone(alert.handling_minutes)

    def test_ac103_close_needs_note(self):
        shift_services.add_cash_entry(self.cashier, key(), self.shift.pk, "dau_ca", 0)
        shift_services.close_shift(self.cashier, self.shift.pk)
        later = self.shift.ends_at + timedelta(hours=2, minutes=1)
        self.sync(later)  # thiếu báo cáo cuối ca: giao Chủ quán
        alert = Alert.objects.get(kind="du_lieu_tre")
        self.assertIn(alert, alerts.visible_to(self.d["owner"]))
        self.assertNotIn(alert, alerts.visible_to(self.d["barista"]))
        with self.assertRaises(ValidationError):
            alerts.close(self.d["owner"], alert.pk, "")
        alerts.take(self.d["owner"], alert.pk)
        alerts.close(self.d["owner"], alert.pk, "Đã nhắc gửi báo cáo")
        alert.refresh_from_db()
        self.assertEqual(alert.status, "da_dong")
        self.sync(later)  # vẫn thiếu báo cáo nhưng đã đóng tay: không mở lại
        self.assertEqual(Alert.objects.filter(kind="du_lieu_tre").count(), 1)

    def test_one_open_alert_per_subject_and_owner_reminder(self):
        shift_services.add_cash_entry(self.cashier, key(), self.shift.pk, "dau_ca", 500000)
        shift_services.close_shift(self.cashier, self.shift.pk)
        shift_services.submit_report(self.cashier, self.shift.pk, 400000, 0)
        self.sync()
        self.sync()
        alert = Alert.objects.get(kind="chenh_lech_tien")
        self.assertEqual(alert.assignee_role, "chu_quan")
        from apps.shifts.models import Discrepancy

        d = Discrepancy.objects.get()
        self.assertEqual(d.manager, self.cashier)  # người lập báo cáo chịu trách nhiệm khoản chênh lệch
        shift_services.explain(self.cashier, d.pk, "Thối nhầm")
        self.sync()
        alert.refresh_from_db()
        self.assertEqual((alert.assignee_role, alert.assignee), ("chu_quan", None))  # chuyển Chủ quán quyết định
        self.sync(timezone.now() + timedelta(days=4))
        alert.refresh_from_db()
        self.assertEqual((alert.level, alert.reminded_count), (0, 1))  # Chủ quán là người chính: nhắc lại
        shift_services.decide(self.d["owner"], d.pk, False)
        self.sync()
        alert.refresh_from_db()
        self.assertEqual(alert.status, "da_dong")
