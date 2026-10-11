# Đối chiếu Phần 1–3 với báo cáo yêu cầu

Cập nhật 11/10/2026, sau đợt rà soát tích hợp và sau khi Chủ quán trả lời các quyết định GD-01 đến GD-13. Bảng này so mã nguồn trong `D:\QTDA` với báo cáo yêu cầu đã chỉnh sửa (`BAO CAO SPRINT 1.docx`). Số bài kiểm thử không được dùng làm bằng chứng hoàn thành; mỗi dòng ghi rõ đã kiểm tra bằng gì.

## 1. Bộ tài liệu chuẩn

| Tài liệu | Quy định điều gì | Khi khác nhau |
|---|---|---|
| `BAO CAO SPRINT 1.docx` trong thư viện dự án: báo cáo yêu cầu (BRD) đã chỉnh sửa, tài liệu yêu cầu chính thức (Chủ quán xác nhận 11/10/2026) | Chức năng FR, quy tắc BRU, phi chức năng NFR, tiêu chí nghiệm thu AC, Bảng 5.2 tham số, Bảng 5.3 phân quyền, Bảng 5.4 cảnh báo, Bảng 9.1 sprint | BRD thắng. Mọi chỗ mã nguồn khác BRD được ghi ở mục 4 kèm lý do |
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
| Thanh toán, hoàn tiền | `orders/payments.pay_table`, `pay_received_items`; `shifts/services.approve_refund`, `confirm_refund` | Gắn ca; hoàn tiền mỗi yêu cầu một khoản, tiền ra ghi một lần vào ca thực hoàn |
| Báo cáo cuối ca, đính chính | `shifts/services.submit_report`, `request_correction`, `decide_correction`, `reconcile` | Đối soát lại theo số có hiệu lực, không tính trùng chênh lệch |
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
| FR-06 | Bán hàng dự phòng, nhập bù | Đúng | AC-12, AC-13 (`orders/tests/test_backup.py`): cấp dãy theo ca có người nhận; nhập bù có mã nghiệp vụ thì liên kết đơn đã lưu và chỉ bổ sung phần thiếu; phiếu không mã tạo đơn theo định mức lúc bán; gửi lại không ghi thêm; nháp gửi lại trả đơn đã nhập bù; số trùng, ngoài dãy, quá hạn, hủy tạo ngoại lệ; kết ca bị chặn khi còn số chưa xử lý. Màn hình /du-phong/ |
| FR-07 | Quỹ tiền mặt ca | Đúng | AC-14, AC-15 |
| FR-08 | Kết ca, báo cáo cuối ca | Một phần | AC-16, AC-17 đúng; đính chính báo cáo có lý do và người duyệt (GD-11); "Chủ quán nhận thông báo" mới là thông báo trong ứng dụng, chưa có Web Push |
| FR-09 | Tình trạng dữ liệu ca | Một phần | Có chưa kết ca, thiếu báo cáo quá hạn (AC-18). Chưa có: kiểm kê nhóm trọng yếu trước giờ mở cửa hôm sau, nhập bù (Phần 4), cảnh báo chuyển Chủ quán khi quá hạn xử lý (cùng FR-51) |
| FR-10 | Khóa đơn, yêu cầu điều chỉnh | Đúng | AC-19, AC-20; Chủ quán sửa được danh mục lý do trong trang dữ liệu nền |
| FR-11 | Phê duyệt và chuyển cấp | Đúng | AC-21 đến AC-24; cấp hiện hành tính khi đọc nên không phụ thuộc ai mở màn hình; nhật ký chuyển cấp ghi khi chạy `chay_dinh_ky` |
| FR-12 | Đối soát doanh thu ca | Đúng | AC-25, AC-26, AC-27; lưu ngưỡng đã áp dụng vào từng khoản chênh lệch |
| FR-13 | Chênh lệch tích lũy | Đúng | AC-28 |
| FR-14 | Báo cáo điều chỉnh | Đúng | AC-29 |
| FR-15 | Ngoại lệ theo quy tắc | Đúng | AC-30, AC-31; ngoại lệ phiếu dự phòng (hủy, trùng, ngoài dãy, quá hạn) và tiêu hao vượt mức; giao Chủ quán qua trung tâm cảnh báo có thời hạn và nhắc lại |
| FR-16 | Đối chiếu tiêu hao trọng yếu | Đúng | AC-32, AC-33 (`inventory/tests/test_consumption.py`): chạy khi kiểm kê nguyên liệu trọng yếu được áp dụng, so với lần kiểm kê áp dụng trước; vượt mức cho phép tạo ngoại lệ; kết quả hiện ở Báo cáo nguyên vật liệu (AC-34). Mức cho phép 5% là tham số, theo ví dụ AC-32 |
| FR-17 | Xem xét ngoại lệ | Đúng | AC-35, AC-36, AC-37 |
| FR-18 | Vụ việc tổn thất | Đúng | AC-38 đến AC-41 |
| FR-20 | Danh mục nguyên vật liệu | Đúng | AC-44, AC-45 |
| FR-21 | Định mức có phiên bản | Đúng | AC-46, AC-47 |
| FR-22 | Tồn kho thời gian thực | Đúng | AC-48, AC-49, AC-50 |
| FR-23 | Báo nhanh nguyên liệu | Đúng | AC-51; báo Đã hết trong giờ mở cửa thành cảnh báo Khẩn giao Quản lý ca 15 phút, quá hạn chuyển Chủ quán |
| FR-24 | Phiếu nhập | Đúng | AC-52 đến AC-55; ảnh hóa đơn bắt buộc cho mọi phiếu (đã bỏ ngưỡng 500.000 đ tự đặt) |
| FR-25 | Kiểm kê | Đúng | AC-56, AC-57, AC-58; lưu ngưỡng % đã áp dụng |
| FR-26 | Hao hụt | Đúng | AC-59, AC-60 |
| FR-27 | Trường hợp thiếu nguyên liệu | Đúng | AC-61, AC-62, AC-63 |
| FR-28, FR-29, FR-31 | Ước tính nhu cầu, cần đặt hàng, đề xuất số lượng | Chưa làm | Chờ Hai giải thích logic dự báo; chỉ chuẩn bị dữ liệu đầu vào (mục 7) |
| FR-35 | Chấm công vào ca, ra ca | Đúng | AC-76, AC-77, AC-78 (`staff/tests/test_timekeeping.py`): vào ca chọn vai trò mình đảm nhận; thiếu giờ ra không tính giờ công, nhắc Quản lý ca qua lệnh định kỳ; bổ sung giờ ra phải có lý do, ghi nhật ký. Chưa có lịch ca nên giờ công tính theo giờ vào, ra (BRU-31 khi chưa có lịch). Màn hình /cham-cong/ |
| FR-36 | Tải và chất lượng phục vụ | Đúng | AC-79: tải theo hệ số nhóm món, thời gian chờ trung vị từ gửi pha chế đến mang ra, món tồn quầy cuối khung, đánh dấu quá tải, số người có mặt theo vai trò. Màn hình /tai/ |
| FR-30 | Đặt hàng, theo dõi giao | Đúng | AC-68, AC-69; Giao chậm tính khi đọc |
| FR-51 | Trung tâm cảnh báo | Một phần | AC-102, AC-103 (`control/tests/test_alerts.py`): các loại ở Bảng 5.4 trừ "Cần đặt hàng" (chờ dự báo) và "Kiểm kê lại sau khi pha chế xác nhận còn hàng"; giao người xử lý chính, thời hạn là tham số, trạng thái Mới, Đang xử lý, Đã đóng; tự đóng khi điều kiện không còn; đóng tay phải có ghi chú; quá hạn chuyển Chủ quán hoặc nhắc lại hằng ngày; thống kê tuần theo NFR-23. Chưa có thông báo đẩy. Màn hình /canh-bao/ |
| FR-50 | Bảng điều khiển | Đúng | AC-100, AC-101: BO-01 với từng khoản cấu thành và liên kết sang báo cáo kiểm soát, BO-02, doanh thu và số đơn theo ngày, chênh lệch tích lũy, tồn nguyên liệu trọng yếu, cảnh báo và ngoại lệ đang mở theo mức. Chưa có BO-03 và lợi nhuận (Giai đoạn 2). Màn hình /bang-dieu-khien/ |
| FR-52 | Báo cáo kiểm soát doanh thu | Đúng | AC-104 (`reports/tests/test_reports.py`): điều chỉnh theo lý do và kết quả, ngoại lệ theo nguồn và kết quả xem xét, chênh lệch theo ca và tích lũy, vụ việc, giá trị kiểm soát tách nhóm không tính trùng. Chỉ Chủ quán. /bao-cao/kiem-soat/ |
| FR-53 | Báo cáo doanh thu | Đúng | AC-105: theo ngày, khung giờ, ca, nhóm món, món, nhân viên, phương thức; so với kỳ trước; xuất Excel (.xlsx, mỗi chiều một trang). /bao-cao/doanh-thu/ |
| FR-54 | Báo cáo nguyên vật liệu | Một phần | AC-106: tồn đầu, nhập, tiêu hao theo món (gồm hủy sau pha chế, không trừ lần hai), hao hụt, kiểm kê, tồn cuối khớp sổ kho, trường hợp thiếu. Cột nhu cầu ước tính chờ logic dự báo. /bao-cao/nguyen-lieu/ |
| FR-59 | Tài khoản, phân quyền | Một phần | AC-111, AC-112 phần đã có màn hình; AC-113: bắt buộc người duyệt dự phòng khi khai báo ca, nhắc trên trang chủ và trong lệnh định kỳ; chưa có thông báo đẩy |
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
| Kiểm thử đồng thời | Hệ thống chạy PostgreSQL | Chỉ kiểm trên SQLite; chưa kết luận đạt trên PostgreSQL | Chờ Chủ quán cho phép cài PostgreSQL (GD-13) |
| Cảnh báo theo Bảng 5.4 | Hệ thống tự giao và tự chuyển cấp | Trung tâm cảnh báo cập nhật khi lệnh `chay_dinh_ky` chạy (nên lên lịch mỗi phút) | Tách kiểm tra quá hạn khỏi việc mở màn hình theo yêu cầu của Chủ quán |

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
| Ngưỡng cảnh báo tích lũy toàn quán | 300.000 đ/tháng | Giả định (GD-02); khác mục tiêu BO-01 dưới 200.000 đ/tháng |
| Giá trị hủy sau pha chế mỗi ca | 100.000 đ | Giả định (GD-03) |
| Giờ mở cửa | 6 giờ | Giả định (GD-04) |

