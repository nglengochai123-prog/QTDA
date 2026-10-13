"""Đề nghị kiểm kê lại (AC-03, Bảng 5.4) và kiểm kê nhóm trọng yếu trước giờ mở cửa hôm sau (BRU-07, FR-09)."""

import json
from datetime import timedelta

from django.urls import reverse
from django.utils import timezone

from apps.control import alerts
from apps.control.models import Alert
from apps.inventory import operations as ops
from apps.inventory.models import RecountRequest
from apps.orders.tests.helpers import PASSWORD
from apps.orders.tests.test_adjust_pay import Base, key
from apps.shifts import services as shift_services


class RecountTests(Base):
    def test_recount_request_alert_assigned_to_barista_and_closed_by_count(self):
        self.client.login(username=self.d["waiter"].username, password=PASSWORD)
        body = {"operation_key": key(), "ingredients": [self.d["milk"].pk]}
        for _ in range(2):
            r = self.client.post(reverse("orders:recount"), json.dumps(body), content_type="application/json")
            self.assertTrue(r.json()["ok"])
        self.assertEqual(RecountRequest.objects.count(), 1)
        alerts.sync()
        alert = Alert.objects.get(kind="kiem_ke_lai")
        self.assertIn(alert, alerts.visible_to(self.d["barista"]))
        self.assertNotIn(alert, alerts.visible_to(self.d["owner"]))
        alerts.sync(self.shift.ends_at + timedelta(minutes=1))  # quá hạn trước khi kết ca: chuyển Quản lý ca
        alert.refresh_from_db()
        self.assertEqual((alert.assignee_role, alert.assignee), ("chu_quan", None))  # quá hạn chuyển Chủ quán
        ops.submit_count(self.d["barista"], key(), self.d["milk"].pk, "1000")
        self.assertIsNotNone(RecountRequest.objects.get().done_at)
        alerts.sync()
        alert.refresh_from_db()
        self.assertEqual(alert.status, "da_dong")

    def test_critical_count_required_before_next_opening(self):
        self.d["milk"].is_critical = True
        self.d["milk"].save()
        day = timezone.localdate()
        status = shift_services.critical_count_status(day, now=timezone.now())
        self.assertEqual(status["missing"], ["Sữa đặc"])
        late = shift_services.critical_count_status(day, now=status["deadline"] + timedelta(minutes=1))
        self.assertTrue(late["late"])
        data = shift_services.data_status(self.shift, now=status["deadline"] + timedelta(minutes=1))
        self.assertTrue(any("kiểm kê nhóm trọng yếu" in i for i in data["issues"]))
        ops.submit_count(self.d["barista"], key(), self.d["milk"].pk, "1000")
        self.assertFalse(shift_services.critical_count_status(day, now=status["deadline"] + timedelta(minutes=1))["late"])
