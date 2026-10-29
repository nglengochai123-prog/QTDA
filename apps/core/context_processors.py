from django.conf import settings
from django.urls import reverse

from apps.accounts.permissions import Cap, user_can


def site(request):
    return {"STORE_NAME": settings.LAM_STORE_NAME, "FORECAST_SIMULATED": settings.LAM_FORECAST_INCLUDE_SIMULATED}


# Biểu tượng, nhãn ngắn trên thanh trên và màu ô biểu tượng (trang chủ) của từng phân hệ.
GROUP_ICONS = {"Tổng quan": "home", "Bán hàng": "order", "Ca và nhân sự": "shift", "Kho": "stock", "Dự báo": "forecast",
               "Kiểm soát": "control_report", "Báo cáo": "revenue", "Quản trị": "params"}
GROUP_SHORT = {"Tổng quan": "Trang chủ", "Ca và nhân sự": "Ca, nhân sự"}
GROUP_TONES = {"Tổng quan": "blue", "Bán hàng": "orange", "Ca và nhân sự": "green", "Kho": "teal", "Dự báo": "indigo",
               "Kiểm soát": "red", "Báo cáo": "pink", "Quản trị": "gray"}

# Mục không có biểu tượng cùng tên dùng biểu tượng ở đây (templates/partials/icons.html).
ICONS = {"fc_overview": "forecast", "fc_plans": "po", "fc_prior": "bulb", "fc_season": "sun", "fc_history": "upload",
         "md_ca": "shift", "md_nhan-vien": "people", "md_mon": "brand", "md_nhom-mon": "tag", "md_tuy-chon": "sliders",
         "md_ban": "table", "md_nguyen-lieu": "stock", "md_dinh-muc": "beaker", "md_nha-cung-cap": "truck", "md_ly-do": "note",
         "semi": "beaker", "md_ban-thanh-pham": "beaker"}

# Một dòng mô tả cho thẻ chức năng ở trang chủ: nói chức năng dùng để làm gì, không nói cách tính.
DESCRIPTIONS = {
    "home": "Việc chờ xử lý và lối vào mọi chức năng",
    "dashboard": "Doanh thu, kho và kiểm soát trong một trang",
    "alerts": "Cảnh báo cần bạn xử lý, kèm thời hạn",
    "overview": "Bàn có khách, món đang pha, chờ duyệt, chờ thu tiền",
    "order": "Chọn bàn, thêm món và gửi pha chế",
    "ready": "Món đã pha xong, chờ mang ra bàn",
    "open": "Đơn chưa thanh toán; hủy, đổi món, chuyển bàn",
    "lookup": "Tìm đơn theo mã, bàn hoặc thời gian",
    "approve": "Duyệt yêu cầu hủy món, đổi món, chuyển bàn",
    "bar": "Món cần pha theo thứ tự gửi",
    "cashier": "Thu tiền theo bàn, tiền mặt hoặc chuyển khoản",
    "backup": "Nhập bù phiếu giấy khi mất kết nối",
    "shift": "Quỹ đầu ca, thu chi và báo cáo cuối ca",
    "attendance": "Chấm công vào, ra và sửa chấm công",
    "status": "Ca đang mở, chênh lệch tiền và báo cáo ca",
    "schedule": "Lập lịch tuần và xếp người theo đăng ký",
    "register": "Đăng ký các ca có thể làm tuần sau",
    "my_schedule": "Các ca đã được xếp cho bạn",
    "workload": "Số ly theo giờ, thời gian chờ, người có mặt",
    "stock": "Tồn từng nguyên liệu và còn đủ dùng bao lâu",
    "lots": "Từng lô hàng, hạn dùng và thứ tự lấy",
    "pick": "Lô nên lấy ra quầy hôm nay",
    "receipt": "Ghi hàng nhận từ nhà cung cấp",
    "count": "Đếm tồn thực tế và ghi chênh lệch",
    "waste": "Ghi hàng hư, hết hạn, đổ vỡ",
    "semi": "Ghi mẻ cà phê cốt, nước đường, foam đã làm",
    "po": "Đơn đặt nhà cung cấp và hàng đang về",
    "payables": "Công nợ nhà cung cấp và thanh toán",
    "ledger": "Mọi lần nhập, xuất, điều chỉnh kho",
    "stock_report": "Giá trị tồn, lịch hết hạn, tuổi hàng",
    "fc_overview": "Số ly dự kiến bán những ngày tới",
    "fc_plans": "Nguyên liệu cần mua và ngày đặt chậm nhất",
    "fc_prior": "Ước tính của Chủ quán cho món mới",
    "fc_season": "Tăng giảm dự kiến theo mùa, lễ, sự kiện",
    "fc_history": "Nhập số bán trước khi dùng hệ thống",
    "exceptions": "Sự việc bất thường cần xem xét",
    "cases": "Theo dõi khoản thiếu đến khi kết luận",
    "revenue": "Doanh thu theo ngày, món, giờ, cách trả",
    "control_report": "Tiền thiếu, đã xác minh và đã thu hồi",
    "materials": "Nhập, xuất, tồn và hao hụt theo kỳ",
    "params": "Ngưỡng cảnh báo, thời hạn, giờ mở cửa",
    "md_ca": "Ca bán hàng đang mở và đã kết",
    "md_nhan-vien": "Hồ sơ, vai trò và lương giờ",
    "md_mon": "Thực đơn, kích cỡ và giá bán",
    "md_nhom-mon": "Nhóm món trên màn tạo đơn",
    "md_tuy-chon": "Đường, đá và topping",
    "md_ban": "Danh sách bàn của quán",
    "md_nguyen-lieu": "Đơn vị, quy cách, hạn dùng, nhà cung cấp",
    "md_dinh-muc": "Lượng nguyên liệu cho mỗi ly",
    "md_ban-thanh-pham": "Nguyên liệu cho một mẻ và lượng thu được",
    "md_nha-cung-cap": "Liên hệ và thời gian giao hàng",
    "md_ly-do": "Lý do dùng khi hủy, đổi món, chuyển bàn",
    "log": "Ai đã làm gì, lúc nào",
}


