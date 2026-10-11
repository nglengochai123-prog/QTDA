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

    def test_ac102_assigned_to_manager_then_escalated_and_timed(self):
        self.out_of_stock()
        self.sync()
        alert = Alert.objects.get(kind="da_het")
        self.assertEqual((alert.assignee, alert.level, alert.severity), (self.manager, 0, "khan"))
        self.assertIn(alert, alerts.visible_to(self.manager))
        self.assertNotIn(alert, alerts.visible_to(self.d["owner"]))  # Chủ quán chưa thấy khi chưa quá hạn
        self.sync(timezone.now() + timedelta(minutes=16))
        alert.refresh_from_db()
        self.assertEqual(alert.level, 1)
        self.assertIn(alert, alerts.visible_to(self.d["owner"]))
        report = alert.subject.split("-")[-1]
        ops.acknowledge(self.manager, int(report), "Đã mua thêm 2 hộp")
        self.sync()
        alert.refresh_from_db()
        self.assertEqual((alert.status, alert.auto_closed), ("da_dong", True))
        self.assertIsNotNone(alert.handling_minutes)

    def test_ac103_close_needs_note_and_owner_sees_only_own(self):
        shift_services.add_cash_entry(self.manager, key(), self.shift.pk, "dau_ca", 0)
        shift_services.close_shift(self.manager, self.shift.pk)
        later = self.shift.ends_at + timedelta(hours=2, minutes=1)
        self.sync(later)  # thiếu báo cáo cuối ca: giao Quản lý ca
        alert = Alert.objects.get(kind="du_lieu_tre")
        self.assertEqual(alert.assignee, self.manager)
        self.assertNotIn(alert, alerts.visible_to(self.d["owner"]))
        with self.assertRaises(ValidationError):
            alerts.close(self.manager, alert.pk, "")
        alerts.take(self.manager, alert.pk)
        alerts.close(self.manager, alert.pk, "Đã nhắc gửi báo cáo")
        alert.refresh_from_db()
        self.assertEqual(alert.status, "da_dong")
        self.sync(later)  # vẫn thiếu báo cáo nhưng đã đóng tay: không mở lại
        self.assertEqual(Alert.objects.filter(kind="du_lieu_tre").count(), 1)

    def test_one_open_alert_per_subject_and_owner_reminder(self):
        shift_services.add_cash_entry(self.manager, key(), self.shift.pk, "dau_ca", 500000)
        shift_services.close_shift(self.manager, self.shift.pk)
        shift_services.submit_report(self.manager, self.shift.pk, 400000, 0)
        self.sync()
        self.sync()
        alert = Alert.objects.get(kind="chenh_lech_tien")
        self.assertEqual(alert.assignee, self.manager)
        from apps.shifts.models import Discrepancy

        d = Discrepancy.objects.get()
        shift_services.explain(self.manager, d.pk, "Thối nhầm")
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
