# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

Python/Django theo BRD (Báo cáo Sprint 1, Bảng 3.8): Django auth và Django admin cho dữ liệu nền; Bootstrap cho bố cục đáp ứng; HTMX cho cập nhật từng phần màn hình; manifest và service worker để cài lên màn hình chính (PWA); Web Push qua pywebpush. Chạy thử bằng SQLite trên máy cá nhân, triển khai thật bằng PostgreSQL. Một bộ mã nguồn cho máy tính và điện thoại, không phát hành lên kho ứng dụng.

## Users

LAM Coffee là quán cà phê phục vụ tại chỗ ở 136 Nguyễn Đình Tựu, An Khê, Đà Nẵng; khách chủ yếu là người trung niên và gia đình có trẻ nhỏ. Người dùng hệ thống là nội bộ quán, gồm 5 vai trò:

- **Phục vụ**: chủ yếu dùng điện thoại cá nhân. Tạo đơn tại bàn, gửi yêu cầu điều chỉnh đơn, báo nhanh nguyên liệu, chấm công. Thao tác khi đang đứng, đang di chuyển, một tay, giờ cao điểm 20 đến 25 đơn mỗi giờ.
- **Pha chế**: chủ yếu dùng máy tính tại quầy. Nhận món theo mã đơn, đánh dấu Đã pha chế (trừ kho), in phiếu pha chế, nhập hàng, kiểm kê, ghi hao hụt.
- **Thu ngân**: chủ yếu dùng máy tính tại quầy. Thanh toán tiền mặt và chuyển khoản theo bàn, quỹ tiền ca, chi và nộp giữa ca, kết ca.
- **Quản lý ca**: dùng điện thoại. Phê duyệt điều chỉnh đơn, xử lý cảnh báo được giao, xác nhận tiền, kết ca, xem tải và thời gian chờ.
- **Chủ quán**: dùng cả máy tính và điện thoại. Cấu hình dữ liệu nền (món, định mức, nguyên vật liệu, tham số, phân quyền), xem bảng điều khiển và báo cáo, xem xét ngoại lệ, vụ việc tổn thất, đặt hàng.

## Product Purpose

LAM Coffee System thay KiotViet và các báo cáo qua Zalo bằng một hệ thống vận hành riêng của quán. Ba vấn đề gốc cần giải quyết:

1. Thất thoát doanh thu 3 đến 4,5 triệu đồng mỗi tháng do chuyển hoặc sửa đơn sau khi đã pha chế. Mục tiêu dưới 200.000 đồng mỗi tháng.
2. Thiếu nguyên liệu không phát hiện kịp, 30 đến 50 trường hợp mỗi tháng. Mục tiêu không quá 1 trường hợp mỗi tháng.
3. Bố trí nhân sự không theo tải; 50% đến 60% khung giờ đáp ứng. Mục tiêu 90% đến 95%.

Thành công nghĩa là mọi đơn đi qua hệ thống, mọi thay đổi sau khi gửi pha chế đều có phê duyệt và vết, kho tự trừ theo định mức, và Chủ quán đọc được tình hình mà không phải tự tổng hợp.

## Positioning

Đơn bị khóa ngay khi gửi pha chế; mọi thay đổi sau đó phải qua yêu cầu điều chỉnh có phê duyệt và chuyển cấp. Món chỉ được pha khi có mã đơn hoặc phiếu dự phòng đánh số. Món Đã pha chế trừ kho một lần theo định mức đã lưu, và quỹ tiền ca được đối soát theo công thức. Đây là cơ chế kiểm soát xuyên suốt order, pha chế, phục vụ, thanh toán mà phần mềm bán lẻ chung như KiotViet không có.

## Operating Context

- Quán đông vào cuối tuần, mạng Wi-Fi nội bộ có thể chập chờn; phải có quy trình bán hàng dự phòng bằng phiếu đánh số và nhập bù (NFR-16).
- Máy tính quầy và máy in phiếu có sẵn tại quán; phiếu pha chế in qua trình duyệt.
- Mỗi thay đổi dữ liệu có mã nghiệp vụ duy nhất, gửi lại không tạo bản ghi trùng (NFR-04).
- Mọi cảnh báo có người xử lý chính, thời hạn và chuyển cấp (Bảng 5.4).
- Nhật ký thao tác chỉ thêm mới, không sửa, không xóa (FR-61, NFR-08).
- Tài liệu nguồn: KE_HOACH.md, Business Case, Project Charter, Báo cáo Sprint 1 (BRD với FR, NFR, BRU, Bảng 5.3 phân quyền, Bảng 9.1 sprint).

