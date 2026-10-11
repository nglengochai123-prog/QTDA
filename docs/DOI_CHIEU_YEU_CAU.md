# Đối chiếu Phần 1–3 với báo cáo yêu cầu

Cập nhật 11/10/2026, sau đợt rà soát tích hợp trước Phần 4. Bảng này so mã nguồn trong `D:\QTDA` với báo cáo yêu cầu đã chỉnh sửa (`BAO CAO SPRINT 1.docx`). Số bài kiểm thử không được dùng làm bằng chứng hoàn thành; mỗi dòng ghi rõ đã kiểm tra bằng gì.

## 1. Bộ tài liệu chuẩn

| Tài liệu | Quy định điều gì | Khi khác nhau |
|---|---|---|
| Báo cáo yêu cầu (BRD) đã chỉnh sửa | Chức năng FR, quy tắc BRU, phi chức năng NFR, tiêu chí nghiệm thu AC, Bảng 5.2 tham số, Bảng 5.3 phân quyền, Bảng 5.4 cảnh báo, Bảng 9.1 sprint | BRD thắng. Mọi chỗ mã nguồn khác BRD được ghi ở mục 4 kèm lý do |
| `PRODUCT.md` | Bối cảnh, người dùng, thiết bị, mục tiêu trải nghiệm | Không quy định nghiệp vụ |
| `DESIGN.md` | Chuẩn giao diện (định hướng tạm "vở ô ly, mực tím, lề đỏ") | Không quy định nghiệp vụ |
| `KE_HOACH.md` trong repo | Tiến độ thực tế và phần còn thiếu | Là bản tiến độ duy nhất đúng; các bản `KE_HOACH*.md` trong thư viện là bản cũ |
| Tài liệu này | Đối chiếu chi tiết, giả định và quyết định chờ Chủ quán | Cập nhật mỗi lần rà soát |

Business Case và Project Charter là tài liệu nguồn của BRD, không dùng trực tiếp để quyết định hành vi hệ thống.

## 2. Nơi xử lý dùng chung

Mọi màn hình, lệnh và kiểm thử đều gọi qua các hàm sau, không ghi thẳng vào bảng dữ liệu.

| Nghiệp vụ | Hàm | Bảo đảm |
|---|---|---|
| Mọi thay đổi tồn kho | `apps/inventory/stock.py`: `move`, `reserve`, `consume`, `release`, `record_opening` | Khóa dòng tồn, cập nhật tồn và ghi sổ biến động trong cùng giao dịch; `ledger_problems()` kiểm tồn = tổng sổ, đang giữ = món chờ pha |
| Nhận đơn | `orders/services.submit_order` | Kiểm đủ, giữ chỗ cả đơn, chụp giá và định mức lúc nhận |
| Pha xong, phục vụ | `orders/services.complete_line`, `serve_line` | Trừ kho và bỏ giữ chỗ đúng một lần |
| Điều chỉnh đơn | `orders/adjustments.create_request`, `decide`, `apply_effects` | Cập nhật món, nguyên liệu, tổng tiền, nhật ký trong một giao dịch |
| Thanh toán, hoàn tiền | `orders/payments.pay_table`, `pay_received_items`; `shifts/services.record_refund` | Gắn ca; hoàn tiền mỗi yêu cầu một khoản |
| Nhập, kiểm kê, hao hụt | `inventory/operations.create_receipt`, `submit_count`, `confirm_count`, `record_waste` | Biến động kho có nguồn nghiệp vụ |
| Xác minh tổn thất | `control/services.open_case`, `add_evidence`, `verify`, `recover`, `monthly_control` | Mỗi bằng chứng thuộc một vụ việc; khoản thiếu chuyển nhóm khi xác minh, không tính hai lần |
| Kiểm tra quá hạn | `core/periodic.run_all` qua lệnh `chay_dinh_ky` | Màn hình tự tính đúng khi đọc; lệnh định kỳ chỉ ghi trạng thái và nhật ký |
| Kiểm tra toàn vẹn | `core/integrity.problems` qua lệnh `kiem_tra_toan_ven` | Đối chiếu chéo sổ kho, đơn, giao dịch thu, hoàn tiền, doanh thu đã chốt |

Chống ghi trùng (NFR-04): mọi thao tác tạo dữ liệu dùng mã nghiệp vụ (`core/idempotency.run_once`). Gửi lại cùng mã trả kết quả cũ, cùng mã khác nội dung bị từ chối. Các thao tác trạng thái (duyệt, quyết định chênh lệch, xác minh, báo cáo cuối ca) bấm lại cùng nội dung trả kết quả cũ, khác nội dung bị từ chối.

