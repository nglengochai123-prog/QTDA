from datetime import timedelta

from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.control import reports
from apps.control import services as control
from apps.control.models import ExceptionCase, ExceptionReview
from apps.orders import adjustments, payments, services
from apps.orders.models import Order
from apps.orders.tests.test_adjust_pay import Base, key
from apps.shifts import services as shift_services
from apps.shifts.models import Discrepancy, Refund


class ExceptionRuleTests(Base):
    def test_rejected_after_prep_creates_exception(self):
        # AC-30
        order, line = self.order()
        services.complete_line(self.d["barista"], key(), line.pk, 1, 0)
        req = self.request(self.d["waiter"], order, "chuyen_ban", target_table=self.other_table.pk)
        adjustments.decide(self.manager, key(), req.pk, False, "Không hợp lý")
        exc = ExceptionCase.objects.get(kind="dc_bi_tu_choi")
        self.assertEqual((exc.employee, exc.order, exc.shift), (self.d["waiter"], order, self.shift))
        self.assertIn("BRU-12", exc.rule)

    def test_rejected_before_prep_no_exception(self):
        order, line = self.order()
        req = self.request(self.d["waiter"], order, "chuyen_ban", target_table=self.other_table.pk)
        adjustments.decide(self.manager, key(), req.pk, False)
        self.assertFalse(ExceptionCase.objects.exists())

    def test_count_limit_one_open_exception(self):
        # AC-31: mức 3; yêu cầu thứ 4 mở ngoại lệ, thứ 5 gắn vào ngoại lệ đó.
        for i in range(5):
            order, line = self.order()
            services.complete_line(self.d["barista"], key(), line.pk, 1, 0)
            req = self.request(self.d["waiter"], order, "huy_mon", line=line.pk, cups=1)
            if i < 4:
                adjustments.decide(self.manager, key(), req.pk, True)
            if i < 3:
                self.assertFalse(ExceptionCase.objects.filter(kind="nhieu_dieu_chinh").exists())
        exc = ExceptionCase.objects.get(kind="nhieu_dieu_chinh")
        self.assertEqual(exc.requests.count(), 2)

    def test_paid_cancel_records_refund_and_exception(self):
        order, line = self.order()
        self.finish(line)
        payments.pay_table(self.cashier, key(), order.table_id, "tien_mat")
        req = self.request(self.cashier, Order.objects.get(pk=order.pk), "huy_hoa_don")
        adjustments.decide(self.d["owner"], key(), req.pk, True)
        refund = Refund.objects.get()
        self.assertEqual((refund.method, refund.amount, refund.shift), ("tien_mat", 25000, self.shift))
        self.assertTrue(ExceptionCase.objects.filter(kind="huy_sau_tt", amount=25000).exists())

    def test_adjustment_report_separates_groups(self):
        # AC-29
        o1, l1 = self.order()
        services.complete_line(self.d["barista"], key(), l1.pk, 1, 0)
        r1 = self.request(self.d["waiter"], o1, "huy_mon", line=l1.pk, cups=1)
        adjustments.decide(self.manager, key(), r1.pk, True)
        o2, l2 = self.order()
        r2 = self.request(self.d["waiter"], o2, "chuyen_ban", target_table=self.other_table.pk)
        adjustments.decide(self.manager, key(), r2.pk, False)
        report = reports.adjustment_report(self.shift)
        self.assertEqual(report["total"], 2)
        self.assertEqual(len(report["rejected"]), 1)
        self.assertEqual(report["post_prep_value"], 25000)


