"""Kiểm tra phân quyền phía máy chủ cho cả 5 vai trò theo Bảng 5.3.

Bảng kỳ vọng dưới đây chép độc lập từ BRD (không đọc từ permissions.CAPABILITIES),
để phát hiện khi ai đó sửa ma trận trong mã nguồn sai so với tài liệu.
"""

from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.test import RequestFactory, TestCase
from django.urls import reverse

from apps.accounts.models import Role, User
from apps.accounts.permissions import CAPABILITIES, Cap, capability_required, user_can
from apps.audit.models import Action, AuditLog

PASSWORD = "matkhau-thu-123"
O, M, C, W, B = Role.CHU_QUAN, Role.QUAN_LY_CA, Role.THU_NGAN, Role.PHUC_VU, Role.PHA_CHE

# Quản lý ca đã bỏ theo quyết định của Chủ quán ngày 12/10/2026: vai trò cũ không còn quyền nào.
EXPECTED = {
    Cap.ORDER_CREATE: {O, C, W},
    Cap.BAR_PREPARE: {O, B},
    Cap.ORDER_ADJUST_APPROVE: {O},
    Cap.PAID_INVOICE_CANCEL: {O},
    Cap.PAYMENT: {O, C},
    Cap.CASH_FUND: {O, C},
    Cap.SHIFT_CLOSE: {O, C},
    Cap.BACKUP_TICKETS: {O},
    Cap.EXCEPTION_REVIEW: {O},
    Cap.STOCK_OPERATIONS: {O, B},
    Cap.STOCK_CONFIRM_ORDERING: {O},
    Cap.MASTER_INVENTORY: {O},
    Cap.TIMEKEEPING: {C, W, B},
    Cap.TIMEKEEPING_ADJUST: {O},
    Cap.VIEW_WORKLOAD: {O},
    Cap.SHIFT_REGISTER: {C, W, B},
    Cap.SCHEDULE_MANAGE: {O},
    Cap.PAYROLL: {O},
    Cap.FINANCE: {O},
    Cap.VIEW_DASHBOARD: {O},
    Cap.VIEW_FINANCIALS: {O},
    Cap.HANDLE_ALERTS: {O, B},
    Cap.FORECASTS: {O},
    Cap.MASTER_DATA: {O},
    Cap.AUDIT_LOG: {O},
}


def make_users():
    return {role: User.objects.create_user(f"u_{role}", password=PASSWORD, role=role) for role in Role.values}


class MatrixTests(TestCase):
    def setUp(self):
        self.users = make_users()
        self.factory = RequestFactory()

    def test_matrix_matches_brd(self):
        self.assertEqual(set(CAPABILITIES), set(EXPECTED))
        for cap, roles in EXPECTED.items():
            self.assertEqual(CAPABILITIES[cap][1], roles, cap)

    def test_every_role_every_capability_on_server(self):
        for cap, roles in EXPECTED.items():
            view = capability_required(cap)(lambda request: HttpResponse("ok"))
            for role, user in self.users.items():
                with self.subTest(cap=cap, role=role):
                    request = self.factory.get(f"/thu/{cap}/")
                    request.user = user
                    if role in roles:
                        self.assertEqual(view(request).status_code, 200)
                    else:
                        with self.assertRaises(PermissionDenied):
                            view(request)

    def test_denied_access_is_logged(self):
        # AC-111: pha chế mở báo cáo kiểm soát doanh thu bị từ chối và ghi nhật ký.
        view = capability_required(Cap.VIEW_DASHBOARD)(lambda request: HttpResponse("ok"))
        request = self.factory.get("/bao-cao/kiem-soat-doanh-thu/")
        request.user = self.users[B]
        with self.assertRaises(PermissionDenied):
            view(request)
        log = AuditLog.objects.get(action=Action.ACCESS_DENIED)
        self.assertEqual(log.actor, self.users[B])
        self.assertIn(Cap.VIEW_DASHBOARD, log.reason)

    def test_anonymous_redirected_to_login(self):
        from django.contrib.auth.models import AnonymousUser

        view = capability_required(Cap.ORDER_CREATE)(lambda request: HttpResponse("ok"))
        request = self.factory.get("/")
        request.user = AnonymousUser()
        self.assertEqual(view(request).status_code, 302)

    def test_inactive_user_has_no_capability(self):
        user = self.users[O]
        user.is_active = False
        self.assertFalse(user_can(user, Cap.MASTER_DATA))

    def test_superuser_counts_as_owner(self):
        admin = User.objects.create_superuser("admin", password=PASSWORD)
        self.assertTrue(user_can(admin, Cap.AUDIT_LOG))
        self.assertFalse(user_can(admin, Cap.TIMEKEEPING))


class AdminAccessTests(TestCase):
    """Trang dữ liệu nền chỉ Chủ quán vào được; kiểm tra bằng yêu cầu HTTP thật."""

    def setUp(self):
        self.users = make_users()

    def test_admin_index_only_for_owner(self):
        for role, user in self.users.items():
            with self.subTest(role=role):
                self.client.force_login(user)
                response = self.client.get(reverse("admin:index"))
                self.assertEqual(response.status_code, 200 if role == O else 302)
                self.client.logout()

    def test_owner_flagged_staff_others_not(self):
        for role, user in self.users.items():
            self.assertEqual(user.is_staff, role == O, role)

    def test_audit_log_view_only_for_owner(self):
        url = reverse("admin:audit_auditlog_changelist")
        for role, user in self.users.items():
            with self.subTest(role=role):
                self.client.force_login(user)
                self.assertEqual(self.client.get(url).status_code, 200 if role == O else 302)
                self.client.logout()

    def test_manager_cannot_change_load_factor(self):
        # AC-114: Quản lý ca thử đổi hệ số tải nhóm món bị từ chối.
        from apps.catalog.models import MenuGroup
        from apps.core.models import Store

        group = MenuGroup.objects.create(store=Store.get_default(), name="Pha máy")
        self.client.force_login(self.users[M])
        url = reverse("admin:catalog_menugroup_change", args=[group.pk])
        self.client.post(url, {"name": "Pha máy", "load_factor": "3.00", "is_active": "on", "sort_order": 0})
        group.refresh_from_db()
        self.assertEqual(str(group.load_factor), "1.00")
