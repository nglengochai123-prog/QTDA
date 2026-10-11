"""Lịch sử tham số có thời điểm hiệu lực, và kiểm tra quá hạn tách khỏi việc mở màn hình."""

from datetime import timedelta
from io import StringIO

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.core import params, periodic
from apps.core.models import ParameterValue
from apps.inventory import operations as ops
from apps.inventory.models import PurchaseOrder, Supplier
from apps.orders import adjustments, payments
from apps.orders.models import AdjustmentRequest
from apps.orders.tests.test_adjust_pay import Base, key
from apps.shifts import services as shift_services
from apps.shifts.models import Discrepancy

Level = AdjustmentRequest.Level


class ParameterHistoryTests(Base):
    def test_value_has_effective_time_and_history(self):
        owner = self.d["owner"]
        self.assertEqual(params.get("cash_threshold"), 50000)
        params.set_value("cash_threshold", "70.000", owner, reason="Quán đông hơn")
        later = timezone.now() + timedelta(days=1)
        params.set_value("cash_threshold", 90000, owner, effective_from=later)
        self.assertEqual(params.get("cash_threshold"), 70000)
        self.assertEqual(params.get("cash_threshold", at=later + timedelta(minutes=1)), 90000)
        self.assertEqual(params.get("cash_threshold", at=timezone.now() - timedelta(days=1)), 50000)
        self.assertEqual(ParameterValue.objects.filter(key="cash_threshold").count(), 2)
        with self.assertRaises(ValidationError):  # không lùi hiệu lực về quá khứ
            params.set_value("cash_threshold", 10000, owner, effective_from=timezone.now() - timedelta(hours=2))
        with self.assertRaises(ValidationError):
            params.set_value("cash_threshold", 10000, self.manager)
        with self.assertRaises(ValueError):  # lịch sử không sửa được
            row = ParameterValue.objects.first()
            row.value = 1
            row.save()

    def test_pending_request_keeps_deadline_from_creation(self):
        # Đổi thời hạn 3 → 5 phút khi đang có yêu cầu chờ: yêu cầu đó vẫn theo 3 phút; yêu cầu mới theo 5 phút.
        order, line = self.order()
        old = self.request(self.d["waiter"], order, "huy_mon", line=line.pk, cups=1)
        params.set_value("approval_level_minutes", 5, self.d["owner"])
        self.assertEqual(old.effective_level(old.level_since + timedelta(minutes=3, seconds=1)), Level.BACKUP)
        adjustments.decide(self.manager, key(), old.pk, False)
        new = self.request(self.d["waiter"], order, "huy_mon", line=line.pk, cups=1)
        self.assertEqual(new.level_minutes, 5)
        self.assertEqual(new.effective_level(new.level_since + timedelta(minutes=3, seconds=1)), Level.SHIFT)
        self.assertEqual(new.effective_level(new.level_since + timedelta(minutes=5, seconds=1)), Level.BACKUP)

    def test_threshold_change_after_close_does_not_change_shift_result(self):
        shift_services.add_cash_entry(self.manager, key(), self.shift.pk, "dau_ca", 500000)
        shift_services.close_shift(self.manager, self.shift.pk)
        params.set_value("cash_threshold", 10000, self.d["owner"])  # đổi sau khi ca đã kết
        shift_services.submit_report(self.manager, self.shift.pk, 480000, 0)  # thiếu 20.000
        d = Discrepancy.objects.get()
        self.assertEqual((d.difference, d.threshold, d.over_threshold), (-20000, 50000, False))


class OverdueSeparationTests(Base):
    def test_level_is_correct_on_read_without_periodic_task(self):
        order, line = self.order()
        req = self.request(self.d["waiter"], order, "huy_mon", line=line.pk, cups=1)
        t = req.level_since + timedelta(minutes=3, seconds=1)
        self.assertTrue(adjustments.can_decide(self.backup, req, now=t))
        req.refresh_from_db()
        self.assertEqual(req.level, Level.SHIFT)  # đọc không ghi gì
        self.assertFalse(AuditLog.objects.filter(reason__startswith="Chuyển cấp").exists())
        # Tác vụ định kỳ ghi lại chuyển cấp và nhật ký; chạy lại không ghi thêm.
        periodic.run_all(req.level_since + timedelta(minutes=6, seconds=1))
        periodic.run_all(req.level_since + timedelta(minutes=6, seconds=1))
        req.refresh_from_db()
        self.assertEqual(req.level, Level.OWNER)
        self.assertEqual(AuditLog.objects.filter(reason__startswith="Chuyển cấp").count(), 2)

    def test_exhausted_request_detected_on_bill_without_periodic_task(self):
        order, line = self.order()
        self.finish(line)
        req = self.request(self.d["waiter"], order, "huy_mon", line=line.pk, cups=1)
        AdjustmentRequest.objects.filter(pk=req.pk).update(level_since=timezone.now() - timedelta(minutes=10))
        self.assertEqual(len(payments.bill(order.table)["exhausted"]), 1)

    def test_late_purchase_order_on_read_and_command(self):
        supplier = Supplier.objects.create(store=self.d["store"], name="NCC")
        po = ops.create_purchase_order(self.d["owner"], supplier.pk, self.d["milk"].pk, 1000,
                                       timezone.localdate() - timedelta(days=1), operation_key=key())
        self.assertEqual(po.status, PurchaseOrder.Status.ORDERED)
        self.assertEqual(po.current_status, PurchaseOrder.Status.LATE)
        self.assertFalse(po.counts_as_incoming)
        out = StringIO()
        call_command("chay_dinh_ky", stdout=out)
        po.refresh_from_db()
        self.assertEqual(po.status, PurchaseOrder.Status.LATE)
        self.assertIn("1 lần đặt giao chậm", out.getvalue())
