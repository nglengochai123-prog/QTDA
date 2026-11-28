# Báo cáo lỗi

Phiên bản kiểm thử: commit `f0e5d30` (bằng `origin/main`). Ngày: 28/11/2026. Chưa sửa lỗi nào: theo yêu cầu, chờ Hai duyệt báo cáo.

Mức độ: **P0** mất tiền, mất hàng, lộ quyền, hỏng dữ liệu; **P1** sai nghiệp vụ chính hoặc có thể gây thất thoát trong tình huống cụ thể; **P2** vận hành, hiệu năng; **P3** thẩm mỹ, cấu hình, test.

| Mã | Mức | Tóm tắt | Ca kiểm thử |
|---|---|---|---|
| BUG-01 | P1 | Sửa giá một cỡ của món Đang bán thành 0 đ vẫn lưu được, món vẫn bán, đơn tổng 0 đ | QA-MD-03 |
| BUG-02 | P1 | Đơn gửi đúng lúc kết ca bị gắn vào ca đã kết, ca kết mà vẫn còn đơn chưa thu | QA-CONC-01 |
| BUG-03 | P2 | Báo cáo Doanh thu mất 7,6–8,4 giây; Bảng điều khiển lần mở đầu 1.082 truy vấn, 14–16 giây | QA-PERF-02 |
| BUG-04 | P2 | Màn Thu ngân tăng khoảng 4 truy vấn cho mỗi bàn chờ thu | QA-PERF-01 |
| BUG-05 | P3 | Ở màn 375px, trang Phiếu nhập và Lịch làm bị tràn ngang | QA-UI-01 |
| BUG-06 | P3 | Một test lịch sẵn có hỏng theo ngày chạy (sau trưa thứ Năm) | QA-ENV-02 |
| BUG-07 | P3 | Cấu hình chạy thật chưa bật HSTS (`check --deploy`) | QA-ENV-03 |

Không tìm thấy lỗi P0. Không có lỗi nào làm lệch sổ tiền hay sổ kho trên dữ liệu hiện có (xem QA-DAY-01, QA-DAY-02).

---

## BUG-01 (P1): giá 0 đ trên món đang bán

- **Tái hiện:** Chủ quán mở Dữ liệu gốc › Món và giá › Cà phê sữa (Đang bán), sửa giá cỡ M từ 25.000 thành 0, bấm Lưu. Phục vụ tạo đơn món đó.
- **Mong đợi:** form báo lỗi như khi mở bán món chưa có giá. Quy tắc đã có trong code: `MenuItem.sale_blockers()` coi giá 0 là "chưa đủ điều kiện mở bán" (BRU-20, AC-47) và `docs/THUC_DON_LAM.md` ghi "Nhập giá rồi mới mở bán".
- **Thực tế:** form trả 302 (đã lưu), giá cỡ M = 0, món vẫn ở trạng thái Đang bán, tạo được đơn tổng tiền 0 đ.
- **Bằng chứng:** `apps/core/tests/test_qa_audit.py::MasterDataTests::test_qa_md_03_price_zero_on_selling_item_via_form`. Phép thử có đối chứng: cùng dữ liệu POST với giá 26.000 lưu được, nên lỗi không do dữ liệu gửi thiếu.
- **Nguyên nhân khả dĩ:** `MenuItem.clean()` (`apps/catalog/models.py:164`) kiểm tra `sale_blockers()` theo các cỡ đang có trong CSDL, tức là giá cũ, trước khi formset kích cỡ được lưu. Giá mới trong formset không được xét.
- **Tác động:** một lần gõ nhầm là bán miễn phí đến khi có người phát hiện; doanh thu, giá vốn và cảnh báo đều sai theo.

## BUG-02 (P1): đơn gửi lúc đang kết ca

