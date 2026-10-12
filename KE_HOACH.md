# Kế hoạch code LAM Coffee System

Công nghệ theo BRD: Python/Django, một ứng dụng web cài lên màn hình chính điện thoại (PWA) và Web Push.
Máy chạy thử: SQLite trên máy cá nhân (PyCharm). Khi triển khai thật có thể chuyển sang PostgreSQL mà không đổi mã.

Mỗi phần là một lát cắt chạy được từ đầu đến cuối, làm xong phần trước mới sang phần sau, đúng thứ tự Sprint ở Bảng 9.1.

> **BẢN HIỆN HÀNH.** Đây là bản kế hoạch và tiến độ đúng, nằm tại `D:\QTDA\KE_HOACH.md` cùng mã nguồn.
> Mọi bản `KE_HOACH*.md` khác trong thư viện dự án là bản cũ; bản `KE_HOACH.md` gốc đánh dấu sai Phần 1 đã xong. Không dùng chúng để đọc tiến độ.

## Trạng thái nghiệm thu (cập nhật 12/10/2026, cuối ngày)

Ba trạng thái: **đã nghiệm thu nội bộ** (đã thao tác qua giao diện hoặc đối chiếu trên bộ dữ liệu nghiệm thu, không chỉ dựa vào kiểm thử tự động), **đã làm, chờ Hai nghiệm thu** (cần thiết bị, quyết định hoặc rà soát của Hai), **chưa làm** (kèm lý do). Kiểm thử tự động: 188 bài, đạt trên SQLite và PostgreSQL 16 (một bài chỉ chạy trên SQLite). Số bài kiểm thử không phải bằng chứng hoàn thành. Bảng đối chiếu cuối cùng theo từng yêu cầu ở `docs/DOI_CHIEU_YEU_CAU.md` mục 9.

### Đã nghiệm thu nội bộ

- Đăng nhập, phân quyền 5 vai trò, trang 403 và nhật ký từ chối quyền — tự động và trình duyệt
- Nhận đơn trên điện thoại, quầy pha chế, món sẵn sàng, thu ngân — tự động và trình duyệt
- Điều chỉnh đơn và duyệt, hủy hóa đơn đã thanh toán, duyệt hoàn và xác nhận đã hoàn — tự động
- Nhập hàng, kiểm kê, quỹ ca, kết ca, chuyển đơn sang ca sau, báo cáo cuối ca và đối soát, đính chính — tự động và trình duyệt
- Phiếu dự phòng có kích cỡ, tùy chọn, giá lịch sử, chờ Chủ quán xác nhận — tự động và trình duyệt
- Bảng điều khiển, báo cáo doanh thu, kiểm soát, nguyên vật liệu, xuất Excel (Excel mở được, số khớp) — trình duyệt trên bộ dữ liệu 14 ngày
- **Mới 12/10:** Tra cứu đơn có bộ lọc, phân trang, chi tiết đơn; Sổ kho có bộ lọc, tổng, liên kết sang đơn; lọc và phân trang Ngoại lệ, Vụ việc
- **Mới 12/10:** Truy vết từ số tổng hợp tới giao dịch: 64/64 dòng báo cáo doanh thu ở 7 chiều mở đúng số đơn; 11/11 số liệu báo cáo nguyên vật liệu khớp tổng sổ kho; số trên bảng điều khiển mở được danh sách cấu thành; danh sách báo Sắp hết trên bảng điều khiển
- **Mới 12/10:** Đề nghị kiểm kê lại từ màn tạo đơn (AC-03), kiểm kê nhóm trọng yếu trước giờ mở cửa hôm sau (FR-09) — tự động
- **Mới 12/10:** Lưu nháp biểu mẫu trên thiết bị kèm mã nghiệp vụ, khôi phục sau tải lại; chặn thanh toán, phê duyệt, xem xét khi mất kết nối (NFR-16) — trình duyệt
- **Mới 12/10:** 24 trang chính ở bề rộng 375 px không có cuộn ngang (NFR-15) — trình duyệt
- **Mới 12/10:** Sao lưu và phục hồi vào CSDL riêng trên SQLite và PostgreSQL, CSDL đang chạy không bị đụng (NFR-09) — lệnh thật, `docs/VAN_HANH.md` mục 6
- Đối chiếu chéo `kiem_tra_toan_ven` không báo sai lệch trên SQLite, PostgreSQL và bản phục hồi
- Kiểm thử đồng thời trên PostgreSQL 16 (5 tình huống)

