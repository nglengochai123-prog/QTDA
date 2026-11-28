"""Lãi lỗ theo tháng (Hai, 28/11/2026): lợi nhuận = doanh thu thuần − chi phí, mỗi khoản lấy từ dữ liệu nghiệp vụ."""

from datetime import timedelta

from django.urls import reverse
from django.utils import timezone

from apps.inventory import operations as ops
from apps.inventory.models import Receipt, ReceiptLine, Supplier
from apps.orders import payments
from apps.orders.tests.test_adjust_pay import Base, key
from apps.reports import profit
from apps.reports.models import MonthlyExpense
from apps.shifts import services as shifts
from apps.staff.models import Attendance, Employee


class ProfitTests(Base):
    def setUp(self):
        super().setUp()
        sup = Supplier.objects.create(store=self.d["store"], name="NCC thử")
        receipt = Receipt.objects.create(store=self.d["store"], supplier=sup, code="PN-THU", created_by=self.d["owner"],
                                         payment_type=Receipt.PaymentType.values[0])
        ReceiptLine.objects.create(receipt=receipt, ingredient=self.d["coffee"], quantity=1000, unit_price=300)
        ReceiptLine.objects.create(receipt=receipt, ingredient=self.d["milk"], quantity=1000, unit_price=50)

    def test_profit_is_revenue_minus_each_cost(self):
        order, line = self.order()  # 25.000 đ: 20 g cà phê × 300 + 30 ml sữa × 50 = 7.500 đ giá vốn
        self.finish(line)
        payments.pay_table(self.cashier, key(), order.table_id, "tien_mat")
        ops.record_waste(self.d["owner"], key(), self.d["milk"].pk, "10", "hu_hong", "")  # 500 đ hao hụt
        shifts.add_cash_entry(self.cashier, key(), self.shift.pk, "chi", 20000, category="sua_chua", note="Bóng đèn")
        emp = Employee.create_with_account(full_name="Nhân viên thử", phone="0911111111", roles=["phuc_vu"],
                                           hourly_wage=20000)
        now = timezone.now()
        Attendance.objects.create(store=self.d["store"], user=emp.user, role="phuc_vu",
                                  clock_in=now - timedelta(hours=3), clock_out=now - timedelta(hours=1))  # 2 giờ
        first = timezone.localdate().replace(day=1)
        MonthlyExpense.objects.create(store=self.d["store"], month=first, category="mat_bang", amount=100000,
                                      created_by=self.d["owner"])
        data = profit.month(first)
        amounts = {c["label"].split(" (")[0]: c["amount"] for c in data["costs"]}
        self.assertEqual(data["net"], 25000)
        self.assertEqual(amounts["Giá vốn nguyên liệu đã dùng"], 7500)
        self.assertEqual(amounts["Hao hụt"], 500)
        self.assertEqual(amounts["Lương theo giờ công"], 40000)
        self.assertEqual(amounts["Chi quỹ ca: sửa chữa và thiết bị"], 20000)
        self.assertEqual(amounts["Mặt bằng"], 100000)
        self.assertEqual(data["total_cost"], 7500 + 500 + 40000 + 20000 + 100000)
        self.assertEqual(data["profit"], 25000 - data["total_cost"])
        self.assertEqual(data["gross"], 25000 - 7500)

    def test_owner_adds_copies_and_removes_monthly_costs_staff_cannot_see(self):
        self.client.force_login(self.d["owner"])
        url = reverse("reports:profit")
        first = timezone.localdate().replace(day=1)
        prev = (first - timedelta(days=1)).replace(day=1)
        self.client.post(url, {"thang": f"{prev:%Y-%m}", "action": "add", "category": "dien_nuoc", "amount": "1.200.000"})
        self.assertEqual(MonthlyExpense.objects.get(month=prev).amount, 1200000)
        self.client.post(url, {"thang": f"{first:%Y-%m}", "action": "copy_prev"})
        copied = MonthlyExpense.objects.get(month=first)
        self.assertEqual((copied.category, copied.amount), ("dien_nuoc", 1200000))
        page = self.client.get(url)
        self.assertContains(page, "Lợi nhuận")
        self.assertContains(page, "Điện, nước, gas")
        self.client.post(url, {"thang": f"{first:%Y-%m}", "action": "delete", "expense": copied.pk})
        self.assertFalse(MonthlyExpense.objects.filter(month=first).exists())
        self.client.force_login(self.cashier)
        self.assertEqual(self.client.get(url).status_code, 403)