## 3. Bảng đối chiếu theo chức năng

Trạng thái: **Đúng** là làm đủ theo BRD và có kiểm thử; **Một phần** là có phần chưa làm; **Khác** là làm khác BRD (lý do ở mục 4); **Chưa làm** là chưa có; các giá trị đặt tạm nằm ở mục 5.

| Mã | Nội dung | Trạng thái | Ghi chú, bằng chứng |
|---|---|---|---|
| FR-01 | Tạo đơn trên điện thoại | Đúng | AC-01, AC-02, AC-04: `orders/tests/test_flow.py`. AC-03: kiểm kê nhanh đi qua màn Kiểm kê, chưa có lối tắt từ màn tạo đơn |
| FR-02 | Gửi quầy pha chế, in phiếu | Đúng | Giữ chỗ cả đơn trong một giao dịch; hai đơn đồng thời chỉ kiểm trên SQLite (xem mục 4) |
| FR-03 | Vòng đời đơn | Đúng | AC-06, AC-07 |
| FR-04 | Thanh toán theo bàn | Đúng | AC-08, AC-09, AC-10; trạng thái chờ duyệt và quá hạn mọi cấp tính khi đọc |
| FR-05 | In hóa đơn | Chưa làm | Could, Giai đoạn 3 theo BRD |
| FR-06 | Bán hàng dự phòng, nhập bù | Chưa làm | Phần 4. Hiện có mã nghiệp vụ hiển thị khi mất phản hồi để ghi lên phiếu |
| FR-07 | Quỹ tiền mặt ca | Đúng | AC-14, AC-15 |
| FR-08 | Kết ca, báo cáo cuối ca | Một phần | AC-16, AC-17 đúng; "Chủ quán nhận thông báo" mới là thông báo trong ứng dụng, chưa có Web Push |
| FR-09 | Tình trạng dữ liệu ca | Một phần | Có chưa kết ca, thiếu báo cáo quá hạn (AC-18). Chưa có: kiểm kê nhóm trọng yếu trước giờ mở cửa hôm sau, nhập bù (Phần 4), cảnh báo chuyển Chủ quán khi quá hạn xử lý (cùng FR-51) |
| FR-10 | Khóa đơn, yêu cầu điều chỉnh | Đúng | AC-19, AC-20; Chủ quán sửa được danh mục lý do trong trang dữ liệu nền |
| FR-11 | Phê duyệt và chuyển cấp | Đúng | AC-21 đến AC-24; cấp hiện hành tính khi đọc nên không phụ thuộc ai mở màn hình; nhật ký chuyển cấp ghi khi chạy `chay_dinh_ky` |
| FR-12 | Đối soát doanh thu ca | Đúng | AC-25, AC-26, AC-27; lưu ngưỡng đã áp dụng vào từng khoản chênh lệch |
| FR-13 | Chênh lệch tích lũy | Đúng | AC-28 |
| FR-14 | Báo cáo điều chỉnh | Đúng | AC-29 |
| FR-15 | Ngoại lệ theo quy tắc | Một phần | AC-30, AC-31 đúng; giao cho Chủ quán, chưa có thời hạn và chuyển cấp theo Bảng 5.4 |
| FR-16 | Đối chiếu tiêu hao trọng yếu | Chưa làm | Phần 4 |
| FR-17 | Xem xét ngoại lệ | Đúng | AC-35, AC-36, AC-37 |
| FR-18 | Vụ việc tổn thất | Đúng | AC-38 đến AC-41 |
| FR-20 | Danh mục nguyên vật liệu | Đúng | AC-44, AC-45 |
| FR-21 | Định mức có phiên bản | Đúng | AC-46, AC-47 |
| FR-22 | Tồn kho thời gian thực | Đúng | AC-48, AC-49, AC-50 |
| FR-23 | Báo nhanh nguyên liệu | Một phần | AC-51 phần ghi nhận đúng; giao người xử lý có thời hạn theo Bảng 5.4 chưa làm |
| FR-24 | Phiếu nhập | Đúng | AC-52 đến AC-55; ảnh hóa đơn bắt buộc cho mọi phiếu (đã bỏ ngưỡng 500.000 đ tự đặt) |
| FR-25 | Kiểm kê | Đúng | AC-56, AC-57, AC-58; lưu ngưỡng % đã áp dụng |
| FR-26 | Hao hụt | Đúng | AC-59, AC-60 |
| FR-27 | Trường hợp thiếu nguyên liệu | Đúng | AC-61, AC-62, AC-63 |
| FR-28, FR-29, FR-31 | Ước tính nhu cầu, cần đặt hàng, đề xuất số lượng | Chưa làm | Chờ Hai giải thích logic dự báo; chỉ chuẩn bị dữ liệu đầu vào (mục 7) |
| FR-30 | Đặt hàng, theo dõi giao | Đúng | AC-68, AC-69; Giao chậm tính khi đọc |
| FR-59 | Tài khoản, phân quyền | Một phần | AC-111, AC-112 phần đã có màn hình; AC-113 chưa nhắc tự động trước giờ ca |
| FR-60 | Danh mục món, bảng giá | Đúng | AC-114 |
| FR-61 | Nhật ký thao tác | Đúng | AC-115; chỉ thêm, chặn sửa xóa cả ở CSDL |
| NFR-04 | Không ghi trùng | Đúng | Mọi thao tác tạo dữ liệu có mã nghiệp vụ; kiểm thử gửi lại trong `core/tests/test_end_to_end.py` |
| NFR-14 | Tham số sửa trên ứng dụng | Đúng | Có lịch sử và thời điểm hiệu lực; xem mục 5 |
| NFR-17 | Web Push | Chưa làm | Hiện báo trong ứng dụng khi đang mở |