### Đã làm, chờ Hai nghiệm thu

- Thông báo đẩy trên điện thoại thật (NFR-17): máy chủ gửi được; **tạm hoãn theo yêu cầu của Hai**, đường hầm đã tắt. Thông báo đẩy nay gửi cho cảnh báo, yêu cầu phê duyệt, báo cáo cuối ca, ca thiếu người duyệt dự phòng
- In phiếu pha chế trên máy in thật của quầy (NFR-11): trang phiếu đã xem trên trình duyệt
- Nội dung thông báo xử lý dữ liệu cá nhân (NFR-13): bản dự thảo cần Hai rà soát pháp lý
- Lên lịch tác vụ định kỳ mỗi phút và sao lưu hằng ngày trên máy vận hành, chọn thư mục sao lưu ngoài máy (`docs/VAN_HANH.md` mục 2 và 6): tạo lịch là thay đổi cấu hình máy nên để Hai tự chạy lệnh
- Tự nghiệm thu toàn bộ theo `docs/VAN_HANH.md` mục 1

### Chưa làm

- Dự báo nhu cầu (FR-28), cảnh báo Cần đặt hàng (FR-29), đề xuất số lượng đặt (FR-31), cột nhu cầu ước tính trong báo cáo nguyên vật liệu (FR-54): **chờ Hai hướng dẫn logic dự báo**
- Đo NFR-02, NFR-05, NFR-10 và diễn tập mất mạng thật: cần mạng, thiết bị, máy chủ thật ở tuần chạy thử
- Các chức năng mức Should, Could của Giai đoạn 2, 3 (in hóa đơn FR-05, lịch ca, lương, BO-03...): ngoài phạm vi đợt này
- Nhập dữ liệu thật của quán (nhân viên, thực đơn, giá, tồn đầu kỳ): chờ Hai

## Tiến độ theo phần

Trước ngày 11/10/2026 thư mục D:\QTDA chưa có mã nguồn; các mục Phần 1 từng đánh dấu đã xong là chưa đúng.

Mã nguồn được quản lý bằng Git trong `D:\QTDA` (nhánh main, chưa có kho từ xa).

### Rà soát tích hợp Phần 1–3 (11/10/2026, xong)

- [x] Bộ tài liệu chuẩn: `BAO CAO SPRINT 1.docx` là tài liệu yêu cầu chính thức (BRD đã chỉnh sửa, Hai xác nhận) quyết định chức năng và quy tắc; PRODUCT.md bối cảnh; DESIGN.md giao diện; KE_HOACH.md tiến độ; `docs/DOI_CHIEU_YEU_CAU.md` đối chiếu, giả định và quyết định chờ Chủ quán
- [x] AC-55, FR-24: phiếu nhập luôn cần ảnh hóa đơn; bỏ ngưỡng 500.000 đ tự đặt cho phiếu nhập (500.000 đ của BRU-33 chỉ áp cho khoản chi tiền mặt)
- [x] Hoàn tiền khi hủy hóa đơn đã thanh toán: theo phương thức khách đã trả, ghi vào ca đang mở, mỗi yêu cầu tối đa một khoản, trừ một lần khi đối soát; không có ca mở thì chưa duyệt được (GD-07)
- [x] Một nơi xử lý dùng chung: mọi thay đổi tồn kho qua `stock.move`; đơn, điều chỉnh, thanh toán, hoàn tiền, nhập, kiểm kê, hao hụt, vụ việc đều qua hàm nghiệp vụ (bảng ở mục 2 tài liệu đối chiếu)
- [x] Chống ghi trùng cho cả thanh toán nhà cung cấp, ghi đặt hàng, lập vụ việc, thu hồi, xác minh, báo cáo cuối ca, quyết định chênh lệch
- [x] Tham số có lịch sử và thời điểm hiệu lực; yêu cầu điều chỉnh giữ thời hạn lúc tạo; chênh lệch ca lưu ngưỡng đã dùng; kiểm kê lưu ngưỡng %; trang Tham số hiện căn cứ và giá trị giả định
- [x] Kiểm tra quá hạn tách khỏi việc mở màn hình: cấp duyệt, giao chậm tính khi đọc; lệnh `chay_dinh_ky` ghi trạng thái và nhật ký
- [x] Kiểm thử luồng xuyên suốt nhập hàng → báo cáo cuối ca; lệnh `kiem_tra_toan_ven` đối chiếu chéo sổ kho, đơn, tiền, ca
- [x] Thực hiện quyết định của Chủ quán (11/10/2026): hoàn tiền hai bước duyệt và đã hoàn (GD-07); bắt buộc người duyệt dự phòng, nhắc trước ca, chuyển thẳng Chủ quán chỉ là ngoại lệ có nhật ký (GD-08); đính chính báo cáo cuối ca có lý do, người duyệt, lịch sử, đối soát lại không trùng (GD-11); mục tiêu BO-01 tách khỏi ngưỡng cảnh báo toàn quán; báo cáo tính lại theo giao dịch và đính chính (GD-10)
- [ ] Kiểm tra hai đơn đồng thời trên PostgreSQL: máy chưa cài, chờ Hai cho phép (GD-13); chưa kết luận đạt
- [ ] Lên lịch chạy `chay_dinh_ky` mỗi phút khi triển khai (hướng dẫn `docs/VAN_HANH.md`)

