"""Đính chính báo cáo cuối ca (GD-11), người duyệt dự phòng bắt buộc (GD-08), tách BO-01 khỏi ngưỡng."""

from datetime import timedelta

from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.control import services as control
from apps.core import params, periodic
from apps.orders import adjustments
from apps.orders.models import AdjustmentRequest
from apps.orders.tests.test_adjust_pay import Base, key
from apps.shifts import services as shift_services
from apps.shifts.models import Discrepancy, Shift, ShiftReportCorrection


class CorrectionTests(Base):
    def closed_with_report(self, counted):
        shift_services.add_cash_entry(self.manager, key(), self.shift.pk, "dau_ca", 500000)
        shift_services.close_shift(self.manager, self.shift.pk)
        return shift_services.submit_report(self.manager, self.shift.pk, counted, 0)

    def correct(self, counted, reason="Đếm sót một xấp 100.000"):
        result, _ = shift_services.request_correction(self.manager, key(), self.shift.pk, counted, 0, 0, reason)
        return ShiftReportCorrection.objects.get(pk=result["correction"])

    def test_correction_needs_reason_and_owner_then_re_reconciles_once(self):
        report = self.closed_with_report(400000)  # thiếu 100.000
        old = Discrepancy.objects.get()
        shift_services.explain(self.manager, old.pk, "Chưa rõ")
        with self.assertRaises(ValidationError):
            shift_services.request_correction(self.manager, key(), self.shift.pk, 480000, 0, 0, "")
        c = self.correct(480000)
        self.assertEqual(c.status, ShiftReportCorrection.Status.PENDING)
        with self.assertRaises(ValidationError):  # Quản lý ca không tự duyệt
            shift_services.decide_correction(self.manager, c.pk, True)
        shift_services.decide_correction(self.d["owner"], c.pk, True)
        shift_services.decide_correction(self.d["owner"], c.pk, True)  # bấm lại
        report.refresh_from_db()
        self.assertEqual(report.counted_cash, 400000)  # bản gốc giữ nguyên
        self.assertEqual(report.effective()["counted_cash"], 480000)
        current = Discrepancy.objects.current().get()
        self.assertEqual((current.difference, current.explanation), (-20000, ""))
        old.refresh_from_db()
        self.assertEqual((old.superseded_by, old.explanation), (c, "Chưa rõ"))  # lịch sử còn nguyên
        now = timezone.localtime()
        self.assertEqual(control.monthly_control(now.year, now.month)["in_process"], 20000)  # không cộng 100.000 cũ
        self.assertEqual(shift_services.accumulated_report(now.year, now.month)[0]["total"], 20000)
        with self.assertRaises(ValidationError):
            shift_services.explain(self.manager, old.pk, "Giải trình bản cũ")

    def test_correction_to_exact_removes_discrepancy_and_rejected_changes_nothing(self):
        self.closed_with_report(400000)
        rejected = self.correct(450000)
        shift_services.decide_correction(self.d["owner"], rejected.pk, False)
        self.assertEqual(Discrepancy.objects.current().get().difference, -100000)
        c = self.correct(500000)
        shift_services.decide_correction(self.d["owner"], c.pk, True)
        self.assertFalse(Discrepancy.objects.current().exists())
        self.assertEqual(Discrepancy.objects.count(), 1)

    def test_owner_request_is_self_approved_and_blocked_when_in_loss_case(self):
        self.closed_with_report(400000)
        case = control.open_case(self.d["owner"], "Thiếu tiền", operation_key=key())
        control.add_evidence(self.d["owner"], case, discrepancy=Discrepancy.objects.get())
        with self.assertRaises(ValidationError):
            shift_services.request_correction(self.d["owner"], key(), self.shift.pk, 480000, 0, 0, "Sao kê")
        self.assertFalse(ShiftReportCorrection.objects.exists())


class BackupApproverTests(Base):
    def test_shift_form_requires_backup(self):
        shift = Shift(store=self.d["store"], name="Ca tối", starts_at=timezone.now(),
                      ends_at=timezone.now() + timedelta(hours=4), approver=self.manager)
        with self.assertRaises(ValidationError):
            shift.full_clean()

    def test_missing_backup_reminded_once_and_direct_owner_logged(self):
        Shift.objects.filter(pk=self.shift.pk).update(backup_approver=None)
        self.assertEqual([s.pk for s in shift_services.shifts_missing_backup()], [self.shift.pk])
        periodic.run_all()
        periodic.run_all()
        self.assertEqual(AuditLog.objects.filter(reason=periodic.MISSING_BACKUP_REASON).count(), 1)
        order, line = self.order()
        req = self.request(self.d["waiter"], order, "huy_mon", line=line.pk, cups=1)
        periodic.run_all(req.level_since + timedelta(minutes=3, seconds=1))
        req.refresh_from_db()
        self.assertEqual(req.level, AdjustmentRequest.Level.OWNER)
        self.assertTrue(AuditLog.objects.filter(reason=adjustments.SKIP_BACKUP_REASON).exists())


class TargetSeparationTests(Base):
    def test_bo01_target_is_not_the_store_alert_threshold(self):
        params.set_value("accumulated_store_threshold", 500000, self.d["owner"])
        now = timezone.localtime()
        self.assertEqual(control.monthly_control(now.year, now.month)["target"], 200000)
        self.assertEqual(params.get("accumulated_store_threshold"), 500000)


class ScreenTests(Base):
    def test_screens_render_refund_and_correction(self):
        from django.urls import reverse

        from apps.orders.tests.helpers import PASSWORD

        CorrectionTests.closed_with_report(self, 400000)
        self.client.login(username=self.manager.username, password=PASSWORD)
        page = self.client.get(reverse("shifts:my_shift_detail", args=[self.shift.pk]))
        self.assertContains(page, "Đính chính báo cáo cuối ca")
        self.client.post(reverse("shifts:correction", args=[self.shift.pk]),
                         {"operation_key": key(), "counted_cash": "480.000", "transfer_received": "0",
                          "transfer_refunded": "0", "reason": "Đếm sót"})
        c = ShiftReportCorrection.objects.get()
        self.client.login(username=self.d["owner"].username, password=PASSWORD)
        self.assertContains(self.client.get(reverse("shifts:status")), "Duyệt và đối soát lại")
        self.client.post(reverse("shifts:decide_correction", args=[c.pk]), {"decision": "approve"})
        self.assertEqual(Discrepancy.objects.current().get().difference, -20000)
