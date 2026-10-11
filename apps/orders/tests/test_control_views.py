import uuid
from datetime import timedelta

from django.urls import reverse

from apps.orders import adjustments
from apps.orders.models import AdjustmentRequest, Order, Payment

from .test_adjust_pay import Base, key


class ControlViewTests(Base):
    def test_adjust_form_requires_reason_then_manager_approves(self):
        order, line = self.order()
        self.client.force_login(self.d["waiter"])
        self.assertContains(self.client.get(reverse("orders:open_orders")), "Yêu cầu điều chỉnh")
        url = reverse("orders:request_adjustment", args=[order.pk])
        data = {"operation_key": key(), "kind": "huy_mon", "line": line.pk, "cups": 1, "reason": ""}
        response = self.client.post(url, data)
        self.assertContains(response, "Chọn lý do điều chỉnh")  # AC-20
        data.update(reason=self.reason.pk, operation_key=key())
        self.assertRedirects(self.client.post(url, data), reverse("orders:open_orders"))
        req = AdjustmentRequest.objects.get()
        self.assertEqual(self.client.get(reverse("orders:approvals_count")).json()["count"], 0)

        self.client.force_login(self.manager)
        self.assertEqual(self.client.get(reverse("orders:approvals_count")).json()["count"], 1)
        self.assertContains(self.client.get(reverse("orders:approvals")), "Khách đổi ý")
        body = {"operation_key": key(), "decision": "approve"}
        self.client.post(reverse("orders:decide", args=[req.pk]), body)
        self.client.post(reverse("orders:decide", args=[req.pk]), body)  # bấm lại
        req.refresh_from_db()
        self.assertEqual(req.status, AdjustmentRequest.Status.APPROVED)

    def test_backup_approver_of_any_role_sees_escalated_request(self):
        order, line = self.order()
        req = self.request(self.d["waiter"], order, "chuyen_ban", target_table=self.other_table.pk)
        AdjustmentRequest.objects.filter(pk=req.pk).update(level_since=req.level_since - timedelta(minutes=4))
        self.client.force_login(self.backup)  # vai trò Phục vụ, là người duyệt dự phòng của ca
        self.assertEqual(self.client.get(reverse("orders:approvals_count")).json()["count"], 1)
        self.assertEqual(self.client.get(reverse("orders:approvals")).status_code, 200)

    def test_cashier_screen_and_payment(self):
        order, line = self.order()
        self.finish(line)
        self.client.force_login(self.cashier)
        self.assertContains(self.client.get(reverse("orders:cashier")), "Thu 25.000")
        op = key()
        url = reverse("orders:pay", args=[order.table_id])
        self.client.post(url, {"operation_key": op, "method": "tien_mat"})
        self.client.post(url, {"operation_key": op, "method": "tien_mat"})
        self.assertEqual(Payment.objects.count(), 1)
        self.client.force_login(self.d["waiter"])
        self.assertEqual(self.client.get(reverse("orders:cashier")).status_code, 403)

    def test_cashier_sees_why_table_is_blocked(self):
        order, line = self.order()
        self.client.force_login(self.cashier)
        self.assertContains(self.client.get(reverse("orders:cashier")), "chưa phục vụ xong")

    def test_cashier_lists_only_tables_with_open_orders(self):
        from apps.orders import payments

        self.order()
        self.assertEqual([b["table"] for b in payments.tables_with_bills()], [self.d["table"]])