### Nền tảng (xong)

- [x] Khung Django 5.2 trong .venv: cấu hình đọc biến môi trường, SQLite chạy thử, sẵn sàng chuyển PostgreSQL
- [x] Tiếng Việt, giờ UTC+7, tiền có dấu chấm phân cách nghìn; mật khẩu tối thiểu 8 ký tự; tự đăng xuất sau 15 phút không thao tác
- [x] Cửa hàng và lớp model nền có mã cửa hàng (NFR-18)
- [x] Đăng nhập, đăng xuất (chỉ bằng POST), tạm khóa sau 5 lần sai mật khẩu trong 15 phút, Chủ quán khóa và mở tài khoản
- [x] Ma trận phân quyền Bảng 5.3 kiểm tra tại máy chủ cho cả 5 vai trò; bị từ chối thì ghi nhật ký (AC-111); trang dữ liệu nền chỉ Chủ quán (AC-114)
- [x] PWA tối thiểu (manifest, service worker, trang mất kết nối), dải cảnh báo mất kết nối trong 10 giây, /healthz/
- [x] PRODUCT.md, DESIGN.md (từ 12/10/2026: phong cách quản trị vuông vức theo UI UX Pro Max, thay định hướng tạm vở ô ly); giao diện đăng nhập, bố cục chung, tạo đơn, quầy pha chế, tồn kho
- [x] Lệnh `tao_du_lieu_mau` tạo dữ liệu mẫu để chạy thử (không phải thực đơn thật)

## Phần 1: Nền tảng và luồng bán hàng cốt lõi (Sprint 1, đã xong trừ các mục còn mở)

