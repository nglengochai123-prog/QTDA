from django.conf import settings
from django.urls import reverse

from apps.accounts.permissions import Cap, user_can


def site(request):
    return {"STORE_NAME": settings.LAM_STORE_NAME}


# Biểu tượng và nhãn ngắn của từng phân hệ trên thanh biểu tượng bên trái (kiểu ServiceDesk Plus).
GROUP_ICONS = {"Tổng quan": "home", "Bán hàng": "order", "Ca và nhân sự": "shift", "Kho": "stock", "Dự báo": "forecast",
               "Kiểm soát": "control_report", "Báo cáo": "revenue", "Quản trị": "params"}
GROUP_SHORT = {"Tổng quan": "Trang chủ", "Ca và nhân sự": "Ca, nhân sự"}


def navigation(request):
    """Mục điều hướng theo quyền. Chỉ liệt kê màn hình đã có; màn hình mới thêm vào đây kèm quyền."""
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {}
    # Mục đánh dấu desktop chỉ hiện trên máy tính (thanh dưới điện thoại giữ tối đa 4 mục).
    desktop_only = {"bar", "data", "log", "cashier", "status", "exceptions", "cases", "params", "backup", "workload",
                    "revenue", "control_report", "materials", "dashboard", "lookup", "ledger"} | {
        "md_ca", "md_nhan-vien", "md_mon", "md_nhom-mon", "md_tuy-chon", "md_ban", "md_nguyen-lieu", "md_dinh-muc",
        "md_nha-cung-cap", "md_ly-do", "fc_overview", "fc_ordering", "fc_eval", "fc_prior"}
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
        ("Dự báo", [
            ("fc_overview", "Dự báo nhu cầu", reverse("forecast:overview"), Cap.FORECASTS),
            ("fc_ordering", "Đặt hàng đề xuất", reverse("forecast:ordering"), Cap.FORECASTS),
            ("fc_eval", "Đánh giá dự báo", reverse("forecast:evaluation"), Cap.FORECASTS),
            ("fc_prior", "Nhận định Chủ quán", reverse("masterdata:list", args=["nhan-dinh"]), Cap.FORECASTS)]),
        ("Kiểm soát", [
            ("exceptions", "Ngoại lệ", reverse("control:exceptions"), Cap.EXCEPTION_REVIEW),
            ("cases", "Vụ việc tổn thất", reverse("control:cases"), Cap.EXCEPTION_REVIEW)]),
        ("Báo cáo", [
            ("revenue", "Doanh thu", reverse("reports:revenue"), Cap.VIEW_DASHBOARD),
            ("control_report", "Kiểm soát doanh thu", reverse("reports:revenue_control"), Cap.EXCEPTION_REVIEW),
            ("materials", "Nguyên vật liệu", reverse("reports:materials"), Cap.VIEW_DASHBOARD)]),
        ("Quản trị", [
            ("params", "Tham số", reverse("control:parameters"), Cap.MASTER_DATA),
            ("md_ca", "Ca làm việc", reverse("masterdata:list", args=["ca"]), Cap.MASTER_DATA),
            ("md_nhan-vien", "Nhân viên", reverse("masterdata:list", args=["nhan-vien"]), Cap.MASTER_DATA),
            ("md_mon", "Món và giá", reverse("masterdata:list", args=["mon"]), Cap.MASTER_DATA),
            ("md_nhom-mon", "Nhóm món", reverse("masterdata:list", args=["nhom-mon"]), Cap.MASTER_DATA),
            ("md_tuy-chon", "Tùy chọn", reverse("masterdata:list", args=["tuy-chon"]), Cap.MASTER_DATA),
            ("md_ban", "Bàn", reverse("masterdata:list", args=["ban"]), Cap.MASTER_DATA),
            ("md_nguyen-lieu", "Nguyên vật liệu", reverse("masterdata:list", args=["nguyen-lieu"]), Cap.MASTER_INVENTORY),
            ("md_dinh-muc", "Định mức", reverse("masterdata:list", args=["dinh-muc"]), Cap.MASTER_INVENTORY),
            ("md_nha-cung-cap", "Nhà cung cấp", reverse("masterdata:list", args=["nha-cung-cap"]), Cap.MASTER_INVENTORY),
            ("md_ly-do", "Lý do điều chỉnh", reverse("masterdata:list", args=["ly-do"]), Cap.MASTER_DATA),
            ("log", "Nhật ký", reverse("masterdata:audit_log"), Cap.AUDIT_LOG)]),
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
    mobile = [key for key in priority if any(i["key"] == key and not i["desktop_only"] for i in nav)][:4]
    for item in nav:
        item["desktop_only"] = item["key"] not in mobile
    # Mục khớp đường dẫn dài nhất là mục đang mở.
    matches = [item for item in nav if path == item["url"] or (item["url"] != "/" and path.startswith(item["url"]))]
    if not matches:
        # Trang chi tiết thuộc về danh sách của nó (ví dụ /don/12/ thuộc Tra cứu đơn) để thẻ phân hệ vẫn sáng.
        import re
        parents = {r"^/don/\d+/$": "lookup"}
        keys = [key for pattern, key in parents.items() if re.match(pattern, path)]
        matches = [item for item in nav if item["key"] in keys]
    if matches:
        max(matches, key=lambda item: len(item["url"]))["active"] = True
    # Thanh trên kiểu ServiceDesk Plus: mỗi nhóm nghiệp vụ là một thẻ, các mục của nhóm đang mở nằm ở thanh phụ.
    nav_groups = []
    for item in nav:
        label = item["group"] or "Tổng quan"
        if not nav_groups or nav_groups[-1]["label"] != label:
            nav_groups.append({"label": label, "url": item["url"], "items": [], "active": False,
                               "icon": GROUP_ICONS.get(label, "home"), "short": GROUP_SHORT.get(label, label)})
        nav_groups[-1]["items"].append(item)
        nav_groups[-1]["active"] = nav_groups[-1]["active"] or item["active"]
    active_group = next((g for g in nav_groups if g["active"]), None)
    can_order = user_can(user, Cap.ORDER_CREATE)
    # Bảng điều khiển không nằm ở thanh dưới điện thoại; Trang chủ có lối vào (AC-100: Chủ quán mở trên điện thoại).
    header = {
        "alerts": reverse("control:alerts") if user_can(user, Cap.HANDLE_ALERTS) else "",
        "approvals": reverse("orders:approvals") if user_can(user, Cap.ORDER_ADJUST_APPROVE) else "",
        "settings": reverse("control:parameters") if user_can(user, Cap.MASTER_DATA) else "",
        "initial": (user.given_name or user.username or "?")[:1].upper(),
    }
    return {"NAV_ITEMS": nav, "HEADER": header, "NAV_GROUPS": nav_groups, "NAV_ACTIVE_GROUP": active_group, "APPROVALS_COUNT_URL": reverse("orders:approvals_count"),
            "QUICK_REPORT_COUNT_URL": reverse("inventory:quick_report_count") if user_can(user, Cap.VIEW_WORKLOAD) else "",
            "STOCK_URL": reverse("inventory:stock"),
            "APPROVALS_URL": reverse("orders:approvals"), "READY_COUNT_URL": reverse("orders:ready_count") if can_order else "",
            "READY_URL": reverse("orders:ready") if can_order else ""}
