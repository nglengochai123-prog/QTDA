"""Bảng điều khiển và báo cáo (FR-50, FR-52, FR-53, FR-54; AC-100, AC-104, AC-105, AC-106)."""

import io
import zipfile

from django.urls import reverse
from django.utils import timezone

from apps.control import services as control
from apps.inventory import operations as ops
from apps.inventory.models import StockMovement
from apps.inventory import stock
from apps.orders import adjustments, payments
from apps.orders.models import Order
from apps.orders.tests.helpers import PASSWORD
from apps.orders.tests.test_adjust_pay import Base, key
from apps.reports import services
from apps.shifts import services as shift_services
from apps.shifts.models import Discrepancy, Shift


class ReportTests(Base):
    def paid(self, quantity=1, method="tien_mat"):
        order, line = self.order(quantity=quantity)
        self.finish(line)
        payments.pay_table(self.cashier, key(), order.table_id, method, transfer_confirmed=True)
        return Order.objects.get(pk=order.pk)

    def test_ac105_revenue_totals_match_paid_orders_and_excel(self):
        self.paid(2)
        self.paid(1, "chuyen_khoan")
        today = timezone.localdate()
        for dim in services.DIMENSIONS:
            data = services.revenue(today, today, dim)
            self.assertEqual(data["total"], 75000)
            self.assertEqual(sum(r["revenue"] for r in data["rows"]), 75000)
        by_method = {r["key"]: r["revenue"] for r in services.revenue(today, today, "phuong_thuc")["rows"]}
        self.assertEqual(by_method, {"Tiền mặt": 50000, "Chuyển khoản": 25000})
        book = zipfile.ZipFile(io.BytesIO(services.revenue_xlsx(today, today)))
        self.assertIn("xl/worksheets/sheet7.xml", book.namelist())
        self.assertIn("75000", book.read("xl/worksheets/sheet1.xml").decode())
        self.client.login(username=self.d["owner"].username, password=PASSWORD)
        response = self.client.get(reverse("reports:revenue") + "?xuat=excel")
        self.assertEqual(response["Content-Type"], "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    def test_ac106_material_identity_and_post_prep_not_double(self):
        order, line = self.order(quantity=2)
        from apps.orders import services as order_services

        order_services.complete_line(self.d["barista"], key(), line.pk, 2, 0)
        req = self.request(self.d["waiter"], order, "huy_mon", line=line.pk, cups=1)
        adjustments.decide(self.manager, key(), req.pk, True)  # 1 ly hủy sau pha chế
        ops.record_waste(self.d["barista"], key(), self.d["coffee"].pk, "10", "het_han")
        today = timezone.localdate()
        coffee = [r for r in services.materials(today, today)["rows"] if r["ingredient"] == self.d["coffee"]][0]
        self.assertEqual((coffee["opening"], coffee["consumed"], coffee["post_prep"], coffee["waste"]),
                         (2000, 40, 20, 10))
        self.assertEqual(coffee["opening"] + coffee["receipts"] - coffee["consumed"] - coffee["waste"]
                         + coffee["count_adjust"], coffee["closing"])
        self.d["coffee"].stock.refresh_from_db()
        self.assertEqual(coffee["closing"], self.d["coffee"].stock.physical)

    def test_ac104_control_value_groups(self):
        shift_services.add_cash_entry(self.manager, key(), self.shift.pk, "dau_ca", 0)
        shift_services.close_shift(self.manager, self.shift.pk)
        shift_services.submit_report(self.manager, self.shift.pk, 0, 0)
        mk = lambda amount: Discrepancy.objects.create(  # noqa: E731
            store=self.d["store"], shift=Shift.objects.create(store=self.d["store"], name="Ca", starts_at=self.shift.starts_at,
                                                              ends_at=self.shift.ends_at, approver=self.manager,
                                                              backup_approver=self.backup),
            method="tien_mat", expected=amount, actual=0, difference=-amount, manager=self.manager)
        owner = self.d["owner"]
        case12 = control.open_case(owner, "VV-012", operation_key=key())
        control.add_evidence(owner, case12, discrepancy=mk(100000))
        control.verify(owner, case12, 100000)
        control.recover(owner, case12, 100000, "Hoàn", operation_key=key())
        case15 = control.open_case(owner, "VV-015", operation_key=key())
        control.add_evidence(owner, case15, discrepancy=mk(65000))
        control.verify(owner, case15, 65000)
        mk(20000)
        mk(30000)
        today = timezone.localdate()
        data = services.revenue_control(today.replace(day=1), today)
        c = data["control"]
        self.assertEqual((c["verified"], c["in_process"], c["control_value"], c["recovered"], c["verified_remaining"]),
                         (165000, 50000, 215000, 100000, 65000))
        self.assertFalse(data["met"])

    def test_dashboard_renders_for_owner_only(self):
        # Bỏ Quản lý ca (12/10/2026): bảng điều khiển và báo cáo chỉ dành cho Chủ quán.
        self.paid()
        self.d["milk"].is_critical = True
        self.d["milk"].save()
        self.client.login(username=self.d["owner"].username, password=PASSWORD)
        page = self.client.get(reverse("reports:dashboard"))
        self.assertContains(page, "Ca đang mở")
        self.assertContains(page, "Sữa đặc")
        self.assertContains(page, "BO-01")
        for name in ("reports:revenue", "reports:materials", "reports:revenue_control"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 200)
        self.client.login(username=self.cashier.username, password=PASSWORD)
        for name in ("reports:dashboard", "reports:revenue", "reports:revenue_control"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 403)
        _ = (stock, StockMovement)


class DashboardChartTests(Base):
    paid = ReportTests.paid

    def test_charts_match_report_filter_and_empty_state(self):
        self.paid(2)
        self.paid(1, "chuyen_khoan")
        self.client.login(username=self.d["owner"].username, password=PASSWORD)
        today = timezone.localdate()
        page = self.client.get(reverse("reports:dashboard"))
        data = page.context
        report = services.revenue(data["first"], data["end"])
        self.assertEqual(sum(d["revenue"] for d in data["days"]), report["total"])
        self.assertEqual(sum(d["orders"] for d in data["days"]), report["orders"])
        self.assertContains(page, 'class="chart-svg"')
        self.assertContains(page, "data-tip=")
        older = (today.replace(day=1) - timezone.timedelta(days=40)).strftime("%Y-%m")
        empty = self.client.get(reverse("reports:dashboard") + f"?thang={older}")
        self.assertContains(empty, "Chưa có đơn đã thanh toán trong tháng này")
        self.assertIsNone(empty.context["revenue_chart"])
