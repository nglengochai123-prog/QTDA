"""Kiểm thử đồng thời bổ sung của đợt QA 28/11/2026 (QA-CONC-01..03). Chỉ có giá trị bằng chứng trên PostgreSQL.

Tận dụng khung của test_concurrency (luồng thật, rào xuất phát cùng lúc). Các luồng thật trên SQLite bị khóa cả
tệp nên không chứng minh được gì; vì vậy lớp này bỏ qua khi không chạy trên PostgreSQL.

Để cửa sổ tranh chấp không phụ thuộc may rủi, QA-CONC-01 làm chậm bước tính số liệu kết ca 0,8 giây (chỉ trong
test, bọc hàm thật, không đổi logic): kết ca đã kiểm tra điều kiện xong và đang giữ khóa ca thì đơn mới tới.
"""

import time
import unittest
import uuid
from datetime import timedelta
from unittest import mock

from django.db import connection
from django.utils import timezone

from apps.core.tests.test_concurrency import ConcurrencyTests, run_parallel
from apps.orders import services
from apps.orders.models import Order
from apps.orders.tests.helpers import cart
from apps.shifts import services as shifts
from apps.shifts.models import CashEntry, Shift


def key():
    return uuid.uuid4().hex


@unittest.skipUnless(connection.vendor == "postgresql", "Bằng chứng tranh chấp chỉ tính trên PostgreSQL")
class QAConcurrencyTests(ConcurrencyTests):
    # Không chạy lại 5 tình huống gốc ở lớp con.
    test_orders_compete_for_last_stock = None
    test_same_operation_key_sent_concurrently = None
    test_complete_line_many_times = None
    test_pay_same_table_concurrently = None
    test_two_approvers_decide_same_request = None

    def test_qa_conc_01_order_sent_while_shift_closing(self):
        """QA-CONC-01: phục vụ gửi đơn đúng lúc thu ngân bấm Kết ca. Mong đợi: hoặc kết ca bị chặn vì có đơn mới,
        hoặc đơn mới không nằm trong ca đã kết. Không được có đơn chưa thanh toán thuộc một ca đã kết."""
        shifts.add_cash_entry(self.cashier, key(), self.shift.pk, CashEntry.Kind.OPENING, 0)
        real = shifts.figures

        def slow_figures(shift):
            time.sleep(0.8)
            return real(shift)

        def work(i):
            if i == 0:
                return shifts.close_shift(self.cashier, self.shift.pk)
            time.sleep(0.2)  # để kết ca kiểm tra điều kiện trước, rồi đơn tới khi kết ca đang tính số
            return services.submit_order(self.d["waiter"], key(), cart(self.d))

        with mock.patch.object(shifts, "figures", slow_figures):
            results = run_parallel(work, n=2)
        self.shift.refresh_from_db()
        stuck = Order.objects.filter(shift=self.shift).exclude(status__in=[Order.Status.PAID, Order.Status.CANCELLED])
        print("\nQA-CONC-01:", [(r[0], type(r[1]).__name__) for r in results], "ca:", self.shift.status,
              "đơn chưa thu trong ca đã kết:", list(stuck.values_list("code", flat=True)))
        if self.shift.status == Shift.Status.CLOSED:
            self.assertFalse(stuck.exists(), "Ca đã kết nhưng vẫn có đơn chưa thanh toán gắn vào ca đó")

    def test_qa_conc_02_two_expenses_cannot_overdraw_cash(self):
        """QA-CONC-02: hai thu ngân cùng ghi chi 60.000 đ khi két chỉ có 100.000 đ: chỉ một khoản được ghi."""
        shifts.add_cash_entry(self.cashier, key(), self.shift.pk, CashEntry.Kind.OPENING, 100000)
        results = run_parallel(lambda i: shifts.add_cash_entry(
            self.cashier, key(), self.shift.pk, CashEntry.Kind.EXPENSE, 60000, category="sua_chua", note="Sửa máy"),
            n=4)
        ok = [r for r in results if r[0] == "ok"]
        print("\nQA-CONC-02:", [(r[0], type(r[1]).__name__) for r in results])
        self.assertEqual(len(ok), 1, results)
        self.assertGreaterEqual(shifts.cash_on_hand(self.shift), 0)

    def test_qa_conc_03_shift_close_twice(self):
        """QA-CONC-03: hai người cùng bấm Kết ca: ca kết đúng một lần, một bản ghi nhật ký kết ca."""
        from apps.audit.models import AuditLog

        shifts.add_cash_entry(self.cashier, key(), self.shift.pk, CashEntry.Kind.OPENING, 0)
        before = AuditLog.objects.filter(object_type="shifts.Shift").count()
        results = run_parallel(lambda i: shifts.close_shift([self.cashier, self.manager][i % 2], self.shift.pk), n=4)
        self.shift.refresh_from_db()
        self.assertEqual(self.shift.status, Shift.Status.CLOSED, results)
        self.assertEqual(AuditLog.objects.filter(object_type="shifts.Shift").count() - before, 1)

    def setUp(self):
        super().setUp()
        now = timezone.now()
        self.shift.starts_at, self.shift.ends_at = now - timedelta(hours=1), now + timedelta(hours=4)
        self.shift.save(update_fields=["starts_at", "ends_at"])
