"""Nghiệm thu xuyên suốt qua giao diện web theo 5 vai trò (Chủ quán, Quản lý ca, Thu ngân, Phục vụ, Pha chế).

Mọi thao tác đi qua đường dẫn thật của ứng dụng bằng tài khoản đúng vai trò, không gọi thẳng hàm nghiệp vụ:
nhập hàng → khai báo và mở ca → nhận đơn → pha một phần → phục vụ → điều chỉnh → thanh toán → hủy hóa đơn
và hoàn tiền → nhập bù phiếu dự phòng → kiểm kê → đơn chuyển sang ca sau → kết ca → báo cáo cuối ca
→ báo cáo. Kèm các tình huống bị từ chối quyền, gửi lại thao tác, pha một phần và giao dịch qua thời điểm kết ca.
Cuối cùng đối chiếu đơn, kho, quỹ ca, doanh thu, ngoại lệ, nhật ký và kiểm tra toàn vẹn.
"""

import json
import tempfile
import uuid
from datetime import timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.audit.models import AuditLog
from apps.catalog.models import Table
from apps.control.models import ExceptionCase
from apps.core import integrity
from apps.inventory import stock
from apps.inventory.models import Receipt, StockCount, Supplier
from apps.orders.models import AdjustmentReason, AdjustmentRequest, BackupSlip, Order, Payment
from apps.orders.tests.helpers import PASSWORD, D, build_menu, cart, levels
from apps.reports import services as reports
from apps.shifts import services as shift_services
from apps.shifts.models import CashEntry, Refund, Shift, ShiftReport