- [x] Tài khoản 5 vai trò, phân quyền Bảng 5.3 tại máy chủ (FR-59)
- [x] Nhật ký thao tác chỉ thêm mới, chặn sửa xóa ở model và trigger CSDL, tra cứu cho Chủ quán (FR-61, BRU-40, AC-115)
- [x] Hồ sơ nhân viên: nhiều vai trò, đơn giá lương giờ, tài khoản riêng; nghỉ việc thì khóa tài khoản ngay (FR-34, BRU-38, AC-74, AC-75)
- [x] Danh mục bàn, nhóm món và hệ số tải, món, kích cỡ và giá, nhóm tùy chọn và tùy chọn (FR-60)
- [x] Nguyên vật liệu, nhà cung cấp, mức tồn an toàn tạm thời (FR-20, AC-44, AC-45)
- [x] Định mức có phiên bản theo kích cỡ và tùy chọn; bản đã áp dụng không sửa được; chỉ mở bán món đủ định mức (FR-21, BRU-20, BRU-39, AC-46, AC-47)
- [x] Tồn đầu kỳ và sổ biến động kho chỉ thêm mới (nguyên liệu, số lượng, nguồn nghiệp vụ, người thực hiện, thời điểm)
- [x] Tồn vật lý, đang giữ và tồn có thể dùng, cập nhật cùng giao dịch với mỗi biến động; màn hình Tồn kho (FR-22, BRU-18, AC-48)
- [x] Tạo đơn theo bàn trên điện thoại: món, kích cỡ, tùy chọn, ghi chú; số ly còn đáp ứng tính theo cỡ, tùy chọn đang chọn và các món đã có trong phiếu; nháp lưu trên máy (FR-01, AC-02, AC-03 phần hiển thị)
- [x] Đơn bị từ chối vì thiếu: báo từng món còn đáp ứng bao nhiêu ly và nguyên liệu nào thiếu (AC-04)
- [x] Mất phản hồi: hiện mã nghiệp vụ để gửi lại hoặc ghi lên phiếu dự phòng (BRU-03, NFR-16)
- [x] Gửi pha chế: máy chủ kiểm tra và giữ nguyên liệu cho cả đơn trong một giao dịch, thiếu thì không nhận và báo thiếu gì; hai đơn đồng thời không giữ cùng phần tồn (FR-02, BRU-20, NFR-04; có kiểm thử hai luồng đồng thời)
- [x] Dòng món lưu giá, tùy chọn và phiên bản định mức lúc nhận; đổi giá hay định mức không ảnh hưởng món đang chờ (BRU-39, AC-46, AC-114)
- [x] Khóa đơn sau khi gửi (FR-10); màn hình quầy pha chế tự cập nhật 2 giây, có giờ gửi; Xong 1 ly hoặc cả dòng, trừ tồn vật lý và bỏ phần giữ đúng một lần (FR-02, FR-03, AC-05 phần hiển thị, AC-48)
- [x] In phiếu pha chế qua trình duyệt: mã đơn, món, tùy chọn, số lượng, bàn, ghi chú, thời điểm; tùy chọn tự in khi có đơn mới (FR-02, AC-05)
- [x] Vòng đời đơn Đã gửi pha chế → Đã pha chế → Đã phục vụ; phục vụ thấy món đã pha xong kèm số bàn và bấm Đã mang ra; chặn thanh toán khi chưa phục vụ (FR-03, BRU-02, AC-06, AC-07)
- [x] Mã nghiệp vụ cho mỗi yêu cầu thay đổi dữ liệu: gửi lại sau mất phản hồi trả kết quả cũ, cùng mã khác nội dung bị từ chối (NFR-04)
- [x] Ca làm việc tối thiểu: Chủ quán khai báo ca, người duyệt trong ca, người duyệt dự phòng, người được ủy quyền thanh toán; đơn và thanh toán gắn ca hiện tại (BRU-01, BRU-09, FR-59 phần ca)
- [x] Thanh toán theo bàn bằng tiền mặt hoặc chuyển khoản (chỉ khi đã thấy tiền về); chỉ khi mọi đơn đã phục vụ và không có yêu cầu chờ duyệt, báo rõ đang chờ cấp nào; gửi lại không ghi hai lần (FR-04, BRU-04, AC-07, AC-08, AC-09)
- [x] Thanh toán theo món thực nhận khi yêu cầu quá hạn mọi cấp: chỉ người được ủy quyền, không phải người tạo yêu cầu; tiền tính theo giá bán; yêu cầu Chờ hậu kiểm và tạo ngoại lệ cho Chủ quán (AC-10)
- [x] Yêu cầu điều chỉnh có lý do bắt buộc: hủy món, giảm số lượng, đổi món, chuyển bàn hoặc gộp bàn, hủy hóa đơn đã thanh toán (FR-10, BRU-08, AC-19, AC-20)
- [x] Phê duyệt trên điện thoại; không tự duyệt; hủy hóa đơn chỉ Chủ quán; quá 3 phút chuyển người duyệt dự phòng, rồi Chủ quán; cấp hiện hành tính khi đọc, mỗi lần chuyển ghi nhật ký khi chạy `chay_dinh_ky` (FR-11, BRU-09, AC-22, AC-23, AC-24)
- [x] Duyệt hủy món chờ pha trả lại tồn có thể dùng; món đã pha ghi Hủy sau pha chế, không trừ kho lần nữa (BRU-19, AC-21, AC-49)
- [x] Ca phải có người duyệt dự phòng; nhắc Chủ quán trên trang chủ và qua lệnh định kỳ (AC-113, GD-08); thông báo đẩy làm cùng NFR-17
- [ ] Kiểm kê nhanh khi thiếu nguyên liệu rồi gửi lại (AC-03 phần kiểm kê): làm ở Phần 3
- [ ] Đo thời gian đơn hiện ở quầy dưới 3 giây trên mạng thật của quán (NFR-02): đo ở tuần chạy thử
- [ ] Web Push đến điện thoại khi ứng dụng đóng (NFR-17); hiện đã báo trong ứng dụng khi đang mở

