# Kết quả chạy thử dự báo trên dữ liệu giả định 6 tháng

Ngày chạy 12/10/2026. Tệp `Du_lieu_gia_dinh_LAM_Coffee_6_thang.xlsx` do Hai gửi.

> **Đây là dữ liệu mô phỏng** (chính tệp ghi rõ ở sheet Giai_thich). Kết quả dưới đây chỉ xác minh phần mềm và quy trình dự báo chạy đúng, **không phải bằng chứng độ chính xác tại quán** (khung lý thuyết mục 5.1).

## 1. Nhập dữ liệu

| Kiểm tra | Kết quả |
|---|---|
| Sheet được dùng | `Mon_theo_ngay` (số ly theo ngày, món, cỡ). Hệ thống tự chọn sheet nhỏ nhất có đủ cột ngày, món, số ly |
| Khoảng ngày | 01/04/2026 đến 30/09/2026, 183 ngày, không ngày đóng cửa hay thiếu hàng |
| Tổng số ly nhập | 31.883, khớp cột "Tổng số ly" của sheet `Du_lieu_ngay` |
| Món và cỡ | Đủ 11 món-cỡ, khớp thực đơn, không dòng nào bị bỏ |
| Nơi lưu | Loại "Dữ liệu mô phỏng", tách riêng khỏi dữ liệu thật; chỉ cơ sở dữ liệu chạy thử `thu_du_bao.sqlite3` mới dùng nó cho dự báo |

### Đơn hàng chi tiết

Sheet `Don_hang` và `Chi_tiet_mon` được nhập thành đơn đã thanh toán bằng lệnh `manage.py nhap_don_gia_dinh <tệp> --chay-thu`:

| Kiểm tra | Kết quả |
|---|---|
| Số đơn | 23.753, khớp cột "Số đơn" của `Du_lieu_ngay` |
| Tổng tiền đơn và thanh toán | 1.041.325.000 đ, khớp cột "Doanh thu VND" |
| Số ly | 31.883 trên 31.650 dòng món, không dòng nào lệch tổng tiền |
| Ca | Mỗi ngày một ca "Ca cả ngày (giả định)" đã kết, có báo cáo cuối ca đúng tiền mặt và chuyển khoản |
| Tùy chọn | Đường, đá, topping giữ theo tệp |
| Kho | Không ghi biến động kho (tệp không có nhập hàng, kiểm kê); `kiem_tra_toan_ven` không báo sai lệch |

Đơn hiện ở Bán hàng › Tra cứu đơn (mã GD-…), Báo cáo › Doanh thu (chọn khoảng 01/04–30/09/2026). Bảng điều khiển chỉ hiện ca hôm nay nên không có số liệu của tệp.

## 2. Đánh giá cuốn chiếu

- **Học và kiểm tra:** nửa đầu (01/04 đến khoảng 01/07) dùng để chọn cấu hình; nửa sau (khoảng 02/07 đến 30/09) để kiểm tra, mỗi món 92 ngày kiểm tra ở thời hạn 1 ngày.
- **So với:** cách "cùng thứ tuần trước".
- **Chưa so với ước tính của Chủ quán:** chưa có nhận định theo từng món; nhận định trong tệp tính theo đơn và doanh thu, không theo số ly.
- **Cách đọc chỉ số:**
  - CRPS và MAE: càng nhỏ càng tốt.
  - "Trong khoảng 80%": tỷ lệ ngày có số bán thực nằm trong khoảng 10%–90% của dự báo; lý tưởng là gần 80%.
  - Phân tán: gần 1 là mô hình mô tả đúng độ biến động.

| Món | Cấu hình | Phân tán | 1 ngày: CRPS mô hình / tuần trước | MAE | Trong khoảng 80% | 7 ngày: CRPS mô hình / tuần trước | MAE | Trong khoảng |
|---|---|---|---|---|---|---|---|---|
| Bạc xỉu M | 0.98, 0.0 | 0.89 | 2.105 / 2.62 | 2.87 / 3.7 | 88% / 74% | 2.137 / 2.649 | 2.95 / 3.73 | 87% / 74% |
| Bạc xỉu L | 0.98, 0.0 | 0.86 | 1.331 / 1.856 | 1.89 / 2.53 | 93% / 71% | 1.376 / 1.858 | 1.91 / 2.52 | 93% / 71% |
| Cà phê sữa M | 0.95, 0.0 | 0.89 | 2.952 / 3.923 | 4.11 / 5.46 | 88% / 71% | 3.113 / 4.016 | 4.43 / 5.57 | 86% / 70% |
| Cà phê sữa L | 0.98, 0.0 | 1.08 | 2.025 / 2.68 | 2.84 / 3.73 | 85% / 70% | 2.141 / 2.685 | 3.01 / 3.74 | 78% / 71% |
| Cà phê đen M | 0.98, 0.0 | 1.41 | 2.994 / 3.951 | 3.99 / 5.4 | 82% / 64% | 3.213 / 4.07 | 4.26 / 5.53 | 76% / 63% |
| Cà phê đen L | 0.98, 0.0 | 0.85 | 1.565 / 2.078 | 2.25 / 2.96 | 90% / 73% | 1.605 / 2.039 | 2.33 / 2.91 | 88% / 73% |
| Matcha đá xay M | 0.98, 0.0 | 0.98 | 2.081 / 3.071 | 2.95 / 4.21 | 82% / 62% | 2.068 / 3.083 | 2.9 / 4.19 | 79% / 62% |
| Trà sữa M | 0.98, 0.0 | 1.05 | 2.844 / 3.89 | 4.08 / 5.35 | 83% / 65% | 2.726 / 3.803 | 3.86 / 5.22 | 87% / 67% |
| Trà sữa L | 0.98, 0.0 | 0.84 | 1.662 / 2.057 | 2.29 / 2.89 | 87% / 73% | 1.606 / 2.075 | 2.27 / 2.92 | 91% / 72% |
| Trà đào M | 0.98, 0.0 | 0.97 | 2.995 / 4.378 | 4.26 / 5.96 | 82% / 61% | 3.016 / 4.292 | 4.27 / 5.84 | 83% / 62% |
| Trà đào L | 0.98, 0.0 | 1.18 | 2.347 / 3.141 | 3.39 / 4.2 | 78% / 63% | 2.358 / 3.084 | 3.41 / 4.15 | 80% / 64% |

