"""Phân quyền theo Bảng 5.3 của BRD, kiểm tra tại máy chủ (NFR-07).

Mỗi chức năng là một "quyền" (Cap) gắn với tập vai trò được phép. Màn hình nào
cũng phải khai báo quyền của nó bằng capability_required hoặc CapabilityRequiredMixin;
không chỉ ẩn nút trên giao diện.
"""

from functools import wraps

from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied

from .models import Role

OWNER = Role.CHU_QUAN
MANAGER = Role.QUAN_LY_CA  # Không còn dùng (Hai 12/10/2026: Chủ quán trực tiếp quản lý ca)
CASHIER = Role.THU_NGAN
WAITER = Role.PHUC_VU
BARISTA = Role.PHA_CHE


class Cap:
    ORDER_CREATE = "order_create"
    BAR_PREPARE = "bar_prepare"
    ORDER_ADJUST_APPROVE = "order_adjust_approve"
    PAID_INVOICE_CANCEL = "paid_invoice_cancel"
    PAYMENT = "payment"
    CASH_FUND = "cash_fund"
    SHIFT_CLOSE = "shift_close"
    BACKUP_TICKETS = "backup_tickets"
    EXCEPTION_REVIEW = "exception_review"
    STOCK_OPERATIONS = "stock_operations"
    STOCK_CONFIRM_ORDERING = "stock_confirm_ordering"
    MASTER_INVENTORY = "master_inventory"
    TIMEKEEPING = "timekeeping"
    TIMEKEEPING_ADJUST = "timekeeping_adjust"
    VIEW_WORKLOAD = "view_workload"
    SHIFT_REGISTER = "shift_register"
    SCHEDULE_MANAGE = "schedule_manage"
    PAYROLL = "payroll"
    FINANCE = "finance"
    VIEW_DASHBOARD = "view_dashboard"
    VIEW_FINANCIALS = "view_financials"
    HANDLE_ALERTS = "handle_alerts"
    FORECASTS = "forecasts"
    MASTER_DATA = "master_data"
    AUDIT_LOG = "audit_log"


# (mô tả, vai trò được phép) — chép đúng thứ tự dòng của Bảng 5.3.
CAPABILITIES = {
    Cap.ORDER_CREATE: ("Tạo đơn, gửi yêu cầu điều chỉnh đơn", {OWNER, CASHIER, WAITER}),
    Cap.BAR_PREPARE: ("Nhận món tại quầy, cập nhật Đã pha chế", {OWNER, BARISTA}),
    Cap.ORDER_ADJUST_APPROVE: ("Phê duyệt điều chỉnh đơn", {OWNER}),
    Cap.PAID_INVOICE_CANCEL: ("Phê duyệt hủy hóa đơn đã thanh toán", {OWNER}),
    Cap.PAYMENT: ("Thanh toán", {OWNER, CASHIER}),
    Cap.CASH_FUND: ("Tiền đầu ca, chi tiền mặt, nộp tiền giữa ca", {OWNER, CASHIER}),
    Cap.SHIFT_CLOSE: ("Kết ca, báo cáo cuối ca, giải trình chênh lệch", {OWNER, CASHIER}),
    Cap.BACKUP_TICKETS: ("Phiếu dự phòng, nhập bù, khai báo phiếu hủy", {OWNER}),
    Cap.EXCEPTION_REVIEW: ("Xem xét ngoại lệ, vụ việc tổn thất", {OWNER}),
    Cap.STOCK_OPERATIONS: ("Báo nhanh nguyên liệu, phiếu nhập, kiểm kê, hao hụt", {OWNER, BARISTA}),
    Cap.STOCK_CONFIRM_ORDERING: ("Xác nhận chênh lệch kiểm kê, ghi nhận đặt hàng", {OWNER}),
    Cap.MASTER_INVENTORY: ("Khai báo nguyên vật liệu, định mức, nhà cung cấp", {OWNER}),
    Cap.TIMEKEEPING: ("Chấm công vào ca, ra ca", {CASHIER, WAITER, BARISTA}),
    Cap.TIMEKEEPING_ADJUST: ("Bổ sung giờ ra ca, xác nhận thời gian ngoài lịch", {OWNER}),
    Cap.VIEW_WORKLOAD: ("Xem tải, thời gian chờ, khung giờ quá tải", {OWNER}),
    Cap.SHIFT_REGISTER: ("Đăng ký ca (Giai đoạn 2)", {CASHIER, WAITER, BARISTA}),
    Cap.SCHEDULE_MANAGE: ("Nhu cầu nhân sự, công bố lịch (Giai đoạn 2)", {OWNER}),
    Cap.PAYROLL: ("Bảng lương, đơn giá lương (Giai đoạn 2)", {OWNER}),
    Cap.FINANCE: ("Khoản phải trả, sổ chi phí, khóa sổ (Giai đoạn 2)", {OWNER}),
    Cap.VIEW_DASHBOARD: ("Bảng điều khiển, báo cáo doanh thu, nguyên vật liệu", {OWNER}),
    Cap.VIEW_FINANCIALS: ("Xem lợi nhuận, chi phí, lương", {OWNER}),
    Cap.HANDLE_ALERTS: ("Xem và xử lý cảnh báo được giao", {OWNER, BARISTA}),
    Cap.FORECASTS: ("Ước tính và đề xuất", {OWNER}),
    Cap.MASTER_DATA: ("Tài khoản, danh mục món, bảng giá, tham số", {OWNER}),
    Cap.AUDIT_LOG: ("Tra cứu nhật ký thao tác", {OWNER}),
}