## Phần 2: Ca, tiền và kiểm soát doanh thu (Sprint 2, phần ca và tiền đã xong)

- [x] Tham số quản trị sửa được trên ứng dụng, có hiệu lực ngay hoặc từ thời điểm chọn, giữ lịch sử, ghi nhật ký (NFR-14); giá trị giả định được đánh dấu chờ Chủ quán xác nhận
- [x] Quỹ tiền mặt ca: tiền đầu ca, chi kèm danh mục, khoản từ 500.000 đ phải có ảnh chứng từ, nộp giữa ca chỉ có hiệu lực khi người nhận xác nhận (FR-07, BRU-05, AC-14, AC-15)
- [x] Kết ca: chặn khi còn đơn chưa thanh toán, yêu cầu chờ duyệt, chưa có tiền đầu ca hoặc khoản nộp chưa xác nhận; chuyển đơn sang ca sau kèm lý do; chốt doanh thu theo phương thức (FR-08, BRU-06, AC-16)
- [x] Báo cáo cuối ca: tiền mặt đếm, chuyển khoản nhận và hoàn theo sao kê, sự cố; gửi xong đối soát ngay (FR-08, AC-17)
- [x] Đối soát theo công thức BRU-10, lưu mọi chênh lệch khác 0 theo ca, phương thức, Quản lý ca; vượt ngưỡng phải giải trình, Chủ quán Chấp nhận hoặc Không chấp nhận (FR-12, AC-25, AC-26, AC-27)
- [x] Hoàn tiền khi hủy hóa đơn đã thanh toán: Chủ quán duyệt, thu ngân xác nhận đã hoàn; theo phương thức khách đã trả, gắn thanh toán gốc, tiền ra ghi vào ca thực hoàn, trừ một lần trong đối soát (BRU-05, BRU-10, AC-27, GD-07)
- [x] Đính chính báo cáo cuối ca có lý do, Chủ quán duyệt, giữ lịch sử; đối soát lại không tính trùng (GD-11)
- [x] Chênh lệch tích lũy theo Quản lý ca, loại ca, tháng và toàn quán; vượt ngưỡng tạo ngoại lệ gắn các ca (FR-13, BRU-11, AC-28)
- [x] Tình trạng dữ liệu ca: chưa kết ca, thiếu báo cáo cuối ca quá hạn 2 giờ (FR-09, BRU-07, AC-18)
- [ ] Tình trạng kiểm kê nhóm trọng yếu trước giờ mở cửa hôm sau (BRU-07, FR-09): chưa làm, làm cùng Phần 4
- [x] Báo cáo điều chỉnh theo ca: người tạo, người duyệt, lý do, kết quả, giá trị món; tách bị từ chối và hủy sau thanh toán; tổng hủy sau pha chế (FR-14, AC-29)
- [x] Ngoại lệ tự động theo BRU-12: điều chỉnh sau pha chế bị từ chối, hủy hóa đơn đã thanh toán, vượt số điều chỉnh của nhân viên trong ca (một ngoại lệ mở, yêu cầu sau gắn vào), vượt giá trị hủy sau pha chế của ca, thanh toán theo món thực nhận, chênh lệch tích lũy (FR-15, AC-30, AC-31)
- [x] Xem xét ngoại lệ chỉ Chủ quán: Hợp lệ, Nhắc nhở, Vi phạm; có tổn thất tiền phải gắn vụ việc trước; kết quả không sửa, chỉ đính chính; nhắc lại sau 3 ngày; xem chuỗi thao tác và lịch sử nhân viên (FR-17, BRU-14, AC-35, AC-36, AC-37)
- [x] Vụ việc tổn thất mã VV-xxx: bằng chứng là ngoại lệ hoặc khoản chênh lệch, mỗi thứ thuộc tối đa một vụ việc, cùng giao dịch chỉ tính một lần; xác minh, đính chính có lý do, thu hồi, còn lại (FR-18, BRU-15, AC-38, AC-39)
- [x] Giá trị kiểm soát tạm tính của tháng so với mục tiêu 200.000 đ (BRU-16)
- [ ] Ngoại lệ phiếu dự phòng (BRU-03) và chênh lệch kiểm kê tích lũy (BRU-25): làm cùng Phần 3, Phần 4
- [x] Giao cảnh báo theo Bảng 5.4 có thời hạn và chuyển cấp (BRU-36): trung tâm cảnh báo FR-51