class ReviewAndLossTests(Base):
    def make_exception(self, amount=120000, order=None):
        return control.open_exception(ExceptionCase.Kind.PAID_CANCELLED, rule="thử", employee=self.cashier,
                                      shift=self.shift, amount=amount, order=order, one_per_scope=False)

    def test_only_owner_reviews_and_loss_needs_case(self):
        # AC-35, AC-36
        exc = self.make_exception()
        with self.assertRaises(ValidationError):
            control.review(self.manager, exc.pk, "vi_pham", money_loss=True)
        with self.assertRaises(ValidationError):
            control.review(self.d["owner"], exc.pk, "vi_pham", money_loss=True)
        case = control.open_case(self.d["owner"], "Hủy hóa đơn bàn 5", operation_key=key())
        control.add_evidence(self.d["owner"], case, exception=exc)
        review = control.review(self.d["owner"], exc.pk, "vi_pham", money_loss=True, measure="Trừ lương")
        exc.refresh_from_db()
        self.assertEqual(exc.status, ExceptionCase.Status.CLOSED)
        review.measure = "sửa"
        with self.assertRaises(ValidationError):
            review.save()
        with self.assertRaises(ValidationError):
            control.review(self.d["owner"], exc.pk, "hop_le")  # đổi kết quả phải có đính chính
        new = control.review(self.d["owner"], exc.pk, "nhac_nho", correction_reason="Có camera mới")
        review.refresh_from_db()
        self.assertEqual(review.superseded_by, new)
        self.assertEqual(exc.effective_review(), new)

    def test_reminder_after_days(self):
        exc = self.make_exception()
        self.assertNotIn(exc, control.reminders_due())
        self.assertIn(exc, control.reminders_due(timezone.now() + timedelta(days=3, minutes=1)))

    def test_no_money_loss_review_closes(self):
        # AC-37
        exc = self.make_exception(amount=0)
        control.review(self.d["owner"], exc.pk, "nhac_nho", money_loss=False)
        self.assertEqual(ExceptionReview.objects.count(), 1)
        now = timezone.localtime()
        self.assertEqual(control.monthly_control(now.year, now.month)["control_value"], 0)

    def test_loss_case_no_double_count_and_recovery(self):
        # AC-38, AC-39
        order, line = self.order()
        exc = self.make_exception(amount=100000, order=order)
        shift_services.add_cash_entry(self.manager, key(), self.shift.pk, "dau_ca", 0)
        Order.objects.update(status=Order.Status.CANCELLED)
        shift_services.close_shift(self.manager, self.shift.pk)
        first = shift_services.submit_report(self.manager, self.shift.pk, 0, 0)
        self.assertEqual(shift_services.submit_report(self.manager, self.shift.pk, 0, 0), first)  # gửi lại
        with self.assertRaises(ValidationError):
            shift_services.submit_report(self.manager, self.shift.pk, 10000, 0)  # số khác: phải giải trình
        # Tạo thủ công khoản thiếu 100.000 tiền mặt cho ca.
        Discrepancy.objects.create(store=self.d["store"], shift=self.shift, method="tien_mat", expected=100000,
                                   actual=0, difference=-100000, manager=self.manager, over_threshold=True)
        d = Discrepancy.objects.get()
        now = timezone.localtime()
        self.assertEqual(control.monthly_control(now.year, now.month)["in_process"], 100000)
        op = key()
        case = control.open_case(self.d["owner"], "VV bàn 5", operation_key=op)
        self.assertEqual(control.open_case(self.d["owner"], "VV bàn 5", operation_key=op), case)  # gửi lại
        self.assertEqual(case.code, "VV-001")
        control.add_evidence(self.d["owner"], case, exception=exc)
        control.add_evidence(self.d["owner"], case, discrepancy=d, transaction_ref=order.code)
        with self.assertRaises(ValidationError):
            control.add_evidence(self.d["owner"], control.open_case(self.d["owner"], "Khác", operation_key=key()), discrepancy=d)
        self.assertEqual(case.proposed_amount(), 100000)
        control.verify(self.d["owner"], case, 100000)
        control.verify(self.d["owner"], case, 100000)  # bấm lại cùng giá trị
        self.assertEqual(case.verifications.count(), 1)
        op = key()
        control.recover(self.d["owner"], case, 100000, "Nhân viên hoàn", operation_key=op)
        control.recover(self.d["owner"], case, 100000, "Nhân viên hoàn", operation_key=op)
        self.assertEqual((case.verified_amount(), case.recovered_amount(), case.remaining_amount()), (100000, 100000, 0))
        month = control.monthly_control(now.year, now.month)
        self.assertEqual((month["verified"], month["in_process"], month["control_value"], month["recovered"]),
                         (100000, 0, 100000, 100000))
        with self.assertRaises(ValidationError):
            control.verify(self.d["owner"], case, 80000)  # đính chính phải có lý do
        control.verify(self.d["owner"], case, 80000, "Đối chiếu lại camera")
        self.assertEqual(case.verified_amount(), 80000)
        self.assertEqual(case.verifications.count(), 2)
