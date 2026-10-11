---
version: 1
slug: "templates-registration-login-html"
primary_target: "templates/registration/login.html"
related_targets: ["templates/base.html"]
---

# Surface: Đăng nhập và bố cục chung (app shell)

Scope: templates/registration/login.html, templates/base.html, static/css/app.css. Mode: Operate.
Audience: 5 vai trò nội bộ quán; phục vụ và quản lý ca trên điện thoại, pha chế và thu ngân trên máy tính quầy, chủ quán cả hai.
Job: vào đúng tài khoản nhanh; sau đó luôn biết mình là ai, vai trò gì, đang có mạng không, và đi tới việc của mình.
Constraints: tiếng Việt; chữ dễ đọc, nút ≥ 48px, tương phản rõ; trạng thái không chỉ bằng màu; không cuộn ngang 5–10 inch; 1366×768 trên máy quầy.
Định hướng là tạm thời cho đến khi quán có nhận diện chính thức.

## Direction contract

THESIS: Ứng dụng là cuốn vở ô ly của quán: mực tím trên giấy trắng, lề đỏ, và sửa sai bằng bút đỏ ngay bên cạnh chứ không tẩy xóa. Từ chối bố cục POS xám một màu nhấn.

OWN-WORLD: Giấy trắng lạnh, lưới ô ly tím nhạt chỉ ở nền trống; mực tím đậm cho thanh tiêu đề và nút chính; lề đỏ 1px chạy dọc cột nội dung; xanh lá chấm "Đạt", hổ phách cảnh báo. Một họ chữ hệ thống, số dạng bảng. Bút đỏ: giá trị cũ gạch đỏ, giá trị mới viết cạnh.

STORY: Nhân viên mở ứng dụng, nhận ra ngay "vở của quán", điền nhãn vở (tên đăng nhập, mật khẩu), vào trang của vai trò mình; mọi thay đổi về sau hiện như lời đính chính bút đỏ, nên tin được số liệu.

FIRST VIEWPORT: Đăng nhập: nhãn vở viền đôi tím ở giữa trên nền lưới ô ly, tên quán trên cùng, hai ô nhập lớn, nút "Đăng nhập" tím full-width trong vùng ngón cái. Shell: thanh tím trên cùng (tên quán, người dùng, vai trò, đăng xuất); máy tính có cột điều hướng trái, điện thoại có thanh điều hướng dưới; lề đỏ ngăn điều hướng với nội dung; dải "Mất kết nối" đỏ có biểu tượng và chữ.

FORM: Vở ô ly và mực tím học trò, vị trí 3 trong danh sách của mình; seed 9f40aaa3. Raises: mã đơn là danh tính chính (từ catalog sleeve); thay đổi giữ nổi bật đến khi được xác nhận (từ gate board); một màu hành động duy nhất (từ warm consumer app); hành động chính trong vùng ngón cái trên điện thoại (từ vertical feed).

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