## Phần 3: Nguyên vật liệu vận hành (Sprint 2, đã xong phần không cần dự báo)

- [x] Báo nhanh Sắp hết, Đã hết trên điện thoại kèm lượng còn lại; Quản lý ca và Chủ quán thấy dải báo ngay và ghi đã xử lý (FR-23, AC-51)
- [x] Phiếu nhập: số lượng thực nhận, đơn giá, ảnh hóa đơn bắt buộc với mọi phiếu, Trả ngay hoặc Trả sau, liên kết lần đặt; tăng tồn vật lý; gửi lại không ghi trùng (FR-24, BRU-33, AC-52, AC-53, AC-55)
- [x] Khoản phải trả và thanh toán từng phần; Trả ngay bằng tiền mặt quỹ ca ghi thành chi tiền mặt của ca (FR-24, BRU-33, AC-54)
- [x] Kiểm kê: trong ngưỡng 5% điều chỉnh ngay; vượt ngưỡng phải ghi lý do và chờ Chủ quán xác nhận; điều chỉnh theo chênh lệch lúc đếm nên không làm lệch phần đang giữ (FR-25, BRU-25, AC-56, AC-57)
- [x] Chênh lệch kiểm kê tích lũy tháng theo nguyên liệu vượt ngưỡng tạo ngoại lệ kèm người kiểm kê (BRU-25, AC-58)
- [x] Hao hụt xuất kho có lý do bắt buộc, giảm tồn vật lý; hủy sau pha chế tự ghi từ yêu cầu điều chỉnh, không trừ lần nữa (FR-26, BRU-19, AC-59, AC-60)
- [x] Trường hợp thiếu nguyên liệu: báo Đã hết trong giờ mở cửa, đổi hoặc hủy món vì Hết nguyên liệu được duyệt, khách đổi món sau cảnh báo khi tạo đơn; mỗi nguyên liệu tối đa một trường hợp mỗi ngày (FR-27, BRU-26, AC-61, AC-62, AC-63)
- [x] Ghi nhận đặt hàng, theo dõi Đã đặt, Giao một phần, Đã giao đủ, Giao chậm; lô giao chậm không tính là hàng đang về đến khi có ngày giao mới (FR-30, BRU-23, AC-68, AC-69)
- [x] Báo cáo nguyên vật liệu tháng: hao hụt theo lý do, hủy sau pha chế, kiểm kê, trường hợp thiếu theo ngày và nguyên liệu
- [ ] Đề xuất số lượng đặt hàng (FR-31, BRU-24) và cảnh báo cần đặt hàng (FR-29, BRU-22): chờ Hai giải thích logic dự báo
- [x] Cảnh báo khoản phải trả đến hạn và giao chậm có thời hạn, nhắc lại hằng ngày theo Bảng 5.4: trong trung tâm cảnh báo (FR-51)

## Phần 4: Dự phòng, ước tính, nhân sự, báo cáo (Sprint 3, đã xong phần không cần dự báo)

Bán hàng dự phòng và nhập bù (FR-06); đối chiếu tiêu hao trọng yếu (FR-16); ước tính nhu cầu theo giai đoạn, cảnh báo cần đặt hàng (FR-28, FR-29); hồ sơ nhân viên, chấm công, đo tải và thời gian chờ (FR-34, FR-35, FR-36); bảng điều khiển, trung tâm cảnh báo, báo cáo doanh thu, kiểm soát doanh thu, nguyên vật liệu, xuất Excel (FR-50 đến FR-54).