Mỗi lần lưu là một giá trị mới có "hiệu lực từ", không sửa, không xóa, không lùi về quá khứ. Việc đang dở dùng giá trị đã chốt: yêu cầu điều chỉnh giữ thời hạn lúc tạo (đổi 3 → 5 phút thì yêu cầu đang chờ vẫn theo 3 phút); đối soát dùng ngưỡng có hiệu lực lúc kết ca và lưu ngưỡng đó vào khoản chênh lệch; kiểm kê lưu ngưỡng % lúc gửi; thời hạn báo cáo cuối ca theo giá trị lúc ca kết thúc. Số liệu báo cáo vẫn tính lại theo giao dịch và đính chính hợp lệ (GD-10).

## 6. Quyết định nghiệp vụ

Chủ quán trả lời ngày 11/10/2026. Cột "Đã làm" ghi cách hệ thống thực hiện và kiểm thử tương ứng.

| Mã | Quyết định của Chủ quán | Đã làm |
|---|---|---|
| GD-01 đến GD-05 | Dùng các giá trị hiện tại làm mặc định tạm để phát triển và kiểm thử, ghi rõ là giả định, cho phép cấu hình; mọi chênh lệch vẫn được lưu | Trang Tham số đánh dấu từng giá trị "Giả định chờ Chủ quán xác nhận" hoặc "Theo ví dụ AC"; sửa được, có lịch sử. Chênh lệch khác 0 luôn được lưu, ngưỡng chỉ quyết định mức ưu tiên |
| GD-02 (bổ sung) | Tách ngưỡng cảnh báo toàn quán 300.000 đ khỏi mục tiêu BO-01 dưới 200.000 đ | Mục tiêu BO-01 là hằng số dự án `BO01_MONTHLY_TARGET` trong `control/services.py`, không phải tham số cảnh báo; trang Tình trạng ca hiện hai con số riêng (`test_corrections.TargetSeparationTests`) |
| GD-06 | Theo đề xuất: phiếu nhập luôn cần ảnh hóa đơn; 500.000 đ của BRU-33 chỉ áp dụng cho khoản chi tiền mặt khác trong ca | Đã có từ đợt trước |
| GD-07 | Phân biệt duyệt hoàn với xác nhận đã hoàn tiền; chỉ ghi tiền ra một lần vào ca thực sự hoàn; giữ liên kết với thanh toán gốc | Duyệt hủy hóa đơn tạo khoản hoàn "Đã duyệt, chờ hoàn tiền", gắn thanh toán gốc, chưa gắn ca, không cần ca mở. Thu ngân bấm "Đã hoàn tiền" ở trang Ca của tôi: khoản hoàn gắn ca đang mở lúc đó; bấm lại không ghi thêm. Đối soát chỉ trừ khoản đã hoàn (`test_refunds.py`) |
| GD-08 | Nhắc và yêu cầu bổ sung người duyệt dự phòng trước khi ca hoạt động; chuyển thẳng Chủ quán chỉ dùng cho ngoại lệ và có nhật ký | Biểu mẫu ca bắt buộc người duyệt dự phòng. Trang chủ Chủ quán hiện các ca chưa có; lệnh định kỳ ghi nhắc một lần mỗi ca. Ca cũ còn thiếu thì yêu cầu quá hạn chuyển thẳng Chủ quán, nhật ký ghi rõ "ngoại lệ GD-08" (`test_corrections.BackupApproverTests`) |
| GD-09 | Theo đề xuất: phiếu nhập Trả ngay bằng quỹ ca ghi thành khoản chi Nguyên vật liệu của ca đang mở | Đã có từ đợt trước |
| GD-10 | Giữ lịch sử tham số, nhưng báo cáo vẫn cập nhật theo giao dịch mới và đính chính hợp lệ | Lịch sử chỉ giữ giá trị ngưỡng, thời hạn đã áp dụng. Số liệu báo cáo (đối soát, tích lũy, giá trị kiểm soát tháng) luôn tính lại từ giao dịch và đính chính đang có hiệu lực, không chụp cứng |
| GD-11 | Đính chính báo cáo cuối ca có lý do, người duyệt và lịch sử; đối soát lại theo số liệu có hiệu lực, không tính trùng chênh lệch | Bản gốc giữ nguyên; mỗi đính chính là một bản ghi có lý do, người đề nghị, Chủ quán duyệt hoặc từ chối. Duyệt xong hệ thống đối soát lại: khoản không đổi giữ nguyên, khoản đổi thì bản cũ hết hiệu lực (giữ lịch sử, giải trình, quyết định) và bản mới thay thế; tích lũy và giá trị kiểm soát chỉ đếm khoản đang có hiệu lực (`test_corrections.CorrectionTests`) |
| GD-12 | Theo đề xuất: Chủ quán khai báo ca bằng tay trước khi có lịch ca | Đã có |
| GD-13 | Giữ trạng thái chờ Chủ quán cho phép cài PostgreSQL | Chưa cài. Kiểm thử đồng thời mới đạt trên SQLite; **chưa kết luận đạt trên PostgreSQL** |