Luồng xuyên suốt nhập hàng → tạo đơn → pha một phần → điều chỉnh → phục vụ → thanh toán → hủy hóa đơn có hoàn tiền → kết ca → đối soát → giải trình → xác minh → báo cáo được kiểm trong `apps/core/tests/test_end_to_end.py`, đối chiếu cùng lúc trạng thái đơn, sổ kho, giao dịch tiền, báo cáo điều chỉnh, giá trị kiểm soát tháng và nhật ký.

## 4. Chỗ khác báo cáo và lý do

| Chỗ khác | BRD | Hiện tại | Lý do |
|---|---|---|---|
| Ca làm việc | Lịch ca từ đăng ký và lập lịch (FR-38, FR-39, Giai đoạn 2) | Chủ quán khai báo ca tối thiểu: giờ, người duyệt, dự phòng, người ủy quyền | Đơn, thanh toán, đối soát cần gắn ca ngay từ Phần 1 |
| Trang tham số | Mục công nghệ ghi tham số nằm trong Django admin | Trang Kiểm soát › Tham số | Cần hiện căn cứ, lịch sử, thời điểm hiệu lực và dùng được trên điện thoại |
| Tự chuyển cấp | "Tự chuyển" khi quá hạn | Cấp đúng ngay khi đọc; ghi nhật ký chuyển cấp khi lệnh `chay_dinh_ky` chạy | Không để việc mở màn hình quyết định dữ liệu. Khi triển khai cần lên lịch lệnh mỗi phút (Task Scheduler hoặc `--lap 60`) |
| Kiểm thử đồng thời | Hệ thống chạy PostgreSQL | Chỉ kiểm trên SQLite | Máy chưa cài PostgreSQL; xem GD-13 |
| Cảnh báo theo Bảng 5.4 | Mỗi loại có người xử lý, thời hạn, cấp chuyển | Ngoại lệ giao Chủ quán, báo trong ứng dụng | Làm cùng trung tâm cảnh báo FR-51 ở Phần 4 |

## 5. Tham số: căn cứ và quy tắc hiệu lực

Trang Tham số hiện căn cứ của từng giá trị. "Theo ví dụ AC" nghĩa là BRD không nêu giá trị mặc định, dự án lấy số trong ví dụ của tiêu chí nghiệm thu.

| Tham số | Mặc định | Căn cứ |
|---|---|---|
| Thời hạn mỗi cấp duyệt | 3 phút | BRD Bảng 5.2 |
| Thời hạn báo cáo cuối ca | 2 giờ | BRD Bảng 5.2 |
| Ngày nhắc lại ngoại lệ | 3 ngày | BRD Bảng 5.2 |
| Khoản chi tiền mặt cần ảnh chứng từ | 500.000 đ | BRD BRU-33 |
| Ngưỡng chênh lệch tiền mặt | 50.000 đ | Theo ví dụ AC-25 |
| Ngưỡng tích lũy mỗi Quản lý ca | 100.000 đ/tháng | Theo ví dụ AC-28 |
| Số điều chỉnh sau pha chế mỗi nhân viên mỗi ca | 3 | Theo ví dụ AC-31 |
| Ngưỡng kiểm kê từng lần | 5% | Theo ví dụ AC-56 |
| Giờ đóng cửa | 22 giờ | Theo ví dụ AC-62 |
| Ngưỡng chênh lệch chuyển khoản | 50.000 đ | Giả định (GD-01) |
| Ngưỡng tích lũy toàn quán | 300.000 đ/tháng | Giả định (GD-02) |
| Giá trị hủy sau pha chế mỗi ca | 100.000 đ | Giả định (GD-03) |
| Giờ mở cửa | 6 giờ | Giả định (GD-04) |

