# Kế hoạch kiểm thử tổng thể

## Phạm vi và phiên bản

- Hệ thống: LAM Coffee System (Django 5.2.18, Python 3.13.7).
- Phiên bản: commit `f0e5d30`, xác minh bằng `git rev-parse` và so với `origin/main`, không dựa vào tên nhánh.
- Thời gian: 28/11/2026.
- Vai trò người kiểm: QA, BA, kiểm thử Django.

## Nguyên tắc đã tuân thủ

- Không đổi nhánh, không merge, reset, rebase, pull, commit, push.
- Không sửa logic sản phẩm, model, migration, phân quyền; không sửa test sẵn có.
- Không ghi vào `db.sqlite3` thật. Mọi thao tác ghi chạy trên CSDL test của Django, bản sao trong thư mục tạm, hoặc PostgreSQL thử riêng. Hash `db.sqlite3` trước và sau đợt kiểm thử: `493dfc06f2acc8cd…` (không đổi).
- Chỉ đánh PASS khi có bằng chứng (test tự động, đầu ra lệnh, ảnh, số đo). Thiếu điều kiện ghi NOT TESTED; tài liệu chưa quy định ghi NEEDS SPEC.
- Bằng chứng đồng thời chỉ tính trên PostgreSQL.

## Môi trường

| Môi trường | Dùng cho |
|---|---|
| SQLite test của Django | Bộ test gốc, 42 ca QA nghiệp vụ |
| PostgreSQL 16 riêng (cổng 5433, dữ liệu ở `C:\Users\HP\lam-postgres`) | 42 ca QA chạy lại, 5 + 3 tình huống tranh chấp |
| Bản sao `db.sqlite3` trong thư mục tạm | Sao lưu và phục hồi, đối soát ngày, đo hiệu năng, trình duyệt |
| Máy chủ riêng cổng 8765 trên bản sao | PWA ngoại tuyến, 375px (Edge không giao diện qua Playwright) |

## Các giai đoạn

| Giai đoạn | Nội dung | Kết quả |
|---|---|---|
| 0–1 | Xác minh phiên bản, khảo sát tài liệu, code, test, migration | Xong |
| 2 | Baseline, check, migration, toàn vẹn | 582/583, sạch |
| 3 | Tài khoản, phân quyền, nhật ký | Đạt |
| 4 | Dữ liệu gốc, công thức, đơn vị | 1 lỗi (BUG-01) |
| 5 | Bán hàng đầu cuối A–E, gửi lại, phiếu dự phòng | Đạt; 2 NEEDS SPEC |
| 6 | Quầy, mang ra, điều chỉnh, hủy hóa đơn, hoàn tiền | Đạt |
| 7 | Kho: nhập có ảnh, sổ kho, kiểm kê, hao hụt | Đạt |
| 8 | Ca, quỹ, kết ca, báo cáo, đối soát, điều chỉnh báo cáo | Đạt |
| 9 | Cảnh báo, ngoại lệ, tổn thất | Đạt |
| 10 | Bảng điều khiển, báo cáo, Excel | Đúng số; chậm (BUG-03) |
| 11 | Nhân sự, lịch, dự báo | Dựa vào test gốc; 1 ca QA |
| 12 | Gửi lại, giao dịch, đồng thời trên PostgreSQL | 1 lỗi (BUG-02) |
| 13 | PWA ngoại tuyến, sao lưu và phục hồi | Đạt (PostgreSQL dump chưa chạy) |
| 14 | Hiệu năng, N+1, 375px | BUG-03, 04, 05 |
| 15 | Mô phỏng và đối soát trọn ngày | Khớp tuyệt đối |

## Tiêu chí chấp nhận đề xuất

- Không còn lỗi P0, P1.
- Bộ test gốc và bộ QA đạt toàn bộ trên SQLite và PostgreSQL.
- Báo cáo Doanh thu và Bảng điều khiển mở dưới 3 giây với dữ liệu 3 tháng.
- Các mục NEEDS SPEC có quyết định bằng văn bản.