## Capabilities and Constraints

- Phạm vi trước Go-Live: 39 yêu cầu chức năng mức Must (Bảng 8.3), chia theo Sprint 1 đến 3 trong KE_HOACH.md. Giai đoạn 2 và 3 chỉ làm sau khi vận hành ổn định.
- Phân quyền kiểm tra tại máy chủ; lương, chi phí, lãi lỗ chỉ trả về cho Chủ quán (NFR-07).
- Hiệu năng: đơn hiện ở quầy dưới 3 giây; yêu cầu điều chỉnh đến người duyệt dưới 5 giây (NFR-02).
- Thao tác: tạo đơn 2 món dưới 20 giây; yêu cầu điều chỉnh, báo nhanh nguyên liệu không quá 3 thao tác; báo cáo cuối ca dưới 3 phút (NFR-10).
- Tương thích: Chrome Android 10 trở lên, Safari iOS 16.4 trở lên, cài lên màn hình chính; máy quầy Chrome hoặc Edge (NFR-11).
- Hiển thị đủ trên điện thoại 5 đến 10 inch không cuộn ngang; máy tính từ 1366 x 768 (NFR-15).
- Bản địa hóa: 100% tiếng Việt; tiền tệ đồng, dấu chấm phân cách nghìn; giờ UTC+7 (NFR-12).
- Bảo mật: mật khẩu tối thiểu 8 ký tự, tự đăng xuất sau 15 phút không thao tác trên máy dùng chung, HTTPS (NFR-06).
- Không thu thập dữ liệu cá nhân của khách hàng; dữ liệu nhân viên theo Luật 91/2025/QH15 (NFR-13).
- Bảng dữ liệu chính có mã cửa hàng để mở rộng nhiều điểm bán (NFR-18).

## Brand Commitments

Chưa có logo, màu sắc hay font bắt buộc. Mọi định hướng hình ảnh dùng trong giai đoạn này là **tạm thời**, được đề xuất qua Impeccable và ghi trong DESIGN.md, có thể thay khi quán cung cấp nhận diện chính thức. Tên dùng trên giao diện: "LAM Coffee".

## Evidence on Hand

Số liệu thật từ khảo sát: 130 đơn mỗi ngày đầu tuần, 150 đến 160 đơn cuối tuần; doanh thu 5 đến 8 triệu đồng mỗi ngày; cao điểm 20 đến 25 đơn mỗi giờ với 4 đến 5 nhân viên. Chưa có ảnh quán, ảnh món, logo hay danh mục món chính thức; không được tự bịa danh mục, giá hay hình ảnh như thể là của quán.

## Product Principles

1. Tốc độ phục vụ trước hết: mỗi màn hình của nhân viên phải xong việc trong ít thao tác nhất, không để hệ thống làm chậm giờ cao điểm.
2. Kiểm soát không cần tự giác: quy tắc được thực thi bởi hệ thống (khóa đơn, phê duyệt, trừ kho), không dựa vào trí nhớ hay thiện chí.
3. Mỗi vai trò chỉ thấy việc của mình: giao diện theo vai trò và thiết bị chính, không phơi bày chức năng không có quyền.
4. Số liệu khớp nguồn và giải thích được: mọi cảnh báo, chênh lệch đều chỉ ra căn cứ.
5. Không mất dữ liệu khi mất mạng: luôn biết trạng thái kết nối và có đường dự phòng.

## Accessibility & Inclusion

Ưu tiên chữ dễ đọc, nút dễ chạm trên điện thoại, tương phản rõ và ít thao tác. Nhân viên thao tác nhanh trong môi trường quầy đông, ánh sáng thay đổi, thường dùng một tay; trạng thái quan trọng (đơn đã khóa, mất kết nối, cảnh báo khẩn) không được chỉ truyền đạt bằng màu.
