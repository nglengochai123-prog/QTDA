from django.conf import settings
from django.urls import reverse

from apps.accounts.permissions import Cap, user_can


def site(request):
    return {"STORE_NAME": settings.LAM_STORE_NAME}


def navigation(request):
    """Mục điều hướng theo quyền. Chỉ liệt kê màn hình đã có; màn hình mới thêm vào đây kèm quyền."""
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {}
    # Mục đánh dấu desktop chỉ hiện trên máy tính (thanh dưới điện thoại giữ tối đa 4 mục).
    desktop_only = {"bar", "data", "log", "cashier", "status", "exceptions", "cases", "params"}
    items = [("home", "Trang chủ", reverse("core:home"), None)]
    items += [
        ("order", "Tạo đơn", reverse("orders:create"), Cap.ORDER_CREATE),
        ("ready", "Món sẵn sàng", reverse("orders:ready"), Cap.ORDER_CREATE),
        ("open", "Đơn đang mở", reverse("orders:open_orders"), Cap.ORDER_CREATE),
        ("approve", "Duyệt", reverse("orders:approvals"), Cap.ORDER_ADJUST_APPROVE),
        ("cashier", "Thu ngân", reverse("orders:cashier"), Cap.PAYMENT),
        ("shift", "Ca của tôi", reverse("shifts:my_shift"), Cap.CASH_FUND),
        ("status", "Tình trạng ca", reverse("shifts:status"), Cap.VIEW_DASHBOARD),
        ("exceptions", "Ngoại lệ", reverse("control:exceptions"), Cap.EXCEPTION_REVIEW),
        ("cases", "Vụ việc tổn thất", reverse("control:cases"), Cap.EXCEPTION_REVIEW),
        ("params", "Tham số", reverse("control:parameters"), Cap.MASTER_DATA),
        ("bar", "Quầy pha chế", reverse("orders:bar"), Cap.BAR_PREPARE),
        ("stock", "Tồn kho", reverse("inventory:stock"), Cap.STOCK_OPERATIONS),
        ("data", "Dữ liệu nền", reverse("admin:index"), Cap.MASTER_DATA),
        ("log", "Nhật ký", reverse("admin:audit_auditlog_changelist"), Cap.AUDIT_LOG),
    ]
    path = request.path
    nav = [{"key": key, "label": label, "url": url, "active": False, "desktop_only": key in desktop_only}
           for key, label, url, cap in items if cap is None or user_can(user, cap)]
    # Thanh dưới điện thoại giữ tối đa 5 mục theo thứ tự ưu tiên; các mục còn lại xem trên máy tính.
    priority = ["home", "order", "approve", "shift", "stock", "open", "ready"]
    mobile = [key for key in priority if any(i["key"] == key and not i["desktop_only"] for i in nav)][:5]
    for item in nav:
        item["desktop_only"] = item["key"] not in mobile
    # Mục khớp đường dẫn dài nhất là mục đang mở.
    matches = [item for item in nav if path == item["url"] or (item["url"] != "/" and path.startswith(item["url"]))]
    if matches:
        max(matches, key=lambda item: len(item["url"]))["active"] = True
    can_order = user_can(user, Cap.ORDER_CREATE)
    return {"NAV_ITEMS": nav, "APPROVALS_COUNT_URL": reverse("orders:approvals_count"),
            "QUICK_REPORT_COUNT_URL": reverse("inventory:quick_report_count") if user_can(user, Cap.VIEW_WORKLOAD) else "",
            "STOCK_URL": reverse("inventory:stock"),
            "APPROVALS_URL": reverse("orders:approvals"), "READY_COUNT_URL": reverse("orders:ready_count") if can_order else "",
            "READY_URL": reverse("orders:ready") if can_order else ""}