- **Tái hiện (PostgreSQL 16):** ca đã xác nhận tiền đầu ca, không còn đơn chờ. Hai luồng cùng lúc: thu ngân bấm Kết ca, phục vụ gửi đơn. Để không phụ thuộc may rủi, test làm chậm bước tính số liệu kết ca 0,8 giây (bọc hàm thật, không đổi logic).
- **Mong đợi:** hoặc kết ca bị chặn vì có đơn mới, hoặc đơn mới không thuộc ca vừa kết.
- **Thực tế:** cả hai thành công. Ca ở trạng thái Đã kết ca, đơn `2811-001` chưa thanh toán nằm trong ca đó.
- **Bằng chứng:** `apps/core/tests/test_qa_concurrency_pg.py::test_qa_conc_01_order_sent_while_shift_closing`.
- **Nguyên nhân khả dĩ:** `submit_order` lấy ca bằng `Shift.objects.operating()` (`apps/orders/services.py:167`), là một lần đọc không khóa. `close_shift` (`apps/shifts/services.py:331`) khóa dòng ca, kiểm tra `close_blockers` rồi mới lưu. Đơn đọc được ca khi ca còn mở, ghi vào sau khi điều kiện kết ca đã được kiểm.
- **Tác động:** thực tế cửa sổ chỉ vài phần nghìn giây nên hiếm, nhưng khi xảy ra thì ca đã kết có đơn treo, tiền đơn đó khi thu sẽ vào ca sau trong khi đơn ghi ca trước, đối soát theo ca khó giải thích. Thanh toán và bút toán quỹ không bị lỗi này vì đã khóa ca (QA-CONC-02, QA-CONC-03 đạt).

## BUG-03 (P2): báo cáo chậm trên dữ liệu vài nghìn đơn

- **Đo trên bản sao dữ liệu mô phỏng** (4.105 đơn, 3.277 thanh toán, 19.193 dòng sổ kho):
  - `/bao-cao/doanh-thu/`: 54 truy vấn nhưng 7,6–8,4 giây. cProfile: phần lớn thời gian ở `apps/reports/receipts.py:_payment_entries` (gọi 3 lần qua `entries`) và `apps/reports/insights.py`.
  - `/bang-dieu-khien/` lần mở đầu sau khi máy chủ khởi động: 1.082 truy vấn, 14–16 giây (516 lần đọc `core_parametervalue`, 399 lần đọc `staff_attendance`). Lần sau: 88 truy vấn, 1,3 giây nhờ bộ đệm.
- **Tác động:** chủ quán mở báo cáo trên điện thoại sẽ chờ lâu; dữ liệu càng nhiều càng chậm.

## BUG-04 (P2): màn Thu ngân N+1

- **Đo:** 1 bàn chờ thu 23 truy vấn, 9 bàn 55 truy vấn. Quầy pha chế (15 → 15) và Tổng quan ca (44 → 44) không tăng.
- **Bằng chứng:** `test_qa_perf_01_no_n_plus_one_on_hot_screens`.

## BUG-05 (P3): tràn ngang ở 375px

- `/kho/phieu-nhap/`: khối `div.form-actions.rc-bar` (thanh tổng phiếu và nút Lưu, `templates/inventory/receipt.html:60`) rộng hơn màn.
- `/lich/`: dải `ol.steps` (`templates/schedule/board.html:21`) rộng hơn màn.
- 127 trang còn lại (4 vai trò) không tràn, không lỗi JavaScript, không lỗi HTTP.

## BUG-06 (P3): test phụ thuộc ngày chạy

Một test của lịch làm trong bộ gốc hỏng khi chạy sau trưa thứ Năm vì so với hạn đăng ký tính theo ngày thật. Không phải lỗi nghiệp vụ, nhưng làm bộ test báo đỏ giả.

## BUG-07 (P3): HSTS

`manage.py check --deploy` với cấu hình chạy thật còn cảnh báo `SECURE_HSTS_SECONDS` chưa đặt. Các cảnh báo còn lại do chạy ở máy cá nhân với DEBUG bật.

---

## Mục cần Hai quyết định (NEEDS SPEC)

