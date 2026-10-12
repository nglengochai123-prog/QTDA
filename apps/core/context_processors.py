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
    desktop_only = {"bar", "data", "log", "cashier", "status", "exceptions", "cases", "params", "backup", "workload",
                    "revenue", "control_report", "materials", "dashboard", "lookup", "ledger"}
    # Nhóm điều hướng theo nghiệp vụ (DESIGN.md: bố cục quản trị); trên điện thoại chỉ hiện tối đa 5 mục.
    groups = [
        (None, [("home", "Trang chủ", reverse("core:home"), None),
                ("dashboard", "Bảng điều khiển", reverse("reports:dashboard"), Cap.VIEW_DASHBOARD),
                ("alerts", "Cảnh báo", reverse("control:alerts"), Cap.HANDLE_ALERTS)]),
        ("Bán hàng", [
            ("order", "Tạo đơn", reverse("orders:create"), Cap.ORDER_CREATE),
            ("ready", "Món sẵn sàng", reverse("orders:ready"), Cap.ORDER_CREATE),
            ("open", "Đơn đang mở", reverse("orders:open_orders"), Cap.ORDER_CREATE),
            ("lookup", "Tra cứu đơn", reverse("orders:lookup"), Cap.VIEW_DASHBOARD),
            ("approve", "Duyệt", reverse("orders:approvals"), Cap.ORDER_ADJUST_APPROVE),
            ("bar", "Quầy pha chế", reverse("orders:bar"), Cap.BAR_PREPARE),
            ("cashier", "Thu ngân", reverse("orders:cashier"), Cap.PAYMENT),
            ("backup", "Phiếu dự phòng", reverse("orders:backup_slips"), Cap.BACKUP_TICKETS)]),
        ("Ca và nhân sự", [
            ("shift", "Ca của tôi", reverse("shifts:my_shift"), Cap.CASH_FUND),
            ("attendance", "Chấm công", reverse("staff:attendance"),
             Cap.TIMEKEEPING if user_can(user, Cap.TIMEKEEPING) else Cap.TIMEKEEPING_ADJUST),
            ("status", "Tình trạng ca", reverse("shifts:status"), Cap.VIEW_DASHBOARD),
            ("workload", "Tải và thời gian chờ", reverse("staff:workload"), Cap.VIEW_WORKLOAD)]),
        ("Kho", [("stock", "Tồn kho", reverse("inventory:stock"), Cap.STOCK_OPERATIONS),
                 ("ledger", "Sổ kho", reverse("inventory:ledger"), Cap.VIEW_DASHBOARD)]),
        ("Kiểm soát", [
            ("exceptions", "Ngoại lệ", reverse("control:exceptions"), Cap.EXCEPTION_REVIEW),
            ("cases", "Vụ việc tổn thất", reverse("control:cases"), Cap.EXCEPTION_REVIEW)]),
        ("Báo cáo", [
            ("revenue", "Doanh thu", reverse("reports:revenue"), Cap.VIEW_DASHBOARD),
            ("control_report", "Kiểm soát doanh thu", reverse("reports:revenue_control"), Cap.EXCEPTION_REVIEW),
            ("materials", "Nguyên vật liệu", reverse("reports:materials"), Cap.VIEW_DASHBOARD)]),
        ("Quản trị", [
            ("params", "Tham số", reverse("control:parameters"), Cap.MASTER_DATA),
            ("data", "Dữ liệu nền", reverse("admin:index"), Cap.MASTER_DATA),
            ("log", "Nhật ký", reverse("admin:audit_auditlog_changelist"), Cap.AUDIT_LOG)]),
    ]
    items = [(key, label, url, cap, group) for group, entries in groups for key, label, url, cap in entries]
    path = request.path
    nav = [{"key": key, "label": label, "url": url, "active": False, "desktop_only": key in desktop_only, "group": group}
           for key, label, url, cap, group in items if cap is None or user_can(user, cap)]
    last = object()
    for item in nav:
        item["group_start"] = item["group"] if item["group"] != last and item["group"] else ""
        last = item["group"]
    # Thanh dưới điện thoại giữ tối đa 5 mục theo thứ tự ưu tiên; các mục còn lại xem trên máy tính.
    priority = ["home", "order", "approve", "shift", "alerts", "attendance", "stock", "open", "ready"]
    mobile = [key for key in priority if any(i["key"] == key and not i["desktop_only"] for i in nav)][:5]
    for item in nav:
        item["desktop_only"] = item["key"] not in mobile
    # Mục khớp đường dẫn dài nhất là mục đang mở.
    matches = [item for item in nav if path == item["url"] or (item["url"] != "/" and path.startswith(item["url"]))]
    if matches:
        max(matches, key=lambda item: len(item["url"]))["active"] = True
    can_order = user_can(user, Cap.ORDER_CREATE)
    # Bảng điều khiển không nằm ở thanh dưới điện thoại; Trang chủ có lối vào (AC-100: Chủ quán mở trên điện thoại).
    return {"NAV_ITEMS": nav, "APPROVALS_COUNT_URL": reverse("orders:approvals_count"),
            "QUICK_REPORT_COUNT_URL": reverse("inventory:quick_report_count") if user_can(user, Cap.VIEW_WORKLOAD) else "",
            "STOCK_URL": reverse("inventory:stock"),
            "APPROVALS_URL": reverse("orders:approvals"), "READY_COUNT_URL": reverse("orders:ready_count") if can_order else "",
            "READY_URL": reverse("orders:ready") if can_order else ""}
