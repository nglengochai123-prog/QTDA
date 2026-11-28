# Kết quả kiểm thử

Phiên bản `f0e5d30`, ngày 28/11/2026. Chi tiết từng ca ở `QA_TEST_CASES.md`, lỗi ở `QA_BUG_REPORT.md`.

## Tổng hợp

| Hạng mục | Kết quả |
|---|---|
| Bộ test gốc (SQLite) | 583 test, 582 đạt, 1 hỏng do phụ thuộc ngày (BUG-06), 197 giây |
| `manage.py check` | Không lỗi |
| `check --deploy` | 6 cảnh báo: DEBUG ở máy cá nhân, HSTS chưa đặt (BUG-07) |
| `makemigrations --check` | Không thiếu migration |
| `kiem_tra_toan_ven` trên `db.sqlite3` thật | Không phát hiện sai lệch |
| 42 ca QA nghiệp vụ, SQLite | 40 đạt, 2 hỏng (QA-MD-03, QA-PERF-01) |
| 42 ca QA nghiệp vụ, PostgreSQL 16 | 40 đạt, cùng 2 hỏng |
| Đồng thời PostgreSQL: 5 tình huống gốc | 5 đạt |
| Đồng thời PostgreSQL: 3 tình huống QA | 2 đạt, 1 hỏng (QA-CONC-01) |
| Sao lưu, phục hồi SQLite | Đạt: 95/95 bảng, 104.344 dòng khớp; migrate --check và toàn vẹn đạt; chống đè đạt |
| PWA ngoại tuyến | Đạt: trang mất kết nối; đơn gửi lúc mất mạng giữ mã sau tải lại, gửi lại tạo đúng 1 đơn |
| 375px, 4 vai trò, 129 trang | 127 đạt; 2 trang tràn ngang (BUG-05); 0 lỗi JavaScript; 0 lỗi HTTP |
| Đối soát độc lập ngày | Khớp: 14/11, 05/11, 27/10 (có hoàn tiền), 25/11, 26/11, 22/11, cả tháng 11 |
| Đối soát đơn và kho toàn bộ | 4.105 đơn: 0 lệch tổng; 0 nguyên liệu lệch sổ; 0 tồn âm |

## Số đối soát tháng 11/2026 (bản sao dữ liệu mô phỏng)

| | Tính lại từ bảng gốc | Báo cáo ứng dụng |
|---|---|---|
| Tiền thu | 86.909.000 | 86.909.000 |
| Hoàn đã trả | 75.000 | 75.000 |
| Thuần | 86.834.000 | 86.834.000 |

Bảy chiều xem (ngày, khung giờ, ca, nhóm món, món, nhân viên, phương thức) cộng lại đều bằng số thuần. Doanh thu chốt lúc kết ca của từng ca bằng tổng thanh toán tiền mặt và chuyển khoản ghi vào ca đó.

## Hiệu năng đo được (bản sao dữ liệu)

| Trang | Truy vấn | Thời gian |
|---|---|---|
| Báo cáo Doanh thu | 54 | 7,6–8,4 s |
| Bảng điều khiển, lần đầu | 1.082 | 14–16 s |
| Bảng điều khiển, lần sau | 88 | 1,3 s |
| Bán thành phẩm | 18 | 1,35 s |
| Lịch làm | 24 | 0,47 s |
| Thu ngân | 21 | 0,12 s |

## Quan sát về dữ liệu mô phỏng (không phải lỗi sản phẩm)

Bản sao `db.sqlite3` không có thanh toán nào ngày 27/11 và chưa có dữ liệu ngày 28/11 lúc kiểm. Có thể lần tạo dữ liệu tự động ngày 27 chưa chạy. Nên xem lịch chạy của `noi_mo_phong` trên máy.

## Dọn dẹp sau kiểm thử

- Đã dừng máy chủ thử cổng 8765 và PostgreSQL thử.
- `db.sqlite3` không đổi (so hash trước và sau).
- Không commit, không push, không đổi nhánh. HEAD vẫn `f0e5d30`.