def key():
    return uuid.uuid4().hex


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class FiveRoleAcceptanceTests(TestCase):
    def setUp(self):
        self.d = build_menu()
        mk = lambda name, role: User.objects.create_user(name, password=PASSWORD, role=role)  # noqa: E731
        self.owner, self.waiter, self.barista = self.d["owner"], self.d["waiter"], self.d["barista"]
        self.manager = mk("quanlyca", Role.QUAN_LY_CA)
        self.cashier = mk("thungan", Role.THU_NGAN)
        self.backup = mk("duphong", Role.QUAN_LY_CA)
        self.table7 = Table.objects.create(store=self.d["store"], code="7")
        self.reason = AdjustmentReason.objects.get(name="Khách đổi ý")

    # ---------- tiện ích gửi yêu cầu như trình duyệt ----------

    def as_(self, user):
        self.client.logout()
        self.assertTrue(self.client.login(username=user.username, password=PASSWORD))

    def post_json(self, name, body, *args):
        response = self.client.post(reverse(name, args=args), json.dumps(body), content_type="application/json")
        return response.status_code, response.json()

    def order(self, user, payload, op=None):
        return self.post_json("orders:submit", {"operation_key": op or key(), "order": payload})

    def denied(self, user, method, name, *args, data=None):
        self.as_(user)
        call = self.client.post if method == "post" else self.client.get
        self.assertEqual(call(reverse(name, args=args), data or {}).status_code, 403, f"{user} {name}")

    def test_full_day_through_the_web(self):
        now = timezone.localtime()
        # 1. Chủ quán khai báo ca qua trang dữ liệu nền; thiếu người duyệt dự phòng thì không lưu được (GD-08).
        self.as_(self.owner)
        form = {"name": "Ca chiều", "starts_at_0": (now - timedelta(hours=1)).strftime("%Y-%m-%d"),
                "starts_at_1": (now - timedelta(hours=1)).strftime("%H:%M:%S"),
                "ends_at_0": (now + timedelta(hours=3)).strftime("%Y-%m-%d"),
                "ends_at_1": (now + timedelta(hours=3)).strftime("%H:%M:%S"),
                "approver": self.manager.pk, "payment_authorizer": self.cashier.pk, "status": "dang_mo"}
        self.client.post(reverse("admin:shifts_shift_add"), form)
        self.assertFalse(Shift.objects.exists())
        self.client.post(reverse("admin:shifts_shift_add"), {**form, "backup_approver": self.backup.pk})
        shift_a = Shift.objects.get()

        # 2. Nhập hàng (Pha chế): ảnh hóa đơn bắt buộc; gửi lại không ghi trùng.
        supplier = Supplier.objects.create(store=self.d["store"], name="NCC sữa")
        self.as_(self.barista)
        op = key()
        receipt = {"operation_key": op, "supplier": supplier.pk, "payment_type": "tra_sau", "due_days": 7, "rows": 1,
                   "ingredient_0": self.d["milk"].pk, "quantity_0": "1000", "price_0": "30"}
        self.client.post(reverse("inventory:receipt"), receipt)
        self.assertFalse(Receipt.objects.exists())  # thiếu ảnh
        for _ in range(2):
            photo = SimpleUploadedFile("hd.jpg", b"jpeg", content_type="image/jpeg")
            self.client.post(reverse("inventory:receipt"), {**receipt, "invoice_photo": photo})
        self.assertEqual(Receipt.objects.count(), 1)
        self.assertEqual(levels(self.d["milk"])[0], D(2000))

        # 3. Mở ca: Quản lý ca xác nhận tiền đầu ca.
        self.as_(self.manager)
        self.client.post(reverse("shifts:cash_entry", args=[shift_a.pk]),
                         {"operation_key": key(), "kind": "dau_ca", "amount": "500000"})
        self.assertEqual(shift_services.figures(shift_a)["opening"], 500000)

        # 4. Phục vụ nhận đơn bàn 5 (3 ly); gửi lại cùng mã không tạo đơn thứ hai.
        self.as_(self.waiter)
        op = key()
        for _ in range(2):
            status, body = self.order(self.waiter, cart(self.d, quantity=3), op)
            self.assertEqual(status, 200)
        order_a = Order.objects.get()
        line = order_a.lines.get()
        self.assertEqual(levels(self.d["coffee"]), (D(2000), D(60), D(1940)))

        # 5. Pha chế pha một phần (2 ly), bấm lại không trừ thêm.
        self.as_(self.barista)
        for _ in range(2):
            self.post_json("orders:bar_complete", {"operation_key": key(), "line": line.pk, "cups": 2, "expected_done": 0})
        self.assertEqual(levels(self.d["coffee"]), (D(1960), D(20), D(1940)))

        # 6. Điều chỉnh: phục vụ xin bỏ 2 ly (1 chưa pha, 1 đã pha); Quản lý ca duyệt trên điện thoại.
        self.as_(self.waiter)
        self.client.post(reverse("orders:request_adjustment", args=[order_a.pk]),
                         {"operation_key": key(), "kind": "huy_mon", "line": line.pk, "cups": 2, "reason": self.reason.pk})
        req = AdjustmentRequest.objects.get()
        self.denied(self.waiter, "post", "orders:decide", req.pk, data={"decision": "approve"})
        self.as_(self.manager)
        op = key()
        for _ in range(2):
            self.client.post(reverse("orders:decide", args=[req.pk]), {"operation_key": op, "decision": "approve"})
        order_a.refresh_from_db()
        self.assertEqual(order_a.total, 25000)
        self.assertEqual(levels(self.d["coffee"]), (D(1960), D(0), D(1960)))

        # 7. Phục vụ mang ly còn lại ra; thu ngân thu tiền mặt (gửi lại không thu hai lần).
        self.as_(self.waiter)
        self.post_json("orders:serve", {"operation_key": key(), "line": line.pk})
        self.as_(self.cashier)
        op = key()
        for _ in range(2):
            self.client.post(reverse("orders:pay", args=[self.d["table"].pk]), {"operation_key": op, "method": "tien_mat"})
        self.assertEqual(Payment.objects.count(), 1)

        # 8. Hủy hóa đơn đã thanh toán: thu ngân xin, chỉ Chủ quán duyệt; thu ngân xác nhận đã hoàn tiền.
        self.client.post(reverse("orders:request_adjustment", args=[order_a.pk]),
                         {"operation_key": key(), "kind": "huy_hoa_don", "reason": self.reason.pk})
        cancel = AdjustmentRequest.objects.get(kind="huy_hoa_don")
        self.denied(self.manager, "post", "orders:decide", cancel.pk, data={"decision": "approve"})
        cancel.refresh_from_db()
        self.assertEqual(cancel.status, "cho_duyet")
        self.as_(self.owner)
        self.client.post(reverse("orders:decide", args=[cancel.pk]), {"operation_key": key(), "decision": "approve"})
        refund = Refund.objects.get()
        self.assertEqual((refund.status, refund.shift), ("cho_hoan", None))
        self.as_(self.cashier)
        op = key()
        for _ in range(2):
            self.client.post(reverse("shifts:refund_paid", args=[refund.pk]), {"operation_key": op})
        refund.refresh_from_db()
        self.assertEqual((refund.status, refund.shift), ("da_hoan", shift_a))

        # 9. Mất mạng: Quản lý ca cấp dãy phiếu và nhập bù một phiếu; thu ngân không có quyền.
        self.denied(self.cashier, "post", "orders:backup_slips", data={"action": "issue"})
        self.as_(self.manager)
        url = reverse("orders:backup_slips")
        self.client.post(url, {"action": "issue", "shift": shift_a.pk, "first": "151", "last": "152",
                               "receiver": self.manager.pk})
        sold = (timezone.localtime() + timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M")
        slip = {"action": "enter", "operation_key": key(), "number": "151", "sold_at": sold, "restored_at": sold,
                "table": self.table7.pk, "method": "chuyen_khoan", "transfer_confirmed": "1",
                "item_0": f"{self.d['item'].pk}:{self.d['size_m'].pk}", "qty_0": "1"}
        for _ in range(2):
            self.client.post(url, slip)
        self.assertEqual(BackupSlip.objects.get().order.total, 25000)
        self.client.post(url, {"action": "declare", "range": shift_a.backup_ranges.get().pk, "last_used": "151"})

        # 10. Kiểm kê cuối ca (Pha chế), trong ngưỡng nên áp dụng ngay.
        self.as_(self.barista)
        self.d["coffee"].stock.refresh_from_db()
        counted = self.d["coffee"].stock.physical - 5
        self.client.post(reverse("inventory:count"), {"operation_key": key(), "ingredient": self.d["coffee"].pk,
                                                      "counted": str(counted)})
        self.assertEqual(StockCount.objects.get().status, "da_ap_dung")

        # 11. Đơn còn mở lúc kết ca: chặn kết ca, chuyển sang ca sau, thu tiền ở ca sau.
        self.as_(self.waiter)
        late_cart = cart(self.d)
        late_cart["table"] = self.table7.pk
        self.order(self.waiter, late_cart)
        late = Order.objects.filter(shift=shift_a).exclude(pk=order_a.pk).exclude(backup_slip__isnull=False).get()
        self.as_(self.manager)
        self.client.post(reverse("shifts:close", args=[shift_a.pk]))
        shift_a.refresh_from_db()
        self.assertEqual(shift_a.status, "dang_mo")
        shift_b = Shift.objects.create(store=self.d["store"], name="Ca tối", starts_at=timezone.now(),
                                       ends_at=timezone.now() + timedelta(hours=4), approver=self.manager,
                                       backup_approver=self.backup, payment_authorizer=self.cashier)
        self.client.post(reverse("shifts:carry", args=[shift_a.pk]),
                         {"order": late.pk, "to_shift": shift_b.pk, "reason": "Khách ngồi lại"})
        self.client.post(reverse("shifts:close", args=[shift_a.pk]))
        shift_a.refresh_from_db()
        self.assertEqual(shift_a.status, "da_ket")
        late_line = late.lines.get()
        self.as_(self.barista)
        self.post_json("orders:bar_complete", {"operation_key": key(), "line": late_line.pk, "cups": 1, "expected_done": 0})
        self.as_(self.waiter)
        self.post_json("orders:serve", {"operation_key": key(), "line": late_line.pk})
        self.as_(self.cashier)
        self.client.post(reverse("orders:pay", args=[self.table7.pk]), {"operation_key": key(), "method": "tien_mat"})
        self.assertEqual(Payment.objects.get(orders=late).shift, shift_b)

        # 12. Báo cáo cuối ca A: tiền mặt 500.000 + 25.000 − hoàn 25.000 = 500.000, chuyển khoản 25.000 (phiếu).
        self.as_(self.manager)
        self.client.post(reverse("shifts:report", args=[shift_a.pk]),
                         {"counted_cash": "500000", "transfer_received": "25000", "transfer_refunded": "0"})
        self.assertTrue(ShiftReport.objects.filter(shift=shift_a).exists())
        f = shift_services.figures(shift_a)
        self.assertEqual((f["revenue_cash"], f["refunds_cash"], f["expected_cash"], f["revenue_transfer"]),
                         (25000, 25000, 500000, 25000))
        self.assertFalse(shift_a.discrepancies.exists())

        # 13. Quyền xem báo cáo.
        self.denied(self.waiter, "get", "reports:dashboard")
        self.denied(self.cashier, "get", "reports:revenue")
        self.denied(self.manager, "get", "reports:revenue_control")
        self.denied(self.barista, "get", "shifts:status")
        for user, name in ((self.manager, "reports:dashboard"), (self.manager, "reports:materials"),
                           (self.owner, "reports:revenue_control"), (self.owner, "reports:revenue")):
            self.as_(user)
            self.assertEqual(self.client.get(reverse(name)).status_code, 200)

        # ---------- Đối chiếu chéo ----------
        today = timezone.localdate()
        revenue = reports.revenue(today, today)
        paid_total = sum(o.total for o in Order.objects.filter(status="da_thanh_toan"))
        self.assertEqual(revenue["total"], paid_total)  # báo cáo doanh thu khớp các đơn đã thanh toán
        self.assertEqual(paid_total, 50000)  # phiếu 0151 + đơn chuyển ca; đơn bàn 5 đã hủy và hoàn
        self.assertEqual(revenue["refunds"], 25000)
        self.assertEqual(Order.objects.get(pk=order_a.pk).status, "da_huy")
        self.assertEqual(CashEntry.objects.filter(kind="dau_ca").count(), 1)
        self.assertTrue(ExceptionCase.objects.filter(kind="huy_sau_tt").exists())  # hủy sau thanh toán
        self.assertEqual(stock.ledger_problems(), [])
        self.assertEqual(integrity.problems(), [])
        actors = set(AuditLog.objects.exclude(actor=None).values_list("actor__username", flat=True))
        self.assertTrue({u.username for u in (self.owner, self.manager, self.cashier, self.waiter, self.barista)} <= actors)
        denied = AuditLog.objects.filter(action="access_denied").count()
        self.assertGreaterEqual(denied, 6)  # mọi lần bị từ chối quyền đều ghi nhật ký (AC-111)