def allowed_roles(cap):
    return CAPABILITIES[cap][1]


def user_can(user, cap):
    return bool(user and user.is_authenticated and user.has_role(*allowed_roles(cap)))


def _deny(request, cap):
    # Ghi nhật ký mọi lần bị từ chối (AC-111) rồi trả 403.
    from apps.audit.models import Action
    from apps.audit.services import record

    reason = f"{cap}: {CAPABILITIES[cap][0]}"
    log = record(Action.ACCESS_DENIED, request=request, object_type="capability", reason=reason)
    error = PermissionDenied()
    # Với ATOMIC_REQUESTS, giao dịch của yêu cầu bị hủy khi ném lỗi nên dòng nhật ký trên mất theo;
    # DeniedAccessLogMiddleware ghi lại sau khi giao dịch đã đóng.
    error.lam_denied = {"log_id": getattr(log, "pk", None), "reason": reason}
    raise error


class DeniedAccessLogMiddleware:
    """Bảo đảm lần bị từ chối quyền luôn còn trong nhật ký (AC-111), kể cả khi giao dịch yêu cầu bị hủy."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        info = getattr(exception, "lam_denied", None)
        if info is None:
            return None
        from apps.audit.models import Action, AuditLog
        from apps.audit.services import record

        if not AuditLog.objects.filter(pk=info["log_id"]).exists():
            record(Action.ACCESS_DENIED, request=request, object_type="capability", reason=info["reason"])
        return None


def capability_required(cap):
    if cap not in CAPABILITIES:
        raise ValueError(f"Quyền không tồn tại: {cap}")

    def decorator(view_func):
        @wraps(view_func)
        @login_required
        def wrapper(request, *args, **kwargs):
            if not user_can(request.user, cap):
                _deny(request, cap)
            return view_func(request, *args, **kwargs)

        wrapper.required_capability = cap
        return wrapper

    return decorator


class CapabilityRequiredMixin(LoginRequiredMixin):
    capability = None

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and not user_can(request.user, self.capability):
            _deny(request, self.capability)
        return super().dispatch(request, *args, **kwargs)


class OwnerOnlyAdminMixin:
    """Trang quản trị dữ liệu nền chỉ dành cho Chủ quán (dòng cuối Bảng 5.3)."""

    owner_capability = Cap.MASTER_DATA

    def _owner(self, request):
        return user_can(request.user, self.owner_capability)

    def has_module_permission(self, request):
        return self._owner(request)

    def has_view_permission(self, request, obj=None):
        return self._owner(request)

    def has_add_permission(self, request, *args):
        return self._owner(request)

    def has_change_permission(self, request, obj=None):
        return self._owner(request)

    def has_delete_permission(self, request, obj=None):
        return self._owner(request)


class OwnerOnlyInlineMixin(OwnerOnlyAdminMixin):
    """Bảng con trong trang quản trị: cùng quyền với trang cha, không dùng quyền model mặc định."""
