# Độ phủ kiểm thử

Mức phủ: **Có bằng chứng** là có test tự động hoặc phép đo chạy trong đợt này; **Dựa test gốc** là bộ test sẵn có đạt trong baseline nhưng QA không viết thêm; **Chưa** là chưa kiểm.

| Phân hệ | Có bằng chứng | Dựa test gốc | Chưa | Ghi chú |
|---|---|---|---|---|
| Tài khoản, đăng nhập, khóa, hết phiên | QA-AUTH-01..03 | | Đổi mật khẩu, mở khóa bằng lệnh | |
| Phân quyền (4 vai trò x mọi màn) | QA-PERM-01..03, quét AST | | | Toàn bộ ma trận GET; POST các màn nhạy cảm |
| Nhật ký append-only | QA-AUDIT-01 | Trigger SQLite, PostgreSQL | | |
| Dữ liệu gốc, giá, định mức | QA-MD-01..04 | Import thực đơn | Đơn vị quy đổi khi nhập hàng | BUG-01 |
| Bán hàng, topping, ghi chú | QA-SALE-A, C, D, D2, E | | | |
| Phiếu dự phòng | | orders.backup | | |
| Thu trước (prepaid) | | orders.prepaid | | |
| Quầy pha chế, mang ra | QA-BAR-01..03 | | | |
| Điều chỉnh, duyệt, leo thang | QA-ADJ-01..04 | escalate_due | | |
| Hủy hóa đơn, hoàn tiền 2 bước | QA-REF-01..02 | | | |
| Kho: nhập, sổ, kiểm kê, hao hụt, lô | QA-INV-01..04 | Lô, bán thành phẩm | | |
| Ca, quỹ, nộp tiền, kết ca, đối soát | QA-SHIFT-01..03 | Điều chỉnh báo cáo | | |
| Cảnh báo, ngoại lệ, tổn thất | QA-LOSS-01 | control | | |
| Báo cáo, Excel, bảng điều khiển | QA-REP-01..04, QA-DASH-01, QA-DAY-01 | | Mở Excel bằng Excel thật | |
| Lịch, chấm công | QA-SCH-01 | schedule, staff | | 1 test gốc phụ thuộc ngày |
| Dự báo, kế hoạch mua | | forecast | Độ chính xác trên dữ liệu thật | NOT TESTED |
| Đồng thời (PostgreSQL) | 5 gốc + QA-CONC-01..03 | | Tải nhiều người thật qua mạng | BUG-02 |
| Sao lưu, phục hồi | QA-BR-01..02 (SQLite) | | PostgreSQL dump (QA-BR-03) | |
| PWA ngoại tuyến | QA-PWA-01..02 | | Thông báo đẩy trên điện thoại thật | |
| Giao diện 375px | 129 trang, 4 vai trò | | Trình duyệt Safari iOS | BUG-05 |
| Hiệu năng | QA-PERF-01..02 | | Kiểm thử tải | BUG-03, 04 |
| Toàn vẹn dữ liệu | kiem_tra_toan_ven trên dữ liệu thật và bản phục hồi, QA-DAY-02 | | | |

## Số liệu

- Bộ test gốc: 583 test, 582 đạt.
- Bộ QA mới: 42 ca (`test_qa_audit.py`) + 3 ca (`test_qa_concurrency_pg.py`).
- Danh sách ca: 62 mục trong `QA_TEST_CASES.md`: 52 PASS, 6 FAIL, 2 NEEDS SPEC, 2 NOT TESTED.