def navigation(request):
    """Mục điều hướng theo quyền. Chỉ liệt kê màn hình đã có; màn hình mới thêm vào đây kèm quyền."""
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {}
    # Mục đánh dấu desktop chỉ hiện trên máy tính (thanh dưới điện thoại giữ tối đa 4 mục).
    desktop_only = {"bar", "data", "log", "cashier", "status", "exceptions", "cases", "params", "backup", "workload",
                    "revenue", "control_report", "materials", "dashboard", "lookup", "ledger", "lots", "pick", "receipt",
                    "count", "waste", "semi", "po", "payables", "stock_report"} | {
        "md_ca", "md_nhan-vien", "md_mon", "md_nhom-mon", "md_tuy-chon", "md_ban", "md_nguyen-lieu", "md_dinh-muc",
        "md_ban-thanh-pham", "md_nha-cung-cap", "md_ly-do", "schedule", "fc_overview", "fc_plans", "fc_prior", "fc_season", "fc_history"}
    # Nhóm điều hướng theo nghiệp vụ (DESIGN.md: bố cục quản trị); trên điện thoại chỉ hiện tối đa 5 mục.
    groups = [
        (None, [("home", "Trang chủ", reverse("core:home"), None),
                ("dashboard", "Bảng điều khiển", reverse("reports:dashboard"), Cap.VIEW_DASHBOARD),
                ("alerts", "Cảnh báo", reverse("control:alerts"), Cap.HANDLE_ALERTS)]),
        ("Bán hàng", [
            ("overview", "Tổng quan ca", reverse("orders:overview"), Cap.ORDER_CREATE),
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
            ("schedule", "Lịch làm tuần", reverse("schedule:board"), Cap.SCHEDULE_MANAGE),
            ("register", "Đăng ký ca", reverse("schedule:register"), Cap.SHIFT_REGISTER),
            ("my_schedule", "Lịch của tôi", reverse("schedule:mine"), Cap.SHIFT_REGISTER),
            ("workload", "Tải và thời gian chờ", reverse("staff:workload"), Cap.VIEW_WORKLOAD)]),
        ("Kho", [("stock", "Tồn kho", reverse("inventory:stock"), Cap.STOCK_OPERATIONS),
                 ("lots", "Lô hàng", reverse("inventory:lots"), Cap.STOCK_OPERATIONS),
                 ("pick", "Phiếu lấy hàng", reverse("inventory:pick_list"), Cap.STOCK_OPERATIONS),
                 ("receipt", "Phiếu nhập", reverse("inventory:receipt"), Cap.STOCK_OPERATIONS),
                 ("count", "Kiểm kê", reverse("inventory:count"), Cap.STOCK_OPERATIONS),
                 ("waste", "Hao hụt", reverse("inventory:waste"), Cap.STOCK_OPERATIONS),
                 ("semi", "Làm bán thành phẩm", reverse("inventory:semi"), Cap.STOCK_OPERATIONS),
                 ("po", "Đặt hàng", reverse("inventory:purchase_orders"), Cap.STOCK_CONFIRM_ORDERING),
                 ("payables", "Phải trả", reverse("inventory:payables"), Cap.STOCK_CONFIRM_ORDERING),
                 ("ledger", "Sổ kho", reverse("inventory:ledger"), Cap.VIEW_DASHBOARD),
                 ("stock_report", "Báo cáo kho", reverse("reports:inventory"), Cap.VIEW_DASHBOARD)]),
        ("Dự báo", [
            ("fc_overview", "Dự báo nhu cầu", reverse("forecast:overview"), Cap.FORECASTS),
            ("fc_plans", "Kế hoạch mua", reverse("forecast:plans"), Cap.FORECASTS),
            ("fc_prior", "Nhận định Chủ quán", reverse("masterdata:list", args=["nhan-dinh"]), Cap.FORECASTS),
            ("fc_season", "Điều chỉnh theo mùa", reverse("masterdata:list", args=["dieu-chinh-mua"]), Cap.FORECASTS),
            ("fc_history", "Lịch sử bán", reverse("forecast:history"), Cap.FORECASTS)]),
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
            ("md_ban-thanh-pham", "Định mức bán thành phẩm", reverse("masterdata:list", args=["ban-thanh-pham"]),
             Cap.MASTER_INVENTORY),
            ("md_nha-cung-cap", "Nhà cung cấp", reverse("masterdata:list", args=["nha-cung-cap"]), Cap.MASTER_INVENTORY),
            ("md_ly-do", "Lý do điều chỉnh", reverse("masterdata:list", args=["ly-do"]), Cap.MASTER_DATA),
            ("log", "Nhật ký", reverse("masterdata:audit_log"), Cap.AUDIT_LOG)]),
    ]
    items = [(key, label, url, cap, group) for group, entries in groups for key, label, url, cap in entries]
    path = request.path
    nav = [{"key": key, "label": label, "url": url, "active": False, "desktop_only": key in desktop_only, "group": group,
            "description": DESCRIPTIONS.get(key, ""), "tone": GROUP_TONES[group or "Tổng quan"], "icon": ICONS.get(key, key)}
           for key, label, url, cap, group in items if cap is None or user_can(user, cap)]
    last = object()
    for item in nav:
        item["group_start"] = item["group"] if item["group"] != last and item["group"] else ""
        last = item["group"]
    # Thanh dưới điện thoại giữ tối đa 5 mục theo thứ tự ưu tiên; các mục còn lại xem trên máy tính.
    priority = ["home", "order", "approve", "shift", "register", "alerts", "attendance", "stock", "open", "ready"]
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
    # Thanh trên: mỗi nhóm nghiệp vụ là một thẻ; thanh bên trái (điện thoại: thanh phụ) liệt kê các mục của nhóm đang mở.
    nav_groups = []
    for item in nav:
        label = item["group"] or "Tổng quan"
        if not nav_groups or nav_groups[-1]["label"] != label:
            nav_groups.append({"label": label, "url": item["url"], "items": [], "active": False,
                               "icon": GROUP_ICONS.get(label, "home"), "short": GROUP_SHORT.get(label, label),
                               "tone": GROUP_TONES.get(label, "gray")})
        nav_groups[-1]["items"].append(item)
        nav_groups[-1]["active"] = nav_groups[-1]["active"] or item["active"]
    active_group = next((g for g in nav_groups if g["active"]), None)
    can_order = user_can(user, Cap.ORDER_CREATE)
    can_approve = user_can(user, Cap.ORDER_ADJUST_APPROVE)
    # Bảng điều khiển không nằm ở thanh dưới điện thoại; Trang chủ có lối vào (AC-100: Chủ quán mở trên điện thoại).
    header = {
        "alerts": reverse("control:alerts") if user_can(user, Cap.HANDLE_ALERTS) else "",
        "approvals": reverse("orders:approvals") if can_approve else "",
        "settings": reverse("control:parameters") if user_can(user, Cap.MASTER_DATA) else "",
        "initial": user.initial,
    }
    return {"NAV_ITEMS": nav, "HEADER": header, "NAV_GROUPS": nav_groups, "NAV_ACTIVE_GROUP": active_group,
            "NAV_SIDE_GROUP": active_group or (nav_groups[0] if nav_groups else None), "APPROVALS_COUNT_URL": reverse("orders:approvals_count") if can_approve else "",
            "QUICK_REPORT_COUNT_URL": reverse("inventory:quick_report_count") if user_can(user, Cap.VIEW_WORKLOAD) else "",
            "STOCK_URL": reverse("inventory:stock"),
            "APPROVALS_URL": reverse("orders:approvals") if can_approve else "", "READY_COUNT_URL": reverse("orders:ready_count") if can_order else "",
            "READY_URL": reverse("orders:ready") if can_order else ""}