Mỗi lần lưu là một giá trị mới có "hiệu lực từ", không sửa, không xóa, không lùi về quá khứ. Quy tắc áp dụng cho việc đang dở được ghi ở GD-10.

## 6. Quyết định nghiệp vụ cần Chủ quán xác nhận

| Mã | Câu hỏi | Đang làm theo |
|---|---|---|
| GD-01 | Ngưỡng chênh lệch chuyển khoản mỗi ca là bao nhiêu? | 50.000 đ, bằng ngưỡng tiền mặt |
| GD-02 | Ngưỡng tích lũy thiếu tiền toàn quán mỗi tháng là bao nhiêu? | 300.000 đ |
| GD-03 | Tổng giá trị món hủy sau pha chế mỗi ca bao nhiêu thì tạo ngoại lệ? | 100.000 đ |
| GD-04 | Quán mở cửa lúc mấy giờ? | 6 giờ |
| GD-05 | Các số lấy từ ví dụ AC (50.000 đ, 100.000 đ, 3 yêu cầu, 5%, 22 giờ) có dùng làm giá trị thật không? | Dùng làm mặc định |
| GD-06 | Phiếu nhập luôn cần ảnh hóa đơn (AC-55); mức 500.000 đ của BRU-33 chỉ áp dụng cho khoản chi tiền mặt khác trong ca. Đúng ý không? | Như câu hỏi |
| GD-07 | Hủy hóa đơn đã thanh toán: hoàn theo đúng phương thức khách đã trả; ghi vào ca đang mở lúc Chủ quán duyệt (doanh thu vẫn thuộc ca đã thu); không có ca mở thì chưa duyệt được | Như câu hỏi |
| GD-08 | Ca chưa có người duyệt dự phòng: quá hạn chuyển thẳng Chủ quán | Như câu hỏi |
| GD-09 | Phiếu nhập Trả ngay bằng tiền mặt quỹ ca được ghi thành khoản chi danh mục Nguyên vật liệu của ca đang mở và trừ vào tiền mặt phải có | Như câu hỏi |
| GD-10 | Đổi tham số khi việc đang dở: yêu cầu điều chỉnh giữ thời hạn lúc tạo (đổi 3 → 5 phút thì yêu cầu đang chờ vẫn theo 3 phút); đối soát dùng ngưỡng có hiệu lực lúc kết ca; kiểm kê dùng ngưỡng lúc gửi kết quả; thời hạn báo cáo cuối ca theo giá trị lúc ca kết thúc; các kiểm tra khác dùng giá trị lúc phát sinh; ngoại lệ và báo cáo đã có không tính lại | Như câu hỏi |
| GD-11 | Báo cáo cuối ca gửi rồi không sửa; số liệu khác phải ghi bằng giải trình chênh lệch | Như câu hỏi |
| GD-12 | Trước khi có lịch ca (Giai đoạn 2), Chủ quán khai báo ca bằng tay trên ứng dụng | Như câu hỏi |
| GD-13 | Cho phép cài PostgreSQL trên máy để kiểm tra hai đơn đồng thời trước Go-Live? | Chưa cài; mới kiểm trên SQLite |

## 7. Dữ liệu đầu vào cho dự báo (logic dự báo chờ Hai giải thích)

| Dữ liệu | Đang lưu ở | Ghi chú |
|---|---|---|
| Thời điểm nhận đơn | `Order.created_at` | Theo giờ máy chủ, UTC+7 khi hiển thị |
| Thời điểm pha xong | `OrderLine.done_at` (cả dòng xong); từng lần pha một phần: `StockMovement` loại Tiêu hao, `created_at` | |
| Thời điểm mang ra | `OrderLine.served_at`, `served_by` | |
| Số lượng | `OrderLine.quantity`, `done_quantity`, `cancelled_quantity`, `voided_done_quantity` | Tách hủy trước và sau pha chế |
| Định mức đã dùng | `OrderLine.recipe_version`, `usage_per_unit` | Chụp lúc nhận đơn |
| Tiêu hao thực tế | `StockMovement` theo nguyên liệu, loại, nguồn nghiệp vụ | Sổ chỉ thêm mới |
| Thiếu nguyên liệu | `ShortageCase` (nguyên liệu, ngày, nguồn) | Tối đa một trường hợp mỗi nguyên liệu mỗi ngày |
| Nhân sự có mặt theo vai trò | Chưa có | Cần chấm công theo vai trò (FR-35, Phần 4). Hiện chỉ có người duyệt của ca |