### Giả định mới phát sinh, chờ Chủ quán xác nhận

| Mã | Giả định | Lý do |
|---|---|---|
| GD-14 | Quản lý ca đề nghị đính chính thì Chủ quán duyệt; nếu chính Chủ quán đề nghị thì được ghi là tự duyệt ngay, có nhật ký | Quán chỉ có một Chủ quán, không có cấp duyệt cao hơn |
| GD-15 | Không duyệt được đính chính nếu khoản chênh lệch sẽ thay đổi đã là bằng chứng trong vụ việc tổn thất; phải đính chính vụ việc trước | Tránh vụ việc trỏ vào số đã hết hiệu lực và tính trùng tổn thất |
| GD-16 | Khoản hoàn đã duyệt nhưng chưa trả khách không chặn kết ca; nó hiện ở trang Ca của tôi cho đến khi có người bấm "Đã hoàn tiền" | Tiền chưa rời quỹ thì không thuộc ca nào |
| GD-17 | Đơn nhập bù tính tiền theo bảng giá hiện hành lúc nhập bù | Hệ thống chưa lưu lịch sử giá; định mức thì đã theo phiên bản lúc bán |
| GD-18 | Biểu mẫu nhập bù chỉ ghi món, kích cỡ, số ly; chưa ghi tùy chọn | Giữ biểu mẫu ngắn để nhập nhanh; nếu quán hay bán tùy chọn có thêm tiền khi mất mạng thì cần bổ sung |
| GD-20 | Một người được tính có mặt trong khung giờ khi làm ít nhất nửa khung (AC-76: vào 16:55, ra 22:05 được tính 17 đến 22 giờ) | BRD không nêu cách tính khung lẻ |
| GD-21 | Mức món tồn tại quầy cho phép cuối khung giờ: 15 ly (tham số) | BRD không nêu giá trị |
| GD-22 | Cảnh báo đã được người xử lý đóng tay thì không tự mở lại cho cùng đối tượng dù điều kiện còn; cảnh báo "Chênh lệch tiền" chuyển từ Quản lý ca sang Chủ quán khi đã có giải trình | Tránh nhắc lặp cùng một việc đã có kết quả |
| GD-23 | Báo cáo doanh thu tính theo thời điểm thanh toán; "nhân viên" là người tạo đơn; khung giờ theo giờ gửi pha chế | BRD không nói rõ mốc thời gian và người được ghi doanh thu |
| GD-19 | Mỗi dãy phiếu đã cấp cho ca phải khai báo số cuối đã dùng (0 nếu không dùng) trước khi kết ca | Nếu không, hệ thống không biết phiếu cuối bị bỏ sót (AC-13 chỉ phát hiện được số thiếu nằm giữa) |

