# Đề xuất sửa lỗi

Chỉ là đề xuất, chưa triển khai. Thứ tự theo rủi ro tiền và hàng trước, hiệu năng sau.

## 1. BUG-01: chặn giá 0 trên món đang bán (P1)

- Kiểm tra giá trong formset kích cỡ chứ không chỉ trong CSDL: trong form Món và giá (`apps/masterdata/resources.py`, resource `mon`), sau khi formset hợp lệ, nếu món ở trạng thái Đang bán thì từ chối khi có cỡ đang dùng với giá 0, báo lỗi ngay tại ô giá.
- Thêm một chốt ở tầng bán: `submit_order` từ chối dòng có đơn giá 0 nếu món không được khai báo là miễn phí, để chặn cả những đường sửa khác (admin, nhập file).
- Test: dùng lại `test_qa_md_03_price_zero_on_selling_item_via_form`.

## 2. BUG-02: đơn gửi lúc đang kết ca (P1)

Hai hướng, chọn một:

- **Khóa ca khi gắn đơn:** trong `submit_order`, sau khi xác định ca, khóa dòng ca (`select_for_update`) và kiểm tra lại trạng thái Đang mở; nếu ca vừa kết thì gắn đơn vào ca kế tiếp hoặc để trống như đơn gửi lúc chưa có ca (đã có luật xử lý loại này trong `close_blockers`).
- **Kiểm tra lại sau khi lưu:** trong `close_shift`, ngay trước khi lưu trạng thái, đếm lại đơn chưa thu của ca trong cùng giao dịch có khóa bảng đơn theo ca. Hướng này đơn giản hơn nhưng vẫn phụ thuộc mức cô lập của CSDL.
- Test: `test_qa_concurrency_pg.py::test_qa_conc_01` (chỉ chạy trên PostgreSQL).

## 3. BUG-03: báo cáo chậm (P2)

- Báo cáo Doanh thu: `receipts.entries` được gọi 3 lần cho cùng một kỳ; tính một lần và truyền xuống `insights`. Xem lại `_payment_entries` để gộp truy vấn dòng và phân bổ theo lô thay vì từng thanh toán.
- Bảng điều khiển: đọc tham số một lần mỗi yêu cầu (bộ đệm trong yêu cầu cho `params.get`), lấy chấm công một truy vấn cho cả ngày thay vì từng người, từng ca.
- Mục tiêu: dưới 3 giây với dữ liệu 3 tháng.

## 4. BUG-04: Thu ngân N+1 (P2)

`payments.bill()` gọi cho từng bàn; gom `prefetch_related` dòng đơn, yêu cầu chờ duyệt và phiếu dự phòng theo danh sách bàn. Test: `test_qa_perf_01`.

## 5. BUG-05: tràn ngang 375px (P3)

- `rc-bar` trên Phiếu nhập: cho xuống dòng (`flex-wrap`) hoặc thu nhỏ chữ tổng tiền.
- `ol.steps` trên Lịch làm: cho cuộn ngang trong khung riêng hoặc xếp dọc dưới 600px.

## 6. BUG-06, BUG-07 (P3)

- Test lịch: cố định thời điểm bằng `mock` hoặc truyền `now` vào hàm kiểm tra hạn.
- Đặt `SECURE_HSTS_SECONDS` (và `SECURE_HSTS_INCLUDE_SUBDOMAINS` nếu phù hợp) trong cấu hình chạy thật.

## 7. Cần Hai quyết định trước khi làm

- QA-SALE-F: có bắt buộc xác nhận tiền đầu ca trước lần thu tiền mặt đầu tiên không.
- QA-SALE-G: có chặn hay chỉ cảnh báo nhân viên chưa chấm công tạo đơn.

## Thứ tự sửa đề xuất

1. BUG-01 (một chỗ sửa, ảnh hưởng tiền trực tiếp).
2. BUG-02 (cần test PostgreSQL đi kèm).
3. BUG-03, BUG-04 (hiệu năng, cùng nhóm báo cáo).
4. BUG-05, BUG-06, BUG-07.
5. Các mục NEEDS SPEC sau khi có quyết định.