- [x] Bán hàng dự phòng và nhập bù (FR-06, BRU-03, AC-12, AC-13): dãy phiếu theo ca, nhập bù liên kết đơn đã lưu hoặc tạo đơn theo định mức lúc bán, ngoại lệ số trùng, ngoài dãy, quá hạn, hủy; chặn kết ca khi còn số chưa xử lý; màn hình /du-phong/
- [x] Đối chiếu tiêu hao nguyên liệu trọng yếu giữa hai lần kiểm kê, ngoại lệ khi vượt mức cho phép, kết quả trong báo cáo nguyên vật liệu (FR-16, BRU-17, AC-32, AC-33, AC-34)
- [x] Chấm công vào ca, ra ca theo vai trò; thiếu giờ ra không tính giờ, Quản lý ca bổ sung kèm lý do (FR-35, BRU-31, AC-76 đến AC-78)
- [x] Tải và thời gian chờ theo khung giờ, đánh dấu quá tải, số người có mặt theo vai trò (FR-36, BRU-27, AC-79)
- [x] Trung tâm cảnh báo theo Bảng 5.4: giao người xử lý chính, thời hạn tham số, Mới, Đang xử lý, Đã đóng, tự đóng, đóng tay có ghi chú, chuyển cấp hoặc nhắc lại, thống kê tuần (FR-51, BRU-36, AC-102, AC-103); chưa có "Cần đặt hàng" (chờ dự báo)
- [x] Bảng điều khiển (FR-50, AC-100, AC-101), báo cáo kiểm soát doanh thu (FR-52, AC-104), báo cáo doanh thu có xuất Excel (FR-53, AC-105), báo cáo nguyên vật liệu theo kỳ (FR-54, AC-106; cột nhu cầu ước tính chờ dự báo)
- [x] Giao diện quản trị vuông vức theo UI UX Pro Max (DESIGN.md 12/10/2026): token màu mới, góc 2px, không bóng, điều hướng theo nhóm nghiệp vụ, bảng điều khiển tách phần ca (Quản lý ca) và chỉ tiêu (Chủ quán); đã rà soát lại các màn hình Phần 1–3 và Phần 4 trên máy tính và điện thoại
- [x] Nhập bù có kích cỡ, tùy chọn; giá theo lịch sử giá và định mức theo thời điểm bán; thiếu lịch sử thì chờ Chủ quán xác nhận (12/10/2026)
- [x] Thông báo đẩy: đã cài pywebpush, khóa VAPID, gửi cho cảnh báo, phê duyệt, báo cáo cuối ca, ca thiếu người duyệt dự phòng; thử trên điện thoại thật tạm hoãn, chờ Hai
- [x] PostgreSQL 16 để kiểm thử, kiểm thử đồng thời 5 tình huống (GD-13)
- [x] Hoàn thiện 12/10/2026: đề nghị kiểm kê lại (AC-03), kiểm kê trọng yếu trước giờ mở cửa (FR-09), thông báo dữ liệu cá nhân (NFR-13), nháp biểu mẫu và chặn thao tác khi mất mạng (NFR-16), tra cứu đơn, chi tiết đơn, sổ kho, lọc và phân trang ngoại lệ, vụ việc, truy vết từ bảng điều khiển và báo cáo tới giao dịch (NFR-19), danh sách Sắp hết, sao lưu và phục hồi (NFR-09), mẫu cấu hình máy chủ thật, hướng dẫn khởi động, dừng
- [ ] Còn lại của Phần 4: dự báo (chờ Hai); đo NFR-02, NFR-10, diễn tập mất mạng trong tuần chạy thử


## Chờ Hai giải thích

- Logic dự báo: ước tính nhu cầu theo giai đoạn (FR-28, BRU-21), cảnh báo cần đặt hàng (FR-29, BRU-22) và các phần phụ thuộc. Hai sẽ phổ biến cách tính sau; chưa làm.

## Sau Go-Live

Giai đoạn 2 (12 Should) và Giai đoạn 3 (10 Could) theo Bảng 8.4, chỉ làm khi phần Trước Go-Live chạy ổn.