| Mã | Hiện trạng | Câu hỏi |
|---|---|---|
| QA-SALE-F | Thu ngân thu được tiền mặt khi ca chưa xác nhận tiền đầu ca; chỉ bị chặn lúc kết ca | **Hai quyết định 28/11: có, bắt buộc xác nhận tiền đầu ca trước lần thu tiền mặt đầu tiên.** Thành lỗi BUG-08 (P2) |
| QA-SALE-G | Nhân viên chưa chấm công, không có trong lịch vẫn tạo đơn được | **Hai quyết định 28/11: chặn tạo đơn khi chưa chấm công.** Thành lỗi BUG-09 (P2) |
| Ghi chú | Mã nghiệp vụ (`OperationRecord`) không gắn với người gửi | Rủi ro thấp vì mã là chuỗi ngẫu nhiên 32 ký tự; ghi lại để biết |

---

## Kết quả sửa (28/11/2026, sau khi Hai duyệt)

| Mã | Trạng thái | Cách sửa | Kiểm lại |
|---|---|---|---|
| BUG-01 | Đã sửa | Form Món và giá kiểm giá sau khi lưu dòng kích cỡ (`Resource.validate_saved`); thêm chốt ở lúc bán: dòng có giá 0 bị từ chối | QA-MD-03 đạt |
| BUG-02 | Đã sửa | `Shift.objects.operating_locked()` khóa dòng ca và đọc lại trạng thái trước khi ghi đơn, thanh toán, thu trước, thu thêm, hoàn tiền | QA-CONC-01 đạt trên PostgreSQL |
| BUG-03 | Đã sửa | Đệm trong một yêu cầu GET cho tham số và sổ phân bổ doanh thu; chỉ đọc dòng món cho khoản thu chưa có sổ phân bổ; chấm công đọc một lần cho cả ngày; tính sẵn giờ bán và phiếu dự phòng mỗi dòng | Doanh thu 8,4 s → 1,2 s; Bảng điều khiển lần đầu 1.082 → 276 truy vấn, 16 s → 4,2 s; lần sau 0,5 s |
| BUG-04 | Đã sửa | Thu ngân đọc mọi đơn chờ và yêu cầu chờ duyệt một lần | QA-PERF-01 đạt; 20 truy vấn |
| BUG-05 | Đã sửa | Lề trang điện thoại 0,875rem khớp các thanh tràn mép | 375px: /kho/phieu-nhap/, /lich/ không tràn |
| BUG-06 | Đã sửa | Test lịch cố định lúc xem trước hạn đăng ký | Đạt mọi ngày |
| BUG-07 | Đã sửa | `SECURE_HSTS_SECONDS` mặc định 1 năm khi chạy thật (`DJANGO_HSTS_SECONDS` để đổi) | |
| BUG-08 | Đã làm | Thu tiền mặt (thu sau, thu trước, thu thêm) cần ca đã ghi tiền đầu ca; chuyển khoản không cần | QA-SALE-F, F2 |
| BUG-09 | Đã làm | Màn Tạo đơn chặn người chưa Vào ca (Chủ quán được miễn; gửi lại đơn đã nhận vẫn trả đúng đơn); hiện thông báo kèm liên kết Chấm công | QA-SALE-G |
| BUG-10 (mới) | Đã sửa | Trên PostgreSQL, Hoàn tất đơn thu trước và Chuyển đơn sang ca sau báo lỗi máy chủ ("FOR UPDATE cannot be applied to the nullable side of an outer join"). Chỉ thấy khi chạy đủ bộ test trên PostgreSQL. Sửa: khóa riêng dòng chính (`select_for_update(of=("self",))`) ở 12 chỗ | 629/629 test đạt trên PostgreSQL |

Bộ test sau khi sửa: 629 test, đạt toàn bộ trên SQLite và PostgreSQL 16. Các test cũ thu tiền mặt hoặc gửi đơn qua màn hình được bổ sung bước ghi tiền đầu ca hoặc Vào ca (`confirm_opening`, `clock_in` trong `apps/orders/tests/helpers.py`), không bỏ kiểm tra nào.
