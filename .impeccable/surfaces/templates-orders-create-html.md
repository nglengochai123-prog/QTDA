---
version: 1
slug: "templates-orders-create-html"
primary_target: "templates/orders/create.html"
related_targets: ["templates/orders/bar.html","templates/inventory/stock.html"]
---

# Surface: Tạo đơn (điện thoại phục vụ) và Quầy pha chế (máy tính quầy)

Scope: templates/orders/create.html, static/js/order.js, templates/orders/bar.html, templates/orders/_bar_queue.html, static/js/bar.js, templates/inventory/stock.html. Mode: Operate. Thừa hưởng thế giới đã có trong DESIGN.md (vở ô ly, mực tím, lề đỏ); không đổi hệ thống.
Audience/job: phục vụ tạo đơn 2 món dưới 20 giây bằng một tay trên điện thoại; pha chế đọc hàng chờ từ xa và bấm xong từng ly trên máy quầy 1366x768.
Constraints: nút ≥ 48px; trạng thái không chỉ bằng màu; đơn khóa sau khi gửi; gửi lại an toàn bằng mã nghiệp vụ; thiếu nguyên liệu thì báo rõ nguyên liệu nào và còn bao nhiêu.

## Direction contract

THESIS: Phiếu order là giỏ món: tờ phiếu có lề đỏ luôn ở trên, thực đơn ở dưới mở tại chỗ; quầy đọc từng phiếu theo mã đơn. Từ chối lưới ô món kiểu POS và hộp thoại bật lên.

OWN-WORLD: Giữ nguyên DESIGN.md: giấy trắng, mực tím là màu hành động duy nhất, lề đỏ 1px trên phiếu, ghi chú pha chế viết bằng mực đỏ, số dạng bảng.

STORY: Phục vụ chọn bàn, chạm món, chọn cỡ và tùy chọn, thêm vào phiếu, bấm Gửi pha chế ở vùng ngón cái; quầy thấy phiếu mới sáng tím, bấm Xong từng ly, kho trừ đúng một lần.

FIRST VIEWPORT: Điện thoại: phiếu order (tiêu đề, bàn, các dòng món) trên cùng; nhóm món và danh sách món bên dưới; nút Gửi pha chế toàn chiều ngang cố định trên thanh điều hướng dưới. Máy quầy: tổng số ly chờ, lưới phiếu theo thứ tự đến; mã đơn cỡ lớn, bàn, thời gian chờ; mỗi dòng có số ly lớn và nút Xong.

FORM: Phiếu order làm giỏ (vị trí 5 trong danh sách của mình), seed 27d305fc; phiếu mới sáng đến khi được chú ý (từ gate board); mã đơn là danh tính chính.

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