## 7. Dữ liệu đầu vào cho dự báo (logic dự báo chờ Hai giải thích)

| Dữ liệu | Đang lưu ở | Ghi chú |
|---|---|---|
| Thời điểm nhận đơn | `Order.created_at` | Theo giờ máy chủ, UTC+7 khi hiển thị |
| Thời điểm pha xong | `OrderLine.done_at` (cả dòng xong); từng lần pha một phần: `StockMovement` loại Tiêu hao, `created_at` | |
| Thời điểm mang ra | `OrderLine.served_at`, `served_by` | |
| Số lượng | `OrderLine.quantity`, `done_quantity`, `cancelled_quantity`, `voided_done_quantity` | Tách hủy trước và sau pha chế |
| Định mức đã dùng | `OrderLine.recipe_version`, `usage_per_unit` | Chụp lúc nhận đơn |
| Tiêu hao ghi nhận theo sổ kho | `StockMovement` loại Tiêu hao (theo định mức đã chụp của từng ly pha xong), Hao hụt (có lý do), Hủy sau pha chế (`PostPrepCancellation`) | Là lượng hệ thống tính theo định mức và thao tác ghi nhận, chưa phải lượng thật đã dùng |
| Tiêu hao thực tế tính từ kiểm kê | Tồn kiểm kê đầu kỳ + nhập trong kỳ − tồn kiểm kê cuối kỳ, lấy từ `StockCount` (số đếm được, tồn vật lý lúc đếm) và `StockMovement` loại Nhập | Chỉ tính được giữa hai lần kiểm kê đã áp dụng. Chênh lệch giữa hai dòng này là phần FR-16 đối chiếu (Phần 4) |
| Thiếu nguyên liệu | `ShortageCase` (nguyên liệu, ngày, nguồn) | Tối đa một trường hợp mỗi nguyên liệu mỗi ngày |
| Nhân sự có mặt theo vai trò | `staff.Attendance` (vai trò, vào ca, ra ca); `staff.timekeeping.presence` đếm theo khung giờ | Lượt thiếu giờ ra không được tính cho đến khi Quản lý ca bổ sung |
| Tải và thời gian chờ theo khung giờ | `orders.workload.day_frames` | Đơn nhập bù tính tải theo giờ bán trên phiếu, không tính thời gian chờ |