**Nhận xét**
- Trên dữ liệu này, mô hình có CRPS thấp hơn cách "cùng thứ tuần trước" ở cả 11 món-cỡ, cả thời hạn 1 ngày và 7 ngày (thấp hơn khoảng 20–30%). MAE cũng thấp hơn.
- Khoảng dự báo của mô hình chứa số bán thực 76–93% số ngày, gần mức 80% mong muốn. Nhiều món hơi trên 80%, tức khoảng hơi rộng. Khoảng của cách "tuần trước" chỉ chứa 61–74%, tức quá hẹp so với biến động thật.
- Độ phân tán gần 1 (0,84–1,41), nên mô hình không cần thêm nhiễu quan sát; mọi món đều chọn nhiễu bằng 0. Hệ số thích nghi 0,98 được chọn ở hầu hết món, tức mức nền thay đổi chậm. Điều này hợp với cách dữ liệu được sinh: mức nền theo nhóm ngày, giảm theo tháng hè.
- Kết quả tốt một phần vì dữ liệu được sinh từ đúng cấu trúc mà mô hình mô tả (mức nền theo thứ trong tuần, thay đổi chậm theo tháng). Dữ liệu thật thường có thêm ngày lễ, thời tiết, khuyến mãi, hết hàng. Vì vậy cần chạy lại khi có lịch sử thật.

## 3. Dự báo phát hành sau khi học hết 6 tháng (từ 13/10/2026)

Dữ liệu kết thúc ngày 30/09. Các ngày 01–12/10 không có dữ liệu nên mô hình chỉ để độ bất định tăng dần, không coi là bán 0 ly.

| Món | Ngày mai: kỳ vọng (khoảng 10%–90%) | 7 ngày tới: kỳ vọng (khoảng) |
|---|---|---|
| Bạc xỉu M | 16.9 (11–23) | 135 (112–160) |
| Bạc xỉu L | 6.9 (3–11) | 55 (39–72) |
| Cà phê sữa M | 28.2 (21–36) | 242 (205–281) |
| Cà phê sữa L | 11.8 (7–17) | 104 (82–126) |
| Cà phê đen M | 19.8 (13–26) | 176 (149–207) |
| Cà phê đen L | 8.3 (4–13) | 73 (54–95) |
| Matcha đá xay M | 10.8 (6–16) | 92 (71–112) |
| Trà sữa M | 19.4 (13–26) | 160 (133–190) |
| Trà sữa L | 7.2 (4–11) | 62 (46–79) |
| Trà đào M | 19.1 (13–26) | 163 (136–191) |
| Trà đào L | 9.4 (5–14) | 77 (58–96) |

## 4. Giới hạn

- Một mùa hè duy nhất trong 6 tháng, chưa đủ để xác nhận quy luật mùa vụ lặp lại hằng năm. Mô hình hiện bám mùa hè qua mức nền thay đổi dần, chưa có hiệu ứng mùa riêng.
- Chưa có nhận định Chủ quán theo món, nên chưa so được cách "Ước tính ban đầu".

## 5. Cách xem lại

Chạy máy chủ chạy thử bằng cấu hình `lam-thu-du-bao` (cổng 8768), đăng nhập `demo_chuquan`, mở Dự báo › Đánh giá dự báo và Dự báo nhu cầu. Hoặc dùng PowerShell:

```powershell
$env:SQLITE_NAME = "thu_du_bao.sqlite3"; $env:LAM_FORECAST_INCLUDE_SIMULATED = "true"
.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8768
```

Đầu mỗi trang có dải vàng báo đang dùng dữ liệu mô phỏng. Bộ dữ liệu mẫu 8766 và cơ sở dữ liệu chính không dùng dữ liệu này cho dự báo.
