# Cách hoạt động của các chức năng — LAM Coffee System

Tài liệu này giải thích hệ thống chạy như thế nào, theo đúng mã nguồn hiện tại (nhánh `hoan-thien-loi-chuc-nang`, 26/10/2026). Mỗi mục trả lời bốn câu: ai dùng, mở ở đâu, hệ thống làm gì từng bước, và dữ liệu nào được ghi lại. Mã yêu cầu (FR, BRU, AC, GD) lấy theo Báo cáo Sprint 1 và `docs/DOI_CHIEU_YEU_CAU.md`.

Mục lục

1. Bức tranh chung
2. Tài khoản, vai trò và phân quyền
3. Ca làm việc
4. Bán hàng: tạo đơn, pha chế, phục vụ
5. Điều chỉnh đơn và phê duyệt
6. Thanh toán
7. Quỹ tiền ca, kết ca, báo cáo cuối ca, đối soát
8. Bán hàng dự phòng khi mất mạng
9. Kho: tồn, nhập hàng, kiểm kê, hao hụt, báo nhanh, đặt hàng, lô hàng và hạn dùng
10. Ngoại lệ, vụ việc tổn thất và giá trị kiểm soát
11. Trung tâm cảnh báo
12. Chấm công, tải công việc, lịch làm
13. Dự báo nhu cầu và kế hoạch mua nguyên liệu
14. Bảng điều khiển và báo cáo
15. Dữ liệu nền, tham số, nhật ký
16. Tác vụ định kỳ, sao lưu, kiểm tra toàn vẹn
17. Những cơ chế chạy ngầm cần biết
18. Thay đổi trong đợt rà soát 25/10/2026
19. Chạy thử bằng mô phỏng và đổi mô hình ra quyết định
20. Kho theo lô, báo cáo nhiều biểu đồ và giao diện mới

---

## 1. Bức tranh chung

Hệ thống là một ứng dụng web Django, mở được trên máy tính quầy và cài lên màn hình chính điện thoại (PWA). Một vòng bán hàng đi như sau:

```
Phục vụ tạo đơn ──► hệ thống giữ nguyên liệu, khóa đơn ──► Quầy pha chế bấm Xong (trừ kho)
       │                                                          │
       │ cần sửa? ─► Yêu cầu điều chỉnh ─► Chủ quán duyệt          ▼
       │                                                  Phục vụ bấm Đã mang ra
       ▼                                                          │
Thu ngân thu tiền cả bàn ◄────────────────────────────────────────┘
       │
       ▼
Kết ca ─► Báo cáo cuối ca ─► Đối soát tự động ─► Chênh lệch, ngoại lệ, cảnh báo ─► Chủ quán xem xét
```

Ba nguyên tắc chạy xuyên suốt:

- **Đơn khóa ngay khi gửi.** Không ai sửa trực tiếp món, giá, số ly của đơn đã gửi; mọi thay đổi phải qua yêu cầu điều chỉnh có lý do và người duyệt. Mã chặn ở tầng dữ liệu (`OrderLine.save` từ chối mọi thay đổi không phải cập nhật tiến độ).
- **Mỗi thao tác chỉ ghi một lần.** Mỗi biểu mẫu mang một *mã nghiệp vụ* sinh sẵn. Mất mạng rồi bấm gửi lại với cùng mã thì hệ thống trả kết quả cũ, không tạo bản ghi thứ hai (`apps/core/idempotency.py`, NFR-04).
- **Mọi thay đổi đều có vết.** Nhật ký thao tác chỉ thêm mới, không sửa, không xóa; cơ sở dữ liệu có trigger chặn sửa xóa (`apps/audit`).

## 2. Tài khoản, vai trò và phân quyền

**Vai trò đang dùng:** Chủ quán, Thu ngân, Phục vụ, Pha chế. Vai trò Quản lý ca của BRD đã bỏ theo quyết định GD-27 (12/10/2026): Chủ quán trực tiếp quản lý ca. Tài khoản cũ mang vai trò này được giữ để tra cứu nhưng không còn quyền nào.

**Cách kiểm quyền:** `apps/accounts/permissions.py` chứa bảng quyền theo Bảng 5.3. Mỗi màn hình khai báo quyền nó cần; máy chủ kiểm tra trước khi chạy, không chỉ ẩn nút. Bị từ chối thì trả trang 403 và ghi nhật ký "Từ chối quyền" (AC-111), kể cả khi giao dịch của yêu cầu bị hủy.

| Việc | Chủ quán | Thu ngân | Phục vụ | Pha chế |
|---|:-:|:-:|:-:|:-:|
| Tạo đơn, gửi yêu cầu điều chỉnh | ✓ | ✓ | ✓ | |
| Quầy pha chế | ✓ | | | ✓ |
| Duyệt điều chỉnh, hủy hóa đơn đã thu | ✓ | | | |
| Thu tiền, quỹ ca, kết ca, báo cáo cuối ca | ✓ | ✓ | | |
| Báo nhanh, nhập hàng, kiểm kê, hao hụt | ✓ | | | ✓ |
| Chấm công | | ✓ | ✓ | ✓ |
| Đăng ký ca | | ✓ | ✓ | ✓ |
| Báo cáo, dự báo, ngoại lệ, dữ liệu nền, tham số, nhật ký | ✓ | | | |

**Đăng nhập:** mật khẩu tối thiểu 8 ký tự; sai 5 lần trong 15 phút thì tạm khóa; tự đăng xuất sau 15 phút không thao tác; đăng xuất chỉ bằng nút (POST). Chủ quán khóa và mở tài khoản ở Quản trị › Nhân viên. Nhân viên chuyển Nghỉ việc thì tài khoản bị khóa ngay (AC-75).

**Thông báo dữ liệu cá nhân (NFR-13):** trang chủ nhắc nhân viên đọc và bấm xác nhận thông báo xử lý dữ liệu cá nhân cho đến khi đã xác nhận; đổi phiên bản thông báo thì được nhắc lại. Lần xác nhận ghi vào nhật ký.

## 3. Ca làm việc

**Ai:** Chủ quán khai báo ở Quản trị › Ca làm việc (`/du-lieu/ca/`).

**Một ca gồm:** tên, giờ bắt đầu, giờ kết thúc, Chủ quán phụ trách (người tạo ca), người được ủy quyền thanh toán theo món thực nhận. Biểu mẫu gợi ý sẵn ca kế tiếp theo giờ của ca gần nhất.

**Ca nào nhận đơn và tiền?** Hệ thống gọi đó là *ca đang giữ quỹ* (`Shift.objects.operating()`):

1. Nếu có ca đang mở mà giờ hiện tại nằm trong khung giờ của ca: lấy ca đó (ca bắt đầu muộn nhất nếu chồng giờ).
2. Nếu không: lấy ca đang mở, đã bắt đầu, đã quá giờ kết thúc dự kiến nhưng **chưa kết**. Ví dụ ca tối 17–22 giờ, khách trả tiền lúc 22:10 mà thu ngân chưa kết ca: tiền vẫn vào quỹ ca tối.
3. Không có ca nào đang mở: đơn vẫn nhận được (không gắn ca) nhưng **không thu tiền được**. Thu ngân thấy thông báo "Chưa có ca đang mở; Chủ quán khai báo ca rồi mới thu tiền".

Màn hình **Ca của tôi** (`/ca/`) mở ca đang giữ quỹ; nếu không có thì mở ca đã kết mà còn thiếu báo cáo cuối ca.

## 4. Bán hàng: tạo đơn, pha chế, phục vụ

### 4.0. Tổng quan ca (Chủ quán, Thu ngân, Phục vụ) — `/ban-hang/tong-quan/`

Mục đầu tiên của nhóm Bán hàng, bấm thẻ Bán hàng ở thanh trên là mở trang này. Trang tự làm mới mỗi 15 giây và chỉ đọc, không ghi gì.

- **Năm ô trên cùng:** bàn có khách trên tổng số bàn (kèm số tiền chưa thu), yêu cầu điều chỉnh chờ duyệt, số ly chờ pha và phiếu cũ nhất, số ly pha xong chờ mang ra kèm số bàn, số bàn đã phục vụ xong chờ thu tiền. Bấm ô để sang màn xử lý (Duyệt, Quầy pha chế, Món sẵn sàng, Thu ngân) nếu có quyền.
- **Ca này đến giờ:** số đơn, số ly đã bán, thời gian khách chờ món thường gặp (trung vị từ lúc gửi đến lúc mang ra, giống màn Tải và thời gian chờ). Chủ quán và Thu ngân thấy thêm doanh thu ca và tiền mặt phải có; Phục vụ không thấy số tiền ca.
- **Bàn:** mỗi bàn một ô theo khu vực, có chấm trạng thái: *Chờ duyệt* (có yêu cầu điều chỉnh), *Có món chờ mang ra*, *Đang pha*, *Chờ thanh toán* (đã phục vụ hết), *Trống*. Bàn có nhiều tình trạng thì hiện tình trạng đứng trước trong danh sách này. Số phút tính từ đơn đầu tiên của bàn; chuyển đỏ khi bàn còn món chưa mang ra mà đã chờ quá chuẩn thời gian chờ (tham số `wait_standard_minutes`). Bấm ô bàn để mở đơn của bàn trong Đơn đang mở.
- **Cần xử lý:** yêu cầu chờ duyệt (ai gửi, bao lâu, đang chờ cấp nào; nút Duyệt nếu đang chờ chính người xem), bàn chờ món lâu, quầy dồn món quá mức cho phép (tham số `bar_backlog_limit`).
- **Người trong ca:** người đang chấm công vào, kèm người có lịch ca này (lịch tuần đã công bố) mà chưa chấm công.
- **Món sắp hết:** báo nhanh nguyên liệu chưa xử lý và món còn đáp ứng từ 10 ly trở xuống (`LOW_CUPS` trong `apps/orders/overview.py`).

Muốn thử trên dữ liệu mô phỏng: `manage.py tao_ban_co_khach` cho sáu bàn trống có khách ngay lúc chạy lệnh (hai bàn chờ pha, một bàn chờ lâu, một bàn có món chờ mang ra, hai bàn chờ thu tiền, một bàn có yêu cầu đổi món chờ duyệt), đi qua chính các hàm nghiệp vụ. Chưa có ca trong giờ hiện tại thì lệnh mở "Ca ngày" và cho nhân viên demo chấm công. Chạy lại lúc nào cũng được.

### 4.1. Tạo đơn (Phục vụ, trên điện thoại) — `/don/moi/`

1. Chọn bàn, chọn món, kích cỡ, tùy chọn (đá, đường, topping...), số ly, ghi chú.
2. Màn hình hiện **số ly còn đáp ứng** của từng món, tính từ *tồn có thể dùng* và định mức, có tính cả tùy chọn đang chọn và các món đã có trong phiếu (FR-01, AC-02). Số này cập nhật lại mỗi khi mở trang.
3. Phiếu đang soạn được lưu nháp trên điện thoại kèm mã nghiệp vụ, tải lại trang không mất (NFR-16).
4. Bấm **Gửi pha chế**. Máy chủ làm trong *một giao dịch*:
   - kiểm tra món còn mở bán, kích cỡ và tùy chọn hợp lệ, nhóm tùy chọn bắt buộc đã chọn;
   - tính tổng nguyên liệu cả đơn theo định mức đang áp dụng;
   - khóa các dòng tồn kho liên quan theo thứ tự mã (hai đơn cùng lúc không giữ trùng phần tồn);
   - thiếu bất kỳ nguyên liệu nào thì **không nhận gì cả**, trả về từng nguyên liệu thiếu bao nhiêu và từng món còn làm được bao nhiêu ly (AC-04);
   - đủ thì **giữ** nguyên liệu (tăng "đang giữ"), tạo đơn với mã `ddmm-NNN`, chụp lại tên món, giá, tùy chọn, phiên bản định mức và lượng nguyên liệu mỗi ly vào từng dòng (BRU-39). Đổi giá hay định mức sau đó không ảnh hưởng đơn này.
5. Mất phản hồi khi gửi: màn hình hiện mã nghiệp vụ để gửi lại, hoặc ghi lên phiếu dự phòng (mục 8).

**Khi bị báo thiếu:** phục vụ có thể bấm "Đề nghị pha chế kiểm kê lại" (AC-03), tạo cảnh báo Kiểm kê lại giao Pha chế; cảnh báo tự đóng khi có lần kiểm kê nguyên liệu đó. Nếu khách đổi món sau cảnh báo thiếu, bấm "Khách đổi món" để hệ thống ghi một *trường hợp thiếu nguyên liệu* (FR-27).

### 4.2. Quầy pha chế (Pha chế, máy tính quầy) — `/quay/`

- Danh sách món chờ pha tự làm mới mỗi 2 giây, nhóm theo đơn, có giờ gửi và số phút đã chờ.
- **Xong 1 ly** hoặc **Xong cả dòng**: trừ tồn vật lý và bỏ phần đang giữ tương ứng, ghi sổ kho loại Tiêu hao, đúng một lần. Nếu hai máy cùng bấm, máy chậm hơn nhận "Dòng này vừa được cập nhật ở nơi khác; không trừ thêm" (so số ly đã pha lúc mở trang).
- **In phiếu pha chế** (`/quay/phieu/<đơn>/`): mã đơn, bàn, món, tùy chọn, số ly, ghi chú, giờ. Có tùy chọn tự in khi có đơn mới.

### 4.3. Món sẵn sàng (Phục vụ) — `/don/san-sang/`

Liệt kê món đã pha xong kèm số bàn. Bấm **Đã mang ra** để chuyển dòng sang Đã phục vụ. Thanh trên điện thoại hiện số món đang chờ mang.

### 4.4. Vòng đời đơn

Trạng thái đơn được suy ra từ các dòng: còn dòng chờ pha → *Đã gửi pha chế*; mọi dòng đã pha hoặc đã mang → *Đã pha chế*; mọi dòng đã mang → *Đã phục vụ*; thu tiền → *Đã thanh toán*; mọi dòng bị hủy hoặc hủy hóa đơn → *Đã hủy*. Chỉ đơn Đã phục vụ mới thu tiền được (AC-07).

### 4.5. Tra cứu đơn — `/don/tra-cuu/`, `/don/<id>/`

Chủ quán lọc theo mã, ngày tạo hoặc ngày thu, trạng thái, phương thức, bàn, ca, nhân viên, món, nhóm, khung giờ. Trang chi tiết hiện món, điều chỉnh, hoàn tiền, phiếu dự phòng và toàn bộ nhật ký của đơn.

## 5. Điều chỉnh đơn và phê duyệt

**Gửi yêu cầu** (`/don/<id>/dieu-chinh/`): người tạo đơn hoặc thu ngân chọn loại và **lý do từ danh mục** (bắt buộc, AC-20):

| Loại | Khi duyệt, hệ thống làm gì |
|---|---|
| Hủy món / giảm số ly | Ly chưa pha: trả phần đang giữ về tồn có thể dùng. Ly đã pha: ghi *Hủy sau pha chế*, **không** trừ kho lần nữa (BRU-19, AC-21). Tính lại tổng tiền. |
| Đổi món | Hủy số ly cũ như trên, rồi thêm dòng món mới và **giữ** nguyên liệu cho nó. Món mới không đủ nguyên liệu thì không duyệt được, yêu cầu vẫn chờ và Chủ quán thấy rõ thiếu gì. |
| Chuyển bàn / gộp bàn | Đổi bàn của đơn. |
| Hủy hóa đơn đã thanh toán | Đơn chuyển Đã hủy, tạo khoản hoàn "chờ hoàn tiền" theo phương thức khách đã trả (mục 7.4), tạo ngoại lệ cho Chủ quán. |

Quy tắc:

- Mỗi đơn chỉ có tối đa một yêu cầu đang chờ (ràng buộc trong cơ sở dữ liệu).
- Đơn đã thanh toán chỉ nhận yêu cầu hủy hóa đơn.
- **Người duyệt:** Chủ quán, một cấp (GD-27). Nhân viên không tự duyệt yêu cầu của mình; Chủ quán tự gửi thì tự duyệt, có nhật ký.
- **Thời hạn:** mỗi yêu cầu chốt thời hạn duyệt lúc tạo (mặc định 3 phút). Quá hạn mà chưa ai duyệt thì yêu cầu thành *Quá hạn mọi cấp*. Cấp hiện hành được tính mỗi lần đọc nên luôn đúng, không phụ thuộc ai mở màn hình; tác vụ định kỳ ghi lại thời điểm chuyển cấp vào nhật ký.
- Màn hình **Duyệt** (`/duyet/`) trên điện thoại Chủ quán; thanh trên hiện số yêu cầu chờ. Mất mạng thì nút duyệt bị khóa.
- Từ chối một yêu cầu gửi *sau khi đã có món pha xong* → tạo ngoại lệ "Điều chỉnh sau pha chế bị từ chối".
- Một nhân viên gửi quá 3 yêu cầu sau pha chế trong ca → một ngoại lệ nhân viên, các yêu cầu sau gắn vào cùng ngoại lệ (AC-31).
- Tổng giá trị món hủy sau pha chế của ca vượt 100.000 đ → ngoại lệ của ca.
- Duyệt đổi hoặc hủy với lý do "Hết nguyên liệu" → ghi trường hợp thiếu nguyên liệu (BRU-26).

## 6. Thanh toán

**Màn hình Thu ngân** (`/thu-ngan/`) liệt kê từng bàn còn đơn chưa thu, tổng tiền và lý do chưa thu được, ví dụ "Đơn 2510-014 có yêu cầu … đang chờ duyệt" (AC-09) hoặc "chưa phục vụ xong".

**Thu tiền cả bàn:** chọn Tiền mặt hoặc Chuyển khoản. Chuyển khoản chỉ bấm được khi đánh dấu "đã thấy tiền về" (AC-08). Máy chủ kiểm tra lại mọi điều kiện, ghi một bản ghi thanh toán gắn **ca đang giữ quỹ** (mục 3), chuyển các đơn sang Đã thanh toán. Gửi lại cùng mã không thu hai lần.

**Thanh toán theo món thực nhận (AC-10):** khi một yêu cầu đổi món đã quá hạn mọi cấp mà khách đã nhận món thay thế, chỉ *người được ủy quyền của ca* (không phải người tạo yêu cầu) mới bấm được. Hệ thống áp dụng yêu cầu như đã duyệt, trừ kho món thay thế ngay (món đã pha thật nên không chặn vì tồn sổ sách), tính tiền theo giá bán, chuyển yêu cầu sang *Chờ hậu kiểm* và tạo ngoại lệ cho Chủ quán.

## 7. Quỹ tiền ca, kết ca, báo cáo cuối ca, đối soát

Màn hình **Ca của tôi** (`/ca/`, Thu ngân và Chủ quán).

### 7.1. Quỹ tiền mặt (FR-07)

- **Tiền đầu ca:** ghi một lần mỗi ca.
- **Chi tiền mặt:** chọn danh mục, ghi nội dung; từ 500.000 đ phải kèm ảnh chứng từ (AC-15). Chi nguyên vật liệu không ghi ở đây mà qua phiếu nhập "Trả ngay bằng quỹ ca".
- **Nộp tiền giữa ca:** chọn người nhận khác mình; khoản nộp chỉ trừ khỏi quỹ khi người nhận bấm xác nhận đã nhận (AC-14).
- Bút toán chỉ thêm mới; ghi sai thì ghi bút toán khác.

### 7.2. Kết ca (FR-08, AC-16)

Bị chặn khi còn: đơn chưa thanh toán; yêu cầu điều chỉnh chờ duyệt; chưa có tiền đầu ca; khoản nộp chưa xác nhận; phiếu dự phòng chưa nhập bù, chưa khai số cuối đã dùng hoặc chờ Chủ quán xác nhận giá. Đơn chưa thanh toán có thể **chuyển sang ca sau** kèm lý do. Kết ca chốt doanh thu tiền mặt và chuyển khoản của ca.

### 7.3. Báo cáo cuối ca và đối soát (FR-08, FR-12, BRU-10)

Sau khi kết ca, người lập nhập: tiền mặt đếm được, tiền chuyển khoản nhận và tiền hoàn chuyển khoản theo sao kê, sự cố. Hệ thống đối soát ngay:

```
Tiền mặt phải có = tiền đầu ca + doanh thu tiền mặt − hoàn tiền mặt − chi − nộp đã xác nhận
Chênh lệch = thực tế − phải có   (âm là thiếu)
```

Chuyển khoản nhận và chuyển khoản hoàn được so riêng. Mọi chênh lệch khác 0 đều được lưu, kèm ngưỡng có hiệu lực lúc kết ca. Vượt ngưỡng (mặc định 50.000 đ) thì người lập hoặc Chủ quán phải giải trình, Chủ quán chọn Chấp nhận hoặc Không chấp nhận. Chủ quán nhận thông báo đẩy khi có báo cáo.

**Đính chính báo cáo (GD-11):** báo cáo gốc không sửa. Người lập gửi đề nghị đính chính có lý do, Chủ quán duyệt (Chủ quán tự đề nghị thì duyệt luôn). Duyệt xong hệ thống đối soát lại: khoản không đổi giữ nguyên kèm giải trình; khoản đổi thì bản cũ hết hiệu lực (vẫn giữ lịch sử) và bản mới thay thế. Khoản đã là bằng chứng trong vụ việc tổn thất thì phải đính chính vụ việc trước.

**Tích lũy (FR-13):** thiếu tiền chưa được chấp nhận giải trình được cộng dồn theo tháng cho từng người chịu trách nhiệm (vượt 100.000 đ) và toàn quán (vượt 300.000 đ) → ngoại lệ gắn các ca liên quan. Mục tiêu BO-01 (dưới 200.000 đ/tháng) là con số riêng, không phải ngưỡng cảnh báo.

### 7.4. Hoàn tiền khi hủy hóa đơn đã thu (GD-07)

Hai bước tách biệt: Chủ quán duyệt hủy → khoản hoàn "chờ hoàn tiền" (chưa có tiền ra, chưa gắn ca). Người thu tiền bấm **Đã hoàn tiền** ở trang Ca của tôi → khoản hoàn gắn vào ca đang giữ quỹ lúc đó và được trừ đúng một lần khi đối soát ca ấy. Khoản chờ hoàn không chặn kết ca (GD-16).

### 7.5. Tình trạng ca — `/ca/tinh-trang/`

Chủ quán thấy ca chưa kết sau giờ kết thúc, ca thiếu báo cáo quá 2 giờ (AC-18), phiếu dự phòng chưa nhập bù, kiểm kê nhóm trọng yếu chưa làm trước giờ mở cửa hôm sau (chỉ xét ở ca cuối cùng của ngày, tính theo giờ Việt Nam), các chênh lệch chờ quyết định.

Chênh lệch chờ quyết định hiện mỗi khoản một dòng (ca, cách thu, người phụ trách, số tiền) với hai nút Không chấp nhận, Chấp nhận ngay trên dòng. Bảng các ca gần đây hiện 10 ca, bấm "Xem 50 ca trước đó" để xem thêm.

Trang Ca của tôi gộp các việc còn thiếu (chưa kết ca, thiếu báo cáo cuối ca…) vào một thông báo kèm hạn báo cáo; số liệu quỹ chia hai khối Tiền mặt (từ tiền đầu ca tới tiền mặt phải có trong két) và Chuyển khoản.

## 8. Bán hàng dự phòng khi mất mạng — `/du-phong/`

1. Chủ quán cấp cho mỗi ca một **dãy số phiếu** in sẵn, ghi người nhận. Hai dãy không được trùng số.
2. Mất mạng: nhân viên ghi tay lên phiếu, gồm mã nghiệp vụ nếu màn hình đã hiện.
3. Có mạng lại: nhập bù từng phiếu kèm số phiếu, thời điểm bán, giờ có mạng lại, phương thức thanh toán, bàn, món.
   - **Có mã nghiệp vụ trùng đơn đã lưu:** liên kết phiếu với đơn đó, chỉ bổ sung phần còn thiếu (pha, mang ra, thu tiền), không trừ kho lần hai.
   - **Chưa có đơn:** tạo đơn đã pha, đã phục vụ, đã thu tiền; giá theo *lịch sử giá* và định mức theo phiên bản có hiệu lực **tại thời điểm bán**; trừ kho thẳng theo định mức đó.
   - **Thiếu lịch sử giá hoặc định mức** tại thời điểm bán: không đoán; phiếu chờ Chủ quán nhập đơn giá đã bán và chọn phiên bản định mức, có nhật ký (GD-24).
4. Số trùng, số ngoài dãy, nhập bù quá 1 giờ sau khi có mạng, phiếu khai báo hủy → ngoại lệ.
5. Trước khi kết ca phải khai **số cuối đã dùng** của mỗi dãy (0 nếu không dùng). Số đã dùng mà chưa nhập bù hay khai hủy sẽ chặn kết ca (AC-13).

## 9. Kho

### 9.1. Ba con số tồn (FR-22)

- **Tồn vật lý**: lượng thật trên kệ theo sổ.
- **Đang giữ**: lượng đã cam kết cho các ly đang chờ pha.
- **Có thể dùng** = vật lý − đang giữ. Tạo đơn chỉ nhìn con số này.

Mọi thay đổi tồn chỉ đi qua một chỗ (`apps/inventory/stock.py`). Mỗi biến động vật lý là một dòng **sổ kho** chỉ thêm mới (loại, số lượng, tồn sau, nguồn nghiệp vụ, người, giờ). Trong cùng giao dịch, biến động được phân bổ vào **lô hàng** (mục 9.9). Lệnh kiểm tra toàn vẹn so tồn vật lý với tổng sổ kho, phần đang giữ với các ly chờ pha, và tổng còn lại các lô với tồn vật lý.

| Nghiệp vụ | Vật lý | Đang giữ |
|---|---|---|
| Gửi đơn | | + |
| Pha xong | − | − |
| Hủy ly chưa pha | | − |
| Hủy ly đã pha | (không đổi) | |
| Nhập hàng | + | |
| Hao hụt | − | |
| Kiểm kê | ± chênh lệch | |

### 9.2. Tồn kho — `/kho/`

Bốn ô đầu trang: lô quá hạn còn trong kho, lô sắp hết hạn, giá trị dự kiến bỏ vì không dùng kịp, số nguyên liệu dưới mức tồn an toàn. Bấm ô nào thì bảng lọc theo ô đó (`?loc=expired`, `near`, `risk`, `low`).

Mỗi nguyên liệu một dòng: quy tắc xuất lô, có thể dùng, đủ dùng bao nhiêu ngày (theo tốc độ dùng 4 tuần gần nhất), lô nên lấy trước và hạn của lô đó, số lô, giá trị (chỉ Chủ quán), tình trạng. Từ đây mở các thao tác bên dưới.

### 9.3. Báo nhanh (FR-23) — `/kho/bao-nhanh/`

Pha chế báo *Sắp hết* hoặc *Đã hết* kèm lượng còn lại ước chừng, không quá 3 thao tác. Chủ quán thấy dải báo ở đầu màn hình và bấm đã xử lý. Báo *Đã hết* trong giờ mở cửa → cảnh báo Khẩn 15 phút và ghi một trường hợp thiếu nguyên liệu (tối đa một trường hợp mỗi nguyên liệu mỗi ngày).

### 9.4. Phiếu nhập (FR-24) — `/kho/phieu-nhap/`

Chọn nhà cung cấp thì màn hiện các lần đặt đang chờ giao của nhà cung cấp đó; bấm một lần đặt là điền sẵn dòng (nguyên liệu, số còn chờ giao, lần đặt). Mỗi dòng: nguyên liệu, số lượng thực nhận, đơn giá theo đơn vị tính, thành tiền tự tính; bên dưới là hạn sử dụng trên bao bì, số lô nhà sản xuất (không bắt buộc), lần đặt liên quan. Phiếu có tối đa 8 dòng, hiện dần bằng nút Thêm dòng; tổng giá trị phiếu luôn hiện ở thanh dưới. Dòng điền dở (có đơn giá mà thiếu nguyên liệu hoặc số lượng) thì không lưu cả phiếu và báo dòng nào thiếu. Trả ngay thì hỏi nguồn tiền, trả sau thì hỏi hạn trả. **Luôn phải có ảnh hóa đơn** (AC-55). Không nhập được lô đã quá hạn. Mỗi dòng tạo một lô mã `<mã phiếu>/<số dòng>`; dòng để trống hạn mà nguyên liệu có thời hạn sử dụng thì hạn được ước tính bằng ngày nhập cộng thời hạn. Lưu phiếu thì tăng tồn vật lý và tạo khoản phải trả:

- *Trả sau*: hạn trả theo số ngày chọn; Chủ quán ghi thanh toán từng phần ở `/kho/phai-tra/`. Màn Phải trả có tổng còn nợ, phần quá hạn, phần đến hạn trong 7 ngày; khoản quá hạn tô đỏ; số tiền gõ có dấu chấm ("2.982.000") được hiểu đúng. Trả bằng *Tiền mặt quỹ ca* thì ghi luôn một khoản chi Nguyên vật liệu vào ca đang mở (không có ca đang mở thì không cho chọn nguồn này).
- *Trả ngay bằng quỹ ca*: tự ghi một khoản chi "Nguyên vật liệu" vào quỹ ca đang giữ (GD-09).
- Gắn lần đặt: cập nhật Đã giao đủ / Giao một phần; nhận vượt số đặt vẫn ghi nhưng báo cho Chủ quán.

### 9.5. Kiểm kê (FR-25) — `/kho/kiem-ke/`

Nguyên liệu chia hai nhóm: Trọng yếu (kiểm mỗi ngày) và Nguyên liệu khác. Đầu trang có số đã kiểm hôm nay và số trọng yếu còn thiếu. Mỗi dòng hiện tồn trên sổ, lần kiểm trước, và nhãn Đã kiểm, Chờ xác nhận hoặc Được đề nghị kiểm lại (khi phục vụ đề nghị từ màn Tạo đơn). Gõ số đếm được thì màn báo ngay lệch bao nhiêu; ô lý do chỉ hiện và bắt buộc khi lệch vượt ngưỡng. Nháp đang gõ được lưu riêng cho từng nguyên liệu. Hệ thống so với tồn vật lý **lúc đếm**:

- Chênh lệch trong ngưỡng 5%: điều chỉnh ngay.
- Vượt ngưỡng: bắt buộc ghi lý do, chờ Chủ quán xác nhận. Khi xác nhận, hệ thống điều chỉnh đúng phần chênh lúc đếm, nên các biến động phát sinh trong lúc chờ không bị xóa.
- Tồn sổ sách bằng 0 hoặc âm thì mọi chênh lệch đều coi là vượt ngưỡng.
- Thiếu kiểm kê tích lũy trong tháng của một nguyên liệu vượt ngưỡng (mặc định bằng một quy cách) → ngoại lệ kèm tên người kiểm kê (AC-58).
- Kiểm kê nguyên liệu **trọng yếu** được áp dụng → đối chiếu tiêu hao với lần kiểm kê trước (FR-16): tiêu hao thực tế = kiểm kê trước + nhập − kiểm kê này − hao hụt; so với tiêu hao theo đơn; lệch quá 5% → ngoại lệ.
- Kiểm kê xong tự đóng các đề nghị kiểm kê lại của nguyên liệu đó.

### 9.6. Hao hụt (FR-26) — `/kho/hao-hut/`

Chọn nguyên liệu (màn hiện tồn trên sổ và đơn vị), số lượng bỏ đi, lý do bắt buộc (hư hỏng, hết hạn, đổ vỡ, pha hỏng, khác), và lô bị hỏng nếu biết; cột bên phải là các lần ghi gần đây. Để trống lô thì hệ thống trừ theo thứ tự lấy lô; lý do Hết hạn thì trừ lô quá hạn trước. Giảm tồn vật lý. Không được ghi vượt tồn vật lý trên sổ; sổ sai thì kiểm kê trước. Chủ quán có thể đánh dấu *sự cố đơn lẻ* để không làm lệch tỷ lệ hao hụt khi dự báo.

### 9.7. Đặt hàng (FR-30) — `/kho/dat-hang/`

Ghi lần đặt: chọn nguyên liệu thì nhà cung cấp chính của nguyên liệu được chọn sẵn và đơn vị hiện cạnh ô số lượng; ngày giao không được trước hôm nay. Màn chia hai phần: **Đang chờ giao** xếp theo ngày giao, dòng giao chậm tô đỏ, mỗi dòng có nút Đổi ngày (chỉ đổi sang hôm nay trở đi, không đổi lần đặt đã giao đủ hay đã hủy); **Đã giao, đã hủy** hiện 15 lần gần nhất, bấm để xem hết. Trạng thái Nháp → Đã đặt → Giao một phần → Đã giao đủ, hoặc Đã hủy (có lý do). Quá ngày giao mà chưa nhận đủ thì thành **Giao chậm** và không còn tính là hàng đang về cho đến khi có ngày giao mới (AC-69).

### 9.8. Sổ kho và báo cáo — `/kho/so-kho/`, `/kho/bao-cao/`

Sổ kho lọc theo nguyên liệu, loại, ngày, có tổng và liên kết sang đơn; trên điện thoại mỗi biến động thành một khối gọn (nguyên liệu, lượng, giờ, loại, người làm, tồn sau). Báo cáo kho tháng: hao hụt theo lý do, hủy sau pha chế, kiểm kê, trường hợp thiếu. Báo cáo kho có biểu đồ cho Chủ quán ở `/bao-cao/kho/` (mục 14).

### 9.9. Lô hàng, hạn dùng và thứ tự lấy hàng — `/kho/lo/`, `/kho/lay-hang/`

Chi tiết ở `docs/QUAN_LY_KHO_THEO_LO.md`. Tóm tắt:

- Mỗi lần hàng vào kho tạo một **lô** có mã, ngày nhập, hạn sử dụng, số lô của nhà sản xuất, đơn giá và lượng còn lại. Mọi thay đổi lượng của lô ghi một dòng xuất nhập theo lô, chỉ thêm mới.
- **Quy tắc lấy lô**: để trống thì hệ thống tự chọn FEFO (hết hạn trước xuất trước); nguyên liệu không có hạn dùng thì thực chất là FIFO. Chủ quán có thể chọn FIFO hoặc LIFO ở Dữ liệu nền › Nguyên vật liệu; LIFO bị chặn với hàng có hạn dùng. Lô quá hạn luôn xếp cuối và không bao giờ được gợi ý.
- **Trạng thái lô**: Quá hạn, Sắp hết hạn (còn từ max(2 ngày, 20% thời hạn) trở xuống), Còn hạn, Chưa rõ hạn, Không có hạn (ly, ống hút).
- **Dự kiến bỏ**: mô phỏng dùng từng ngày theo tốc độ 4 tuần gần nhất và đúng thứ tự lấy lô; phần lô còn lại khi chạm hạn là lượng dự kiến bỏ.
- **Phiếu lấy hàng** (`/kho/lay-hang/`) cho quầy: mỗi nguyên liệu lấy lô nào trước, hạn, còn bao nhiêu ngày, lô kế tiếp; lô quá hạn hiện riêng với nút hủy.
- **Lô hàng** (`/kho/lo/`) lọc theo trạng thái và nguyên liệu; **chi tiết lô** của một nguyên liệu có biểu đồ lịch dùng dự kiến so với hạn, sửa hạn và số lô, hủy lô (ghi hao hụt đúng lô đó).
- Giá trị tồn tính theo giá thực tế đích danh của từng lô. LIFO chỉ là thứ tự lấy hàng, không phải cách tính giá (Thông tư 200/2014/TT-BTC đã bỏ phương pháp này).

## 10. Ngoại lệ, vụ việc tổn thất và giá trị kiểm soát

**Ngoại lệ** (`/kiem-soat/ngoai-le/`) do hệ thống tự tạo theo quy tắc BRU-12 và các mục trên:

| Loại | Phát sinh khi |
|---|---|
| Điều chỉnh sau pha chế bị từ chối | Mục 5 |
| Hóa đơn đã thanh toán bị hủy | Mục 5 |
| Nhiều điều chỉnh sau pha chế | Quá 3 yêu cầu/nhân viên/ca |
| Giá trị hủy sau pha chế vượt mức | Quá 100.000 đ/ca |
| Thanh toán theo món thực nhận | Mục 6 |
| Tích lũy người phụ trách ca / toàn quán | Mục 7.3 |
| Kiểm kê tích lũy, tiêu hao vượt mức | Mục 9.5 |
| Phiếu dự phòng hủy, trùng, ngoài dãy, quá hạn | Mục 8 |

**Danh sách ngoại lệ:** đầu trang có ba ô số (chờ xem xét và số mục quá hạn xem xét, tổng giá trị liên quan, số mục đã xem xét 30 ngày qua), ba thẻ Chờ xem xét, Đã xem xét, Tất cả, và hàng nút lọc theo loại kèm số mục. Lọc theo nhân viên và ngày nằm trong "Lọc theo nhân viên hoặc ngày". Mỗi dòng ghi loại, ngoại lệ nói về ai hoặc cái gì (nguyên liệu, nhân viên, mã đơn), giá trị, và nhãn Quá hạn hoặc kết luận đã ghi. Nút **Xem lần lượt** mở mục mới nhất.

**Xem xét (chỉ Chủ quán, FR-17):** trang chi tiết chia hai cột: bên trái là chứng cứ (nguyên liệu, nhân viên, ca, giá trị, các món của đơn, yêu cầu điều chỉnh liên quan, diễn biến của đơn theo tên nhân viên, ngoại lệ khác của cùng nhân viên); bên phải là ô kết luận Hợp lệ, Nhắc nhở hoặc Vi phạm kèm biện pháp. Nút **Lưu, xem mục kế tiếp** ghi kết quả rồi mở ngay ngoại lệ chờ kế tiếp, để xem hết danh sách mà không phải quay lại. Có tổn thất tiền thì gắn vào một vụ việc trước (ô "Có mất tiền?"); ô "Có tổn thất tiền" chỉ hiện khi ngoại lệ đã thuộc một vụ việc. Kết quả không sửa; muốn đổi phải lập bản đính chính có lý do. Ngoại lệ chưa xem xét quá 3 ngày được nhắc lại.

**Vụ việc tổn thất** (`/kiem-soat/vu-viec/`, mã `VV-001`…): bằng chứng là ngoại lệ hoặc khoản chênh lệch tiền; mỗi bằng chứng thuộc tối đa một vụ việc; cùng một giao dịch chỉ tính một lần. Trang chi tiết có bốn ô số (đề xuất từ bằng chứng, đã xác minh, đã thu hồi, còn phải thu hồi), danh sách bằng chứng, lịch sử xác minh và thu hồi; bên phải là ô xác nhận hoặc đính chính giá trị và ô ghi thu hồi. Số tiền gõ được "82.000". Thu hồi chỉ ghi được sau khi đã xác nhận giá trị, phải lớn hơn 0 và không vượt phần còn lại.

**Giá trị kiểm soát tạm tính của tháng** so với mục tiêu 200.000 đ (BRU-16) hiện ở bảng điều khiển và báo cáo kiểm soát doanh thu, cộng các nhóm không trùng nhau.

## 11. Trung tâm cảnh báo — `/canh-bao/`

Mỗi lần tác vụ định kỳ chạy, hệ thống quét các điều kiện ở Bảng 5.4, rồi:

- đối tượng mới thỏa điều kiện → tạo cảnh báo, giao người xử lý chính, đặt thời hạn (theo tham số);
- điều kiện không còn → tự đóng kèm ghi chú;
- quá hạn → chuyển cấp lên Chủ quán hoặc nhắc lại;
- đóng tay phải ghi kết quả; đối tượng đã đóng tay không tự mở lại (GD-22).

**Giao diện:** đầu trang có số việc đang chờ và số việc quá hạn, việc Khẩn, thống kê 7 ngày (với Chủ quán). Việc được gom theo loại, loại có việc quá hạn đứng trước; mỗi loại hiện 5 việc đầu, phần còn lại mở bằng "Xem thêm". Mỗi việc có nút **Xử lý** (mở đúng màn hình xử lý), **Nhận** (báo mình đang làm) và **Đóng** (mở ô ghi kết quả). Nhóm ngoại lệ có nút mở thẳng danh sách ngoại lệ. Phần bật thông báo trên điện thoại nằm cuối trang.

Loại cảnh báo: Nguyên liệu Đã hết (Khẩn), phiếu dự phòng chưa nhập bù hoặc chờ xác nhận, dữ liệu ca trễ hạn, chênh lệch tiền vượt ngưỡng, ngoại lệ chờ xem xét, giao chậm, chênh lệch kiểm kê chờ xác nhận, khoản phải trả đến hạn, cần kiểm kê lại (giao Pha chế), kiểm kê trọng yếu trễ, **Cần đặt hàng** (từ kế hoạch mua), **Lô quá hạn còn trong kho** (mỗi lô một cảnh báo, giao Pha chế, Quan trọng, hạn cuối ngày, quá hạn chuyển Chủ quán, tự đóng khi lô được hủy hoặc dùng hết). Cảnh báo Khẩn và Quan trọng gửi thông báo đẩy tới điện thoại (NFR-17). Trang có thống kê tuần (NFR-23).

## 12. Chấm công, tải công việc, lịch làm

**Chấm công** (`/cham-cong/`): nhân viên vào ca chọn vai trò mình đảm nhận, ra ca khi về. Lượt thiếu giờ ra không được tính giờ công; tác vụ định kỳ nhắc Chủ quán một lần, Chủ quán bổ sung giờ ra kèm lý do (AC-77, AC-78). Một người được tính có mặt trong khung giờ khi làm ít nhất nửa khung (GD-20).

- Nhân viên thấy một thẻ lớn: chưa vào ca thì thẻ ghi ca hôm nay trong lịch và chọn sẵn vị trí của ca đó; đang làm thì thẻ ghi đã làm bao lâu, ca kết thúc lúc mấy giờ và nút Ra ca. Lượt còn mở từ hôm trước hiện "Quên bấm Ra ca?" và nhắc báo Chủ quán bổ sung giờ ra; bổ sung xong mới vào ca mới được. Bên cạnh là các lượt gần đây kèm số giờ công, tổng giờ tuần này và tuần trước.
- Chủ quán thấy bốn ô: đang làm, theo lịch hôm nay, đi trễ, chưa vào ca; khối Thiếu giờ ra ca với giờ ra điền sẵn theo giờ kết thúc ca trong lịch (không có lịch thì 8 tiếng sau giờ vào, không quá hiện tại) và lý do chọn nhanh; danh sách hôm nay đối chiếu từng người trong lịch với giờ vào thật: đúng giờ, trễ bao nhiêu phút, chưa vào ca, không chấm công, ngoài lịch. Một lượt chấm công thuộc một ca khi giờ vào nằm từ hai tiếng trước giờ bắt đầu tới trước giờ kết thúc ca. Mức tính đi trễ là tham số `late_minutes` (mặc định 5 phút, Chủ quán đổi ở Kiểm soát › Tham số).

**Tải và thời gian chờ** (`/tai/`, Chủ quán): theo từng khung một giờ:

- tải = số ly × hệ số tải của nhóm món (theo giờ gửi pha chế);
- thời gian chờ = trung vị từ gửi pha chế đến mang ra;
- món tồn quầy cuối khung;
- **Quá tải** khi thời gian chờ trung vị vượt 10 phút hoặc tồn quầy vượt 15 ly;
- số người có mặt theo vai trò.

Trang có ba biểu đồ: số ly theo khung giờ (cột đỏ là khung quá tải), thời gian chờ trung vị so với đường chuẩn, và người có mặt theo vai trò; nút chuyển ngày trước, ngày sau. Khung giờ chưa tới không hiện; khung không có đơn ghi "Không có đơn" thay vì "Đạt chuẩn". Dòng mô tả đầu trang không ghi cách tính tải.

**Lịch làm tuần** (`/lich/`, FR-38, FR-39):

- Nhân viên **đăng ký ca** tuần sau (`/lich/dang-ky/`) cho vị trí mình đảm nhận, trước hạn (mặc định 12 giờ thứ Năm). Sau hạn chỉ Chủ quán xếp.
- Hệ thống **gợi ý số người cần** cho từng ca và vị trí (từ 26/10/2026, xem `docs/KET_QUA_MO_PHONG.md`):
  1. Tải dự kiến từng giờ = dự báo số ly của ngày × tỷ lệ bán theo giờ × hệ số tải.
  2. Số người từng giờ theo mô hình hàng đợi Erlang C: ít nhất 70% việc không phải chờ quá 4 phút mới có người làm (hai tham số), không dưới mức tối thiểu khi quán mở.
  3. Chia vào các ca của ngày sao cho giờ nào cũng đủ người mà tổng giờ công ít nhất; ca chồng giờ cùng gánh giờ đông.
  4. Sức làm mỗi người đặt trong file `apps/core/params.py` (`schedule_productivity_*`), không có trên giao diện. Để 0 thì pha chế được đo lúc mọi pha chế đều bận (từ giờ gửi và giờ bấm Xong); phục vụ, thu ngân lấy giờ đông nhất đã làm kịp, thường thấp hơn sức làm thật nên gợi ý dư người.
  5. Khối "Số người cần từng giờ" cuối trang chỉ ghi kết quả (số ly dự kiến, số người cần từng giờ), không ghi cách tính. Chủ quán sửa số người cần được, khác gợi ý phải ghi lý do.
- **Gợi ý xếp lịch** theo đăng ký, giữ các ô Chủ quán đã xếp tay; không xếp một người vào hai ca trùng giờ (AC-87); thiếu, dư tính riêng từng vị trí (AC-86); gợi ý người thay thế.
- **Công bố** lịch; nhân viên xem ở `/lich/cua-toi/`. Có chép tuần trước sang tuần mới.

Màn Lịch làm tuần (làm lại 27/10/2026):

- Đầu trang: chuyển tuần, Thêm ca, Công bố (hoặc Công bố lại), nhãn Bản nháp, Đã công bố hay Có thay đổi chưa công bố.
- Năm bước lập lịch: Tạo ca, Số người cần, Nhân viên đăng ký (số người đã đăng ký, hạn), Xếp người (còn thiếu bao nhiêu chỗ), Công bố. Bước đang làm có viền xanh; nút việc tiếp theo nằm ngay trong bước (Chép ca tuần trước, Điền theo gợi ý, Xếp theo đăng ký).
- Thẻ "Theo ca": lưới ca mẫu × 7 ngày; mỗi ô là thẻ ca có vạch màu (đỏ thiếu, xanh đủ, cam dư), từng vị trí đã xếp trên số cần và tên người. Ô trống có nút + để thêm ca đúng ngày đó. Trên đầu thẻ là tổng đã xếp theo vị trí. Điện thoại và màn hẹp hiện danh sách theo ngày.
- Bấm một ca mở hộp chi tiết: đặt số người cần bằng nút cộng trừ (hiện "Gợi ý N"; khác gợi ý thì ô lý do tự hiện và bắt buộc), tick "Áp dụng cho Ca … cả tuần" để đặt cùng lúc mọi ca cùng tên trong tuần; danh sách người theo vị trí: người đã xếp (Bỏ ra), người đã đăng ký chưa xếp (Xếp vào ca), chọn thêm người khác kèm số giờ đã xếp trong tuần; Xóa ca. Lưu xong hộp mở lại kèm thông báo.
- Thẻ "Theo nhân viên": mỗi người một dòng, ca từng ngày, tổng giờ xếp, số ca đã đăng ký mà chưa xếp.
- Thẻ "Người cần theo giờ": số ly dự kiến và số người mỗi vị trí cần từng giờ của từng ngày, giờ quán mở mà chưa có ca phủ.
- Hộp Thêm ca: ca hay dùng bấm một lần, chọn ngày (cả tuần, thứ Hai tới thứ Sáu, cuối tuần), số người cần ban đầu (có thể để trống).
- Hộp Công bố: liệt kê ca còn thiếu người và phải tick xác nhận.
- Lỗi cũ "không cập nhật được số người cần": số khác gợi ý bắt buộc lý do nhưng ô lý do chỉ hiện khi số đang lưu đã khác gợi ý, nên lần sửa đầu luôn bị từ chối. Nay ô lý do hiện ngay khi sửa khác gợi ý, và lưu nhiều ca một lần là tất cả hoặc không ca nào.

Đăng ký ca (`/lich/dang-ky/`): ô đếm ngược tới hạn (dưới 24 giờ thì đổi màu cam); chọn nhanh "Ca sáng cả tuần", "Ca chiều cả tuần", "Bỏ chọn hết" (chọn sẵn vị trí đang thiếu nhiều nhất); mỗi ngày một khối, mỗi ca một dòng với nút chọn Không / từng vị trí mình đảm nhận và dòng "Còn thiếu …" của các vị trí đó; báo ngay khi chọn hai ca trùng giờ trong ngày (Chủ quán chỉ xếp được một); thanh dưới ghi tổng số ca, số giờ đang chọn và "Có thay đổi chưa gửi". Sau hạn trang chỉ liệt kê ca đã đăng ký và kết quả xếp (Được xếp, Không được xếp, Chờ công bố).

Lịch của tôi (`/lich/cua-toi/`): thẻ ca sắp tới (hoặc đang làm) với thời gian còn lại; nhắc đăng ký tuần sau khi chưa đăng ký và còn hạn; ca theo từng tuần kèm số ca và số giờ.

## 13. Dự báo nhu cầu và kế hoạch mua nguyên liệu

Chi tiết lý thuyết ở `docs/DU_BAO.md` và `docs/THIET_KE_MUA_NGUYEN_LIEU.md`. Tóm tắt cách chạy bên dưới chỉ để người phát triển đọc: từ 26/10/2026 giao diện chỉ hiện kết quả (số ly dự kiến, mức thấp và cao, việc cần làm, ngày đặt chậm nhất, số lượng đề xuất, tồn dự kiến từng ngày, một câu lý do), không hiện công thức, ký hiệu s, S, σ, mức phục vụ hay tên phương pháp. Trang Đánh giá dự báo và Đề xuất theo món (cũ) không còn trong menu; đường dẫn `/du-bao/danh-gia/` và `/du-bao/dat-hang/` vẫn mở được để kiểm tra kỹ thuật.

**Dữ liệu học:** chỉ ngày đã qua, có ca, mọi ca đã kết và có báo cáo cuối ca. Ngày đóng cửa hoặc chưa chốt không bị coi là bán 0 ly. Ngày có trường hợp thiếu nguyên liệu bị loại khỏi phần học của món bị ảnh hưởng. Phiếu dự phòng tính theo ngày bán ghi trên phiếu. Có thể nhập thêm lịch sử bán từ CSV hoặc Excel (`/du-bao/lich-su/`).

**Dự báo số ly theo món** (`/du-bao/`): trang có biểu đồ tổng số ly ba tuần qua nối với dự báo 14 ngày tới, và biểu đồ khoảng nhu cầu 7 ngày tới của từng món (dải từ phân vị 10 tới 90, chấm là kỳ vọng). Mô hình Poisson với mức nền động và hiệu ứng thứ trong tuần, học tuần tự kiểu Bayes; tiên nghiệm lấy từ **Nhận định Chủ quán** (số ly điển hình, ngày ít, ngày nhiều). Mỗi ngày phát hành một bản dự báo (kỳ vọng và phân vị 10/50/90), lưu nguyên để đánh giá về sau. Mặc định đặt hàng dùng *Ước tính ban đầu*; Chủ quán chuyển sang mô hình ở trang **Đánh giá dự báo** khi kết quả đánh giá ngoài mẫu tốt hơn.

**Kế hoạch mua theo nguyên liệu** (`/du-bao/ke-hoach-mua/`), dùng cho quyết định mua từ 13/10/2026:

1. Dựng chuỗi tiêu hao theo ngày của từng nguyên liệu từ dòng món đã bán × định mức, cộng tỷ lệ hủy sau pha, hao hụt vận hành, kiểm kê âm có hệ thống.
2. Chọn phương pháp dự báo theo dữ liệu đang có: M0 (ước tính tuần của Chủ quán), M1 (trung bình cùng thứ 4–8 tuần), M2 (mô hình tuyến tính động); chỉ đổi khi sai số thấp hơn rõ rệt và không chệch.
3. Áp **điều chỉnh theo mùa** của Chủ quán nếu có, trừ phần mô hình đã tự học.
4. Bộ tính chính sách (hàm thuần, không đọc ghi dữ liệu): với tồn có thể dùng, hàng đang về (lô giao chậm không tính), thời gian giao, chu kỳ kiểm tra, mức phục vụ (95%; hàng để lâu nhóm B ít nhất 98%), quy cách, hạn dùng, sức chứa → tính tồn dự kiến từng ngày, **ngày phải đặt muộn nhất**, số lượng đề xuất làm tròn theo quy cách, và một câu giải thích. Nguyên liệu có hạn dùng được tính theo lô (dựng từ phiếu nhập, dùng lô cũ trước); phần dự kiến hết hạn trước khi dùng kịp không được tính là hàng có (EWA, từ 26/10/2026).
5. Chủ quán **Chấp nhận** (tạo lần đặt ở trạng thái Nháp, sửa số thì ghi lý do) hoặc **Bỏ qua** kèm lý do. Hệ thống không tự liên hệ nhà cung cấp; bấm "Đã báo nhà cung cấp" để chuyển Nháp → Đã đặt.
6. Tính lại: toàn bộ một lần sau giờ đóng cửa mỗi ngày; riêng một nguyên liệu ngay sau mỗi biến động tồn hoặc thay đổi lần đặt. Cùng dữ liệu thì dùng lại kết quả cũ.
7. Ngày phải đặt là hôm nay hoặc đã qua → cảnh báo **Cần đặt hàng**, tự đóng khi đã đặt đủ.

## 14. Bảng điều khiển và báo cáo (chỉ Chủ quán)

Mọi số liệu tính lại từ giao dịch và đính chính đang có hiệu lực (GD-10), và mỗi con số bấm vào được để xem danh sách cấu thành (NFR-19).

Mỗi trang báo cáo chọn loại biểu đồ theo câu hỏi: đường cho xu hướng theo ngày, cột cho khung giờ, thanh ngang cho xếp hạng món và nguyên liệu, thanh tỷ lệ cho cơ cấu, bản đồ nhiệt cho thứ × giờ, biểu đồ chấm cho ma trận thực đơn, dải khoảng cho dự báo. Rê chuột hoặc chạm vào điểm để xem số. Phần **Nhận định** tự viết vài câu từ số liệu (doanh thu tăng giảm so với kỳ trước và do đâu, giờ đông nhất, món dẫn đầu doanh thu, món bán chạy nhưng lãi mỏng, tỷ lệ giá vốn; ở báo cáo kho: lô quá hạn, nguyên liệu có thể hết trước khi hàng về, nguyên liệu hao hụt nhiều nhất, hàng dự kiến bỏ, số ngày hàng nằm kho).

- **Bảng điều khiển** (`/bang-dieu-khien/`):
  - Phần ca đang mở: doanh thu, quỹ, yêu cầu chờ duyệt, người có mặt.
  - Chỉ số tháng: doanh thu, số đơn, giá trị mỗi đơn, lãi gộp ước tính; mỗi ô có đường nhỏ theo ngày và mũi tên so với cùng các ngày của tháng trước.
  - Biểu đồ: doanh thu theo ngày so với tháng trước, giờ đông khách (thứ × giờ), món mang lại doanh thu, ma trận thực đơn, doanh thu theo nhóm món, phương thức thanh toán.
  - **Ma trận thực đơn** (menu engineering, Kasavana và Smith): món chia bốn ô theo số ly (ngưỡng 70% mức bán chia đều) và lãi gộp mỗi ly (ngưỡng lãi gộp bình quân): Ngôi sao, Bán chạy lãi mỏng, Lãi cao ít người gọi, Cân nhắc bỏ; mỗi ô có gợi ý hành động. Lãi gộp = giá bán trừ nguyên liệu thực trừ kho khi đóng món, theo giá nhập gần nhất tại ngày bán.
  - **Kho cần chú ý**: lô quá hạn, lô sắp hết hạn, giá trị dự kiến bỏ, dưới mức an toàn (bấm để mở danh sách), tồn nguyên liệu trọng yếu, danh sách Sắp hết.
  - **Kiểm soát**: cảnh báo và ngoại lệ đang mở, BO-01 giá trị kiểm soát so với mục tiêu, BO-02, chênh lệch tích lũy.
- **Doanh thu** (`/bao-cao/doanh-thu/`): chọn nhanh 7 ngày, 30 ngày, tháng này, tháng trước, 90 ngày. Chỉ số so với kỳ liền trước cùng độ dài. Chọn chiều xem theo ngày, khung giờ, ca, nhóm món, món, nhân viên, phương thức; biểu đồ đổi theo chiều xem, bảng có dòng tổng. Thêm giờ đông khách và ma trận thực đơn của kỳ; xuất Excel. Tính theo thời điểm thanh toán; "nhân viên" là người tạo đơn; khung giờ theo giờ gửi pha chế (GD-23). Doanh thu là số khách đã trả, hoàn tiền trừ một lần ở doanh thu thuần.
- **Kiểm soát doanh thu** (`/bao-cao/kiem-soat/`): điều chỉnh theo lý do và kết quả, ngoại lệ theo nguồn và kết quả, chênh lệch theo ca và tích lũy, vụ việc, giá trị kiểm soát.
- **Nguyên vật liệu** (`/bao-cao/nguyen-lieu/`): tồn đầu + nhập − tiêu hao theo món − hao hụt ± kiểm kê = tồn cuối, cùng trường hợp thiếu và nhu cầu 7 ngày tới.
- **Kho** (`/bao-cao/kho/`): giá trị tồn theo ngày, xuất kho theo tuần (tiêu hao và hao hụt), lịch hết hạn theo tuần, số ngày đủ dùng so với thời gian giao hàng, hao hụt theo lý do và theo nguyên liệu, nhập theo nhà cung cấp, tuổi hàng trong kho; nhận định tự động (xem `docs/QUAN_LY_KHO_THEO_LO.md` mục 9).
- **Báo cáo điều chỉnh theo ca** (`/kiem-soat/dieu-chinh/<ca>/`).

## 15. Dữ liệu nền, tham số, nhật ký (chỉ Chủ quán)

**Dữ liệu nền** (`/du-lieu/<loại>/`): Ca, Nhân viên, Món và giá (kích cỡ, nhóm tùy chọn), Nhóm món (hệ số tải), Tùy chọn, Bàn, Nguyên vật liệu (đơn vị, quy cách, thời gian giao, tồn an toàn, trọng yếu, hạn dùng, quy tắc xuất lô, sức chứa…), Định mức, Nhà cung cấp, Lý do điều chỉnh, Nhận định Chủ quán, Điều chỉnh theo mùa. Mỗi lần sửa ghi nhật ký trước/sau.

**Định mức có phiên bản (FR-21):** tạo bản nháp, khai lượng nguyên liệu theo kích cỡ và tùy chọn, bấm Áp dụng (có thể hẹn ngày hiệu lực). Bản đã áp dụng không sửa được; muốn đổi thì tạo bản nháp mới từ bản cũ. Món chỉ được mở bán khi có định mức áp dụng cho mọi kích cỡ đang bán (hoặc khai "không dùng nguyên liệu"). Đổi giá cũng ghi lịch sử giá để nhập bù phiếu dự phòng đúng giá lúc bán.

**Tham số** (`/tham-so/`, NFR-14): trang chỉ có tham số nghiệp vụ (ngưỡng tiền, thời hạn, giờ mở cửa, số người tối thiểu, báo lô sắp hết hạn…). Tham số của mô hình (mọi `forecast_*`, `plan_*`, sức làm và mục tiêu chờ của gợi ý số người, xem `MODEL_KEYS`) không hiện và không đặt được trên ứng dụng: muốn đổi thì sửa giá trị mặc định trong `apps/core/params.py` rồi khởi động lại; giá trị đã lưu trong cơ sở dữ liệu cho các tham số này bị bỏ qua. Các trường chính sách mua trong form Nguyên vật liệu (nhóm A/B, mức phục vụ, chu kỳ kiểm tra, ngày kiểm tra, số ngày phơi nhiễm) cũng đã bỏ khỏi form. Mỗi tham số nghiệp vụ có giá trị mặc định, căn cứ (BRD, ví dụ AC, hay giả định chờ Chủ quán xác nhận), lịch sử. Mỗi lần lưu là một giá trị mới có "hiệu lực từ" (ngay hoặc thời điểm tương lai, không lùi về quá khứ). Việc đang dở giữ giá trị đã chốt: yêu cầu điều chỉnh giữ thời hạn lúc tạo, đối soát lưu ngưỡng lúc kết ca, kiểm kê lưu ngưỡng % lúc gửi.

**Nhật ký** (`/du-lieu/nhat-ky/`): tra cứu theo người, loại thao tác, đối tượng, thời gian. Không ai sửa hay xóa được, kể cả Chủ quán.

## 16. Tác vụ định kỳ, sao lưu, kiểm tra toàn vẹn

**`manage.py chay_dinh_ky`** (lên lịch mỗi phút bằng Task Scheduler hoặc chạy `--lap 60`), mỗi lần:

1. ghi chuyển cấp các yêu cầu điều chỉnh quá hạn;
2. đánh dấu Giao chậm các lần đặt quá ngày;
3. nhắc lượt thiếu giờ ra;
4. phát hành dự báo số ly của ngày (một lần mỗi ngày);
5. tính toàn bộ kế hoạch mua (một lần sau giờ đóng cửa);
6. đồng bộ trung tâm cảnh báo và gửi thông báo đẩy.

Màn hình không phụ thuộc lệnh này để hiển thị đúng; lệnh chỉ ghi trạng thái và nhật ký đúng thời điểm.

**`manage.py sao_luu` / `phuc_hoi`** (NFR-09): SQLite sao lưu trực tuyến, PostgreSQL dùng `pg_dump`; kèm thư mục ảnh chứng từ; giữ tối thiểu 30 bản. Phục hồi luôn vào một cơ sở dữ liệu khác rồi tự kiểm tra, không bao giờ ghi đè cơ sở dữ liệu đang chạy. Hướng dẫn ở `docs/VAN_HANH.md` mục 6.

**`manage.py kiem_tra_toan_ven`**: đối chiếu chéo tồn vật lý với sổ kho, phần đang giữ với ly chờ pha, tổng tiền đơn với dòng món, thanh toán với đơn, ca với quỹ. Không in gì ngoài "Không phát hiện sai lệch" là số liệu khớp.

**Dữ liệu mẫu:** `tao_du_lieu_mau` (4 tài khoản `demo_*`, mật khẩu `demo-lam-2026`, thực đơn giả), `tao_du_lieu_nghiem_thu` (14 ngày vận hành mẫu) và `tao_du_lieu_mo_phong` (mặc định 8 tuần, xem mục 21). Hai lệnh sau chỉ chạy trên cơ sở dữ liệu trống. Đây không phải dữ liệu thật của quán.

## 17. Những cơ chế chạy ngầm cần biết

- **Mã nghiệp vụ:** mỗi trang sinh sẵn một mã cho mỗi biểu mẫu. Cùng mã, cùng nội dung → trả kết quả cũ. Cùng mã, khác nội dung → từ chối. Thao tác lỗi thì mã không được lưu, gửi lại vẫn được xử lý.
- **Giao dịch theo yêu cầu:** mỗi lần bấm gửi chạy trong một giao dịch cơ sở dữ liệu; lỗi giữa chừng thì không có gì được ghi dở.
- **Lưới an toàn biểu mẫu:** dữ liệu gửi lên thiếu ô chọn, sai định dạng hoặc trỏ tới bản ghi không còn (trang mở đã lâu) không còn ra trang lỗi máy chủ; người dùng quay lại trang trước kèm thông báo, lỗi vẫn được ghi vào nhật ký máy chủ (`apps/core/middleware.py`).
- **Khóa tồn theo thứ tự:** mọi thao tác tồn khóa dòng tồn theo thứ tự mã nguyên liệu nên hai đơn đồng thời không giữ trùng và không khóa chéo nhau (đã kiểm trên PostgreSQL 16).
- **Mất mạng:** sau 10 giây không kết nối, dải cảnh báo hiện ở đầu màn hình; thanh toán, phê duyệt, xem xét bị khóa; biểu mẫu lưu nháp trên thiết bị kèm mã nghiệp vụ.
- **Giờ:** mọi thời điểm lưu theo UTC và hiển thị theo giờ Việt Nam (UTC+7). Các phép so "cùng ngày" dùng ngày theo giờ Việt Nam.

## 18. Thay đổi trong đợt rà soát 25/10/2026

Tìm bằng cách đọc lại luồng nghiệp vụ, duyệt thử 475 trang bằng cả 4 vai trò trên bộ dữ liệu nghiệm thu 14 ngày, và gửi dữ liệu sai vào mọi biểu mẫu. Mỗi lỗi nghiệp vụ có bài kiểm thử trong `apps/core/tests/test_ra_soat_2510.py`.

| # | Lỗi | Hậu quả trước khi sửa | Đã sửa |
|---|---|---|---|
| 1 | Thanh toán sau giờ kết thúc dự kiến của ca (ca chưa kết) không gắn vào ca nào | Tiền thu sau 22 giờ biến mất khỏi đối soát; két dư tiền, báo cáo cuối ca báo chênh lệch sai | Gắn vào ca đang giữ quỹ (mục 3) |
| 2 | Đơn tạo sau giờ kết thúc dự kiến không gắn ca | Đơn không chặn kết ca, không hiện ở Ca của tôi | Như trên |
| 3 | Thu tiền được khi không có ca nào mở | Tiền không thuộc quỹ nào | Chặn, báo cần khai báo ca |
| 4 | Ca của tôi không mở ca đã quá giờ nhưng chưa kết | Thu ngân không tìm thấy ca để kết | Mở ca đang giữ quỹ |
| 5 | Duyệt đổi món khi món mới thiếu nguyên liệu | Trang lỗi máy chủ | Báo thiếu gì, yêu cầu vẫn chờ |
| 6 | Thanh toán theo món thực nhận khi tồn sổ sách không đủ | Trang lỗi máy chủ, không thu được tiền dù món đã pha | Trừ kho thẳng, không chặn |
| 7 | Hao hụt ghi được vượt tồn vật lý | Tồn âm, các đơn sau bị từ chối | Chặn, yêu cầu kiểm kê trước |
| 8 | Kiểm kê khi tồn sổ sách âm tính ra tỷ lệ âm | Chênh lệch lớn được áp dụng ngay, không qua Chủ quán | Coi là vượt ngưỡng |
| 9 | Xác định "ca cuối ngày" theo ngày UTC | Ca sáng 6 giờ bị coi là ca cuối của ngày hôm trước, báo thiếu kiểm kê sai | So theo ngày giờ Việt Nam |
| 10 | Hai đơn không dùng nguyên liệu gửi cùng lúc có thể nhận trùng mã đơn trên PostgreSQL | Lỗi máy chủ khi gửi đơn | Khóa khi cấp mã |
| 11 | 20 chỗ nhận POST báo lỗi máy chủ khi thiếu ô chọn hoặc bản ghi không còn | Trang lỗi trắng | Lưới an toàn biểu mẫu (mục 17) |
| 12 | Nhân viên không có quyền duyệt vẫn được gắn đường dẫn Duyệt (ẩn) và trình duyệt định kỳ hỏi số yêu cầu chờ duyệt | Yêu cầu thừa lên máy chủ, đường dẫn dẫn tới trang 403 | Chỉ Chủ quán mới có |

Tài liệu cập nhật cho khớp quyết định GD-27 (bỏ Quản lý ca): README, PRODUCT.md, một số tiêu đề cột và chú thích trong mã. Bảng GD-13 trong `docs/DOI_CHIEU_YEU_CAU.md` sửa thành đã cài PostgreSQL cho khớp mục 8.

**Còn để ngỏ, cần Hai quyết:**

- Đơn tạo khi **không có ca nào mở** hiện vẫn nhận (để không chặn bán hàng nếu quên khai báo ca), nhưng không thu tiền được cho đến khi có ca. Nếu muốn chặn luôn từ lúc tạo đơn, chỉ cần một dòng kiểm tra trong `submit_order`.
- Đơn nhập bù từ phiếu dự phòng có mã đơn theo ngày nhập bù, còn doanh thu tính theo thời điểm thanh toán là lúc nhập bù (GD-23). Nếu nhập bù sang ngày hôm sau, doanh thu sẽ rơi vào ngày nhập bù dù quỹ ca vẫn đúng. Có thể đổi sang tính theo thời điểm bán ghi trên phiếu nếu Hai muốn.

## 19. Chạy thử bằng mô phỏng và đổi mô hình ra quyết định (26/10/2026)

Hai chức năng ra quyết định được chạy thử trên hai quán giả lập trong mã (`apps/forecast/simulation.py`, `apps/schedule/simulation.py`; chạy lại bằng `python manage.py mo_phong_ke_hoach_mua` và `python manage.py mo_phong_xep_ca`). Kết quả và lý do chọn mô hình ở `docs/KET_QUA_MO_PHONG.md`. Tóm tắt:

| Chức năng | Vấn đề tìm thấy | Đã đổi |
|---|---|---|
| Kế hoạch mua | Coi hàng sắp hết hạn là hàng dùng được; hàng để lâu chỉ giữ 90% mỗi tuần. Quy ra cả quán khoảng 3,4 lần thiếu mỗi tháng, BO-02 cho 1 | Tính phần sẽ hết hạn theo lô (EWA); hàng tươi 95%, hàng để lâu 98%. Còn khoảng 0,9 lần mỗi tháng; xoài, bơ hết hạn nhiều hơn 3–5 điểm phần trăm |
| Gợi ý số người | Năng suất học bằng trung vị gồm cả lúc rảnh nên chỉ bằng 1/3 sức làm thật; ca chồng giờ bị tính hai lần. Gợi ý 116 giờ công mỗi ngày so với 53 giờ của lịch hiện nay | Hàng đợi Erlang C từng giờ, chia ca bằng bài toán phủ, đo sức làm lúc mọi người bận. Khoảng 57–61 giờ, 96% số giờ đạt chuẩn chờ, giờ đông đạt chuẩn từ 74% lên khoảng 91% |
| Xếp người theo đăng ký | | Giữ nguyên: gần tối ưu (38 trên 40 tuần thử bằng lời giải tối ưu) |

## 20. Kho theo lô, báo cáo nhiều biểu đồ và giao diện mới (26/10/2026)

| Phần | Đã làm |
|---|---|
| Kho theo lô | Lô hàng có mã, ngày nhập, hạn, số lô nhà sản xuất, đơn giá. Quy tắc lấy lô FEFO, FIFO, LIFO chọn theo loại nguyên liệu, mặc định tự chọn. Phiếu lấy hàng cho quầy, trang lô và chi tiết lô, hủy lô, sửa hạn. Dự kiến bỏ theo tốc độ dùng. Dữ liệu cũ được chuyển sang lô bằng migration `inventory 0011`. Xem mục 9.9 và `docs/QUAN_LY_KHO_THEO_LO.md`. |
| Cảnh báo | Thêm cảnh báo Lô quá hạn còn trong kho (mục 11). |
| Báo cáo | Bảng điều khiển, doanh thu, kho, tải và dự báo dùng nhiều loại biểu đồ hợp với từng số liệu, có nhận định tự động, so sánh với kỳ trước, ma trận thực đơn và lãi gộp ước tính (mục 14). |
| Giao diện | Bố cục bảng quản trị: thanh bên trái theo nhóm nghiệp vụ, thanh trên mờ, thẻ trắng trên nền xám nhạt, chữ hệ thống, một màu nhấn xanh. Trên điện thoại giữ thanh điều hướng dưới. Quy tắc thiết kế ở `DESIGN.md`. |
| Dữ liệu mẫu | `tao_du_lieu_mau` có thời hạn sử dụng và hạn tồn đầu kỳ cho từng nguyên liệu, thêm ly nhựa (LIFO). `tao_du_lieu_nghiem_thu` có bốn nhà cung cấp giao theo chu kỳ, hạn in trên bao bì khác nhau, đổ vỡ, hủy lô quá hạn mỗi sáng. |

Cách tính tốc độ dùng nguyên liệu cũng được sửa: nguyên liệu mới theo dõi chưa đủ 4 tuần thì chia cho số ngày đã có sổ kho, trước đây chia cứng 28 ngày nên đánh giá thấp tốc độ dùng và báo dự kiến bỏ quá tay.

## 21. Giao diện kiểu Apple, ẩn cách tính, dữ liệu mô phỏng 8 tuần (26/10/2026, bản hai)

| Phần | Đã làm |
|---|---|
| Giao diện | Theo Apple Business Manager: nền trắng; thanh trên có các phân hệ, phân hệ đang mở là viên xám; thanh trái chỉ chữ, tiêu đề là tên phân hệ; thông báo, dải báo và cờ trạng thái nền trắng hoặc xám với chấm màu, bỏ hết khối nền màu nhạt. Trang chủ là lưới thẻ chức năng có ô biểu tượng màu theo phân hệ, mô tả một dòng, lọc theo phân hệ và tìm kiếm. Điện thoại giữ thanh dưới và thẻ gạch chân. Quy tắc ở `DESIGN.md`. |
| Ẩn cách tính | Kế hoạch mua, dự báo, lịch tuần, báo cáo chỉ hiện kết quả (mục 13). Tham số mô hình chỉ sửa trong `apps/core/params.py` (mục 15). |
| Dữ liệu mô phỏng | `manage.py tao_du_lieu_mo_phong [--ngay 56] [--hat-giong 2026]` trên cơ sở dữ liệu trống (đã `migrate`): tạo dữ liệu mẫu rồi cho quán chạy từng ngày tới hôm nay bằng chính các hàm nghiệp vụ (gửi đơn, pha, phục vụ, thu tiền, đổi món, chuyển bàn, hủy sau pha, hủy hóa đơn và hoàn tiền, nhập hàng theo lần đặt có giao thiếu và giao bù, trả nhà cung cấp, kiểm kê, hao hụt, hủy lô quá hạn, quỹ ca, báo cáo cuối ca có ngày thiếu tiền, phiếu dự phòng). 10 món, 9 nguyên liệu, 4 nhà cung cấp, 7 nhân viên chia ca sáng và chiều; khách tăng nhẹ theo thời gian, cuối tuần đông hơn, có ngày mưa vắng. Tác vụ định kỳ chạy mỗi đêm của 2 tuần cuối (để tệp dữ liệu dưới 25 MB) nên có dự báo, kế hoạch mua, cảnh báo, ngoại lệ. Hôm nay dừng ở giờ chạy lệnh: còn đơn đang pha, chờ thu tiền, một yêu cầu đổi món chờ Chủ quán duyệt, một lần kiểm kê Sữa đặc lệch 12% chờ xác nhận, lịch tuần này đã công bố và tuần sau đã có đăng ký. Kết quả không phụ thuộc giờ chạy ngoài phần hôm nay; cùng hạt giống cho cùng dữ liệu. |
| Tổng quan ca | Trang đầu nhóm Bán hàng cho ca đang mở: bàn có khách, chờ duyệt, chờ pha, chờ mang ra, chờ thu tiền, người trong ca, món sắp hết; tự làm mới 15 giây (mục 4.0). Lệnh `tao_ban_co_khach` tạo bàn đang có khách để thử. |

## 22. Làm lại Ca và nhân sự (27/10/2026)

| Màn | Đã làm |
|---|---|
| Lịch làm tuần | Lưới 7 ngày, bấm ca mở hộp đặt số người cần và xếp người, năm bước lập lịch, xem theo nhân viên, người cần theo giờ; sửa lỗi không lưu được số người cần (mục 12). |
| Đăng ký ca | Đếm ngược hạn, chọn nhanh cả tuần, tổng ca và giờ, báo hai ca trùng giờ, thanh gửi không che nội dung (mục 12). |
| Lịch của tôi | Thẻ ca sắp tới, giờ mỗi tuần, nhắc đăng ký tuần sau (mục 12). |
| Chấm công | Thẻ vào ra ca chọn sẵn vị trí theo lịch; Chủ quán xem ai đi trễ, chưa vào ca, ngoài lịch; bổ sung giờ ra điền sẵn; tham số mới `late_minutes` (mục 12). |
| Tình trạng ca, Ca của tôi | Chênh lệch chờ quyết định mỗi khoản một dòng, các ca gần đây 10 dòng; quỹ ca chia Tiền mặt và Chuyển khoản (mục 7.5). |
| Tải và thời gian chờ | Bỏ cách tính ở dòng mô tả, không hiện giờ chưa tới (mục 12). |

## 23. Rà soát nhóm Kho (27/10/2026)

| Việc | Trước | Sau |
|---|---|---|
| Gõ số lượng có dấu chấm | Màn hiển thị "1.866 gram" nhưng gõ lại "1.866" bị hiểu là 1,866 gram (kiểm kê, phiếu nhập, hao hụt, đặt hàng) | Dấu chấm theo sau đúng ba chữ số là phân cách hàng nghìn; dấu phẩy là phần lẻ ("1,5") |
| Gõ đơn giá, số tiền có dấu chấm | "25.000" bị hiểu là 25 đ ở phiếu nhập; "2.982.000" bị báo không hợp lệ ở Phải trả | Hiểu đúng; đơn giá lẻ theo gram ("31,5") làm tròn về đồng |
| Trả khoản phải trả bằng tiền mặt quỹ ca | Không ghi khoản chi vào quỹ ca, cuối ca két lệch | Ghi khoản chi Nguyên vật liệu vào ca đang mở |
| Nháp ở Kiểm kê | Mọi nguyên liệu dùng chung một nháp: gõ dở một dòng rồi tải lại trang thì mọi dòng bị điền cùng nguyên liệu | Mỗi nguyên liệu một nháp |
| Đổi ngày giao | Đổi được cả lần đặt đã giao đủ, và đổi về ngày đã qua | Chặn cả hai |
| Số quá lớn | "1e999" hay số quá dài có thể làm lỗi máy chủ trên PostgreSQL | Báo "quá lớn"; lớp bắt lỗi chung nhận cả lỗi tràn số của CSDL |
| Giao diện | Kiểm kê, Đặt hàng (hiện cả trăm lần đặt cũ), Phải trả, Phiếu nhập, Hao hụt, Sổ kho trên điện thoại | Làm lại theo mục 9.4 đến 9.8 |


## 24. Rà soát Thu ngân, Dự báo và các dòng mô tả (27/10/2026)

| Việc | Trước | Sau |
|---|---|---|
| Thu ngân, yêu cầu quá hạn mọi cấp | Chỉ báo "quá hạn mọi cấp", không nói ai được thu | Nói rõ người được thu theo món khách thực nhận (người được giao thu ở ca, nếu không có thì Chủ quán); Chủ quán thấy nút "Mở Duyệt" |
| Thu ngân, giao diện | Mã đơn dẫn tới trang chi tiết mà thu ngân không mở được; ô "đã thấy tiền chuyển khoản" luôn hiện | Mã đơn chỉ là liên kết với Chủ quán; ô xác nhận chỉ hiện khi chọn Chuyển khoản; đầu trang ghi số bàn chờ thu và tổng tiền |
| Nhãn việc cần làm ở Kế hoạch mua | "Không cần mua" nằm trong nhóm "Đặt trong 2 ngày", đọc như mâu thuẫn | Đổi thành "Chưa cần mua" (nhãn trong CSDL đổi bằng migration `forecast 0006`) |
| Lưu ý của dự báo | Viết bằng thuật ngữ mô hình ("tiên nghiệm", "nhiễu quan sát" kèm số) | Viết lời thường; lưu ý "khoảng nhận định rất hẹp" chỉ hiện khi chưa đủ số bán |
| Báo cáo nguyên vật liệu | Liên kết sang trang đặt hàng cũ có số khác Kế hoạch mua | Dẫn sang Kế hoạch mua |
| Dòng mô tả trang | Một số trang (Đơn đang mở, Duyệt, Cảnh báo, Tham số, Dự báo, Kế hoạch mua) giấu mô tả trong nút "Giải thích" | Mô tả ngắn hiện ngay dưới tiêu đề |

## 25. Rà soát nhóm Kiểm soát (27/10/2026)

| Việc | Trước | Sau |
|---|---|---|
| Chữ người dùng đọc có mã yêu cầu nội bộ | Ngoại lệ, cảnh báo, hướng dẫn trong form ghi "(BRU-12)", "(BRU-17)", "(BRU-25)", "(AC-45)"; thông báo lỗi ghi "(BRU-24, NFR-22)" | Bỏ mã ở nơi tạo; dữ liệu đã lưu trước đó được lọc khi hiển thị (bộ lọc `loi_thuong`) |
| Số và tháng trong ngoại lệ | "(8.33%)", "12.00%", "tháng 2026-10", số lượng không có dấu chấm ngăn nghìn | "8,33%", "12%", "tháng 10/2026", "1.094 gram" |
| Ngoại lệ thanh toán theo món thực nhận | Chi tiết in nguyên cấu trúc dữ liệu `{'table': ..., 'total': ...}` | "Tiền đơn 37.000 đ, thu theo món thực nhận 25.000 đ." |
| Danh sách ngoại lệ | Dòng tiêu hao vượt mức không ghi nguyên liệu nào; nhãn "Quá hạn xem xét" dài lặp ở mọi dòng | Ghi nguyên liệu, nhân viên, mã đơn; lọc theo loại kèm số mục; xem lần lượt (mục 10) |
| Chi tiết ngoại lệ | Ô "Quy tắc kích hoạt" cắt chữ, tràn ngang trên điện thoại; chuỗi thao tác ghi tên đăng nhập | Quy tắc là dòng mô tả dưới tiêu đề; diễn biến ghi tên nhân viên |
| Cảnh báo | Hơn 30 thẻ liền nhau, mỗi thẻ ba nút và một ô nhập | Gom theo loại, nút Đóng gọn lại (mục 11) |
| Thu hồi tổn thất | Ghi được số âm, vượt giá trị đã xác minh, hoặc trước khi xác minh; gõ "82.000" báo lỗi | Chặn cả ba; đọc số kiểu Việt Nam |
| Đọc số | Hai bản riêng ở Kho và các màn khác | Dùng chung `apps/core/numbers.py` |

Migration `catalog 0004` và `inventory 0012` chỉ đổi chữ hướng dẫn của trường, không đổi dữ liệu.


## 26. Rà soát Báo cáo, Dữ liệu nền, Tham số và Nhật ký (27/10/2026)

| Việc | Trước | Sau |
|---|---|---|
| Ô số trong Dữ liệu nền | Ô kiểu số của trình duyệt: gõ "25.000" vào giá món, giá tùy chọn hay lương giờ thì lưu thành 25 đ; gõ "1.000" vào quy cách hay tồn an toàn thì báo lỗi; giá hiện "29000" | Ô chữ đọc số kiểu Việt Nam ("25.000", "25,000", "1.000,5"), hiện lại có dấu chấm ngăn nghìn; gõ sai thì báo "Nhập số nguyên, ví dụ 25.000" (`numbers.SoNguyenField`, `numbers.SoThapPhanField`, dùng cho mọi form Dữ liệu nền, form Nhân viên và ô Tồn đầu kỳ) |
| Bảng Dữ liệu nền | Số lẻ hiện "1000,00"; ô chọn để trống hiện "---------" | "1.000", "1.500,5"; ô chọn để trống ghi "Chưa chọn" |
| Quy tắc xuất lô | Ghi tắt FEFO, FIFO, LIFO trên bảng kho, phiếu lấy hàng, form nguyên liệu | "Theo hạn", "Nhập trước", "Nhập sau"; tên đầy đủ "Hết hạn trước, xuất trước"…; ô để trống ghi "Tự chọn theo hạn dùng". Giá trị lưu trong CSDL giữ nguyên (`fefo`, `fifo`, `lifo`); migration `inventory 0013` chỉ đổi nhãn |
| Dữ liệu nền trên điện thoại | Bảng 8 cột co lại, chữ xuống dòng từng từ, phải kéo ngang | Mỗi dòng thành một thẻ "nhãn: giá trị", chạm cả thẻ để mở; nút Mới cạnh tiêu đề |
| Tham số | Gõ "2.5" bị hiểu thành 25, "50,000" báo lỗi; giá trị hiện "50000"; chữ đơn vị "% hạn dùng" đè lên "hiệu lực từ"; trên điện thoại mỗi tham số chiếm năm hàng | Chỉ nhận số nguyên ("50.000", "50,000"), số lẻ báo lỗi thay vì đoán; hiện "50.000"; đơn vị không đè; điện thoại: giá trị, đơn vị và nút Lưu cùng một hàng |
| Nhật ký thao tác | Cột Thay đổi in nguyên cấu trúc dữ liệu (`{'so_tien': 82000, 'cung_giao_dich': ...}`, `{'pack_size': '1000.00'}`); bộ lọc loại dữ liệu ghi `inventory.Ingredient` | Mỗi thay đổi một dòng "Số tiền: 82.000", "Quy cách đóng gói: ~~50~~ → 1.000"; mã liên kết đổi thành tên; lựa chọn đổi thành nhãn; loại dữ liệu ghi bằng chữ ("Nguyên vật liệu") (`apps/audit/display.py`). Dữ liệu nhật ký không đổi |
| Báo cáo | Mã chỉ tiêu "BO-01", "BO-02" trên trang; chú giải biểu đồ hiện "theo=ngay"; điểm hôm nay chưa hết ngày kéo đường doanh thu xuống 0 | Ghi "Mục tiêu tháng"; chú giải đúng; điểm hôm nay ghi "(hôm nay, tính đến giờ)" và bỏ khi chưa có doanh thu; trang Kiểm soát doanh thu và Nguyên vật liệu có chọn kỳ nhanh |

Nhớ chạy `python manage.py migrate` sau khi cập nhật (migration `inventory 0013`).

## 27. Rà soát Kế hoạch mua, Dự báo, Hao hụt và kiểm kê, Quầy (27/10/2026)

| Việc | Trước | Sau |
|---|---|---|
| Số lượng đặt ở Kế hoạch mua và Đặt theo dự báo | Gõ "1.000" (như màn hình hiển thị) thì lưu thành 1; ô hiện "5900" không có dấu chấm | Đọc số kiểu Việt Nam qua `numbers.qty`; ô hiện "5.900"; thông báo "Đã tạo đơn Nháp 5.900 ml" |
| Dự báo từng món | Cột ngày ghi "2026-10-26"; bảng 60 ngày dài trước, tổng nhiều ngày ở cuối | Ghi "T2 26/10"; tổng 1, 3, 7 ngày lên đầu; bảng từng ngày hiện 14 ngày, phần còn lại gập trong "Xem thêm" |
| Hao hụt và kiểm kê tháng (trước tên "Báo cáo nguyên vật liệu") | Hai bảng thô hơn 200 dòng; bảng kiểm kê chỉ lấy 50 lần đầu mà không báo; đơn vị "g" lẫn "gram" | Ô tóm tắt (thiếu nguyên liệu so mục tiêu, số kỳ tiêu hao vượt mức, số lần kiểm kê chờ xác nhận); mỗi nguyên liệu một dòng, chi tiết từng kỳ, từng lần gập lại và không cắt; chuyển tháng trước, sau; trên điện thoại bảng thành thẻ |
| Thời gian chờ | "546 phút · trễ" ở Quầy pha chế, Tổng quan ca, Cảnh báo | "9 giờ 6 phút · trễ" (bộ lọc `phut`) |
| Thông báo dữ liệu cá nhân | "Phiên bản 2026-10-12" | "Phiên bản ngày 12/10/2026" |

## 28. Rà soát Phiếu dự phòng, Quỹ ca và quay lại trang sau khi gửi (27/10/2026)

| Việc | Trước | Sau |
|---|---|---|
| Tiền ở Quỹ ca (tiền mặt đếm được, chi, chuyển khoản) | "1 390 000 đ" hoặc "1.390.000 đ" báo lỗi; "2.5" thành 25 đồng | Đọc số kiểu Việt Nam qua `numbers.vnd`; số 0 hợp lệ, số âm báo "không được âm" |
| Đơn giá ở Phiếu dự phòng | "25,000" báo lỗi tiếng Anh của Python | Đọc số kiểu Việt Nam; lỗi báo bằng câu "Đơn giá dòng … " |
| Lỗi nhập ở Phiếu dự phòng, Kho, Lịch ca | Có chỗ in nguyên câu lỗi tiếng Anh ("invalid literal for int()…") | Câu lỗi tiếng Anh đổi thành "Dữ liệu nhập không hợp lệ; kiểm tra lại các ô số và ngày giờ." (`apps/core/errors.py`) |
| Tùy chọn món ở Phiếu dự phòng | Danh sách ô đánh dấu dài, không nhóm, không ghi giá thêm | Mỗi nhóm một hàng, tùy chọn là nút bấm ghi giá thêm ("+5.000") |
| Quay lại sau khi gửi (Hủy lô, Kho, Quỹ ca, Chấm công) | Ô `next` gửi lên được dùng nguyên: chữ lạ như "-5" gây trang lỗi máy chủ, địa chỉ trang ngoài thì đưa người dùng sang trang đó | Chỉ quay lại đường dẫn của chính trang web; khác đi thì về trang mặc định (`apps/core/links.py`) |

## 29. Rà soát Tra cứu đơn, Quầy, Thu ngân, Tồn kho và Tải theo giờ (27/10/2026)

| Việc | Trước | Sau |
|---|---|---|
| Tra cứu đơn | Chín ô lọc chiếm cả màn hình điện thoại; bảng 7 cột bị bóp, trạng thái cắt chữ; tổng tiền chỉ tính trang đang xem | Ô tìm và nút Tìm một hàng, các bộ lọc khác gập trong "Lọc thêm" (tự mở và ghi số điều kiện khi đang dùng); trên điện thoại mỗi đơn một thẻ, trạng thái có màu; dòng "3.779 đơn · tổng tiền …" tính trên mọi đơn khớp bộ lọc |
| Quầy pha chế | Đơn có yêu cầu đổi món, hủy món hay chuyển bàn đang chờ duyệt vẫn hiện như đơn thường, quầy có thể pha món sắp bị đổi | Phiếu ghi "Đang chờ duyệt: Đổi 1 × Trà sữa L sang 1 × Cà phê đen L" |
| Thu ngân | Câu báo quá hạn duyệt gọi người đang xem bằng tên ở ngôi thứ ba; danh sách một lý do vẫn có dấu chấm đầu dòng | "Người được ủy quyền thu tiền của ca (tên) thu tiền theo món khách thực nhận…"; một lý do thì không có dấu đầu dòng |
| Tồn kho trên điện thoại | Bảng 8 cột phải kéo ngang | Mỗi nguyên liệu một thẻ: có thể dùng, đủ dùng mấy ngày, lô lấy trước, giá trị, tình trạng |
| Kiểm kê | "Đếm 3.771, sổ 4.285 ml" | "Đếm được 3.771, trên sổ 4.285 ml" |
| Quỹ ca | Sau hạn vẫn ghi "Hạn báo cáo cuối ca 00:00 27/10" như chưa tới hạn | "Đã quá hạn báo cáo cuối ca (00:00 27/10)"; trước hạn ghi "Cần xong trước hạn …" |
| Tải và thời gian chờ | Ly còn chờ từ tối hôm trước tạo các khung 0–1 giờ, 1–2 giờ… toàn số 0; ngày chưa có đơn chỉ báo trống | Ngoài giờ mở cửa chỉ hiện khung có đơn thật; ngày trống có liên kết xem ngày trước |
| Số đếm ở phân trang | "18708 dòng" | "18.708 dòng" |

## 30. Rà soát tải tệp, chi tiết đơn, kết ca và dữ liệu mẫu (27/10/2026)

| Việc | Trước | Sau |
|---|---|---|
| Ảnh hóa đơn nhập hàng, ảnh chứng từ khoản chi | Nhận mọi tệp, kể cả tệp HTML hay SVG; tệp được phục vụ lại cùng tên miền nên người mở "chứng từ" có thể chạy mã lạ trong phiên của mình | Chỉ nhận ảnh JPG, PNG, WEBP, HEIC hoặc PDF, xét cả đuôi tệp lẫn những byte đầu tệp, tối đa 10 MB (`apps/core/uploads.py`) |
| Nhập lịch sử bán | Tệp lưu bảng mã khác in lỗi Python ("'utf-8' codec can't decode…"); ngày ghi "2026-08-01"; ô chọn tệp chỉ cho chọn CSV dù hệ thống đọc được Excel | Báo "Trong Excel chọn Lưu thành CSV UTF-8 rồi nhập lại, hoặc nhập thẳng tệp .xlsx"; ngày dd/mm/yyyy; chọn được cả .xlsx |
| Câu báo gửi trùng biểu mẫu | "Mã nghiệp vụ này đã được dùng cho một yêu cầu khác" | "Biểu mẫu này đã được gửi trước đó với nội dung khác (có thể do bấm Quay lại). Tải lại trang rồi nhập lại." |
| Chi tiết đơn | Nhật ký thiếu lúc gửi và lúc duyệt yêu cầu điều chỉnh; bảng món 8 cột bóp chữ trên điện thoại | Có đủ; mỗi món một thẻ, cột hủy chỉ hiện khi có hủy, trạng thái có màu |
| Kết ca | Còn đơn chưa thu hay yêu cầu chờ duyệt vẫn hiện nút Kết ca, bấm mới báo lỗi | Nút mờ kèm câu nói cần làm gì: thu tiền ở Thu ngân, chờ Chủ quán duyệt, hoặc chuyển đơn sang ca sau |
| Báo cáo điều chỉnh của ca | Bảng 7 cột bóp chữ trên điện thoại; không dẫn tới đơn | Mỗi yêu cầu một thẻ, bấm để mở đơn |
| Nhật ký thao tác | Tỷ lệ hiện "8.33%", "0.00%" | "8,33%", "0%" |
| Trang chủ của Phục vụ | Thẻ lọc "Trang chủ" trong Chức năng bấm vào không có gì | Ẩn khi không có chức năng nào; nhóm ghi là "Tổng quan" |
| Lệnh `tao_du_lieu_nghiem_thu` | Dừng giữa chừng với lỗi "Số lượng đếm được phải lớn hơn 0" khi nhập bù phiếu dự phòng làm sổ kho âm | Chạy hết 14 ngày; lần kiểm kê đó ghi đếm được 0 kèm lý do |

## 31. Rà soát bảng trên điện thoại, ngày lạ trên địa chỉ trang và tốc độ (27/10/2026)

| Việc | Trước | Sau |
|---|---|---|
| Chuyển đơn sang ca khác | Chuyển được cả đơn đã thu tiền, đơn đã hủy, đơn của ca đã kết, và chuyển ngược sang ca bắt đầu sớm hơn | Chỉ chuyển đơn chưa thu tiền của ca đang mở sang ca bắt đầu sau ca đó |
| Bảng trên điện thoại | Báo cáo nguyên liệu, kiểm soát doanh thu, kế hoạch mua, danh sách lô và chi tiết lô, ca gần đây, dự báo, ma trận thực đơn, nhật ký thao tác, báo cáo kho phải kéo ngang | Mỗi dòng một thẻ "nhãn: giá trị"; bảng còn lại có lề ô hẹp hơn để vừa màn hình |
| Bảng kích cỡ, tùy chọn, định mức trong Quản trị | Ô nhập xếp ngang, phải kéo ngang | Mỗi dòng một thẻ, nhãn bên trái, ô nhập bên phải |
| Ngoại lệ theo loại (Kiểm soát doanh thu) | Trên điện thoại có cột trống bên trái | Tên loại sát lề trái |
| Ngày lạ trên địa chỉ trang | `?tu=9999-12-31` ở báo cáo, tra cứu đơn, sổ kho, lịch làm, tải theo giờ báo lỗi máy chủ | Ngày sai định dạng hoặc ngoài năm 2000–2099 bị bỏ qua, trang dùng ngày mặc định (`apps/core/dates.py`) |
| Màn tạo đơn và số ly còn đáp ứng | Mỗi kích cỡ, mỗi tùy chọn đọc định mức riêng: 180 truy vấn mỗi lần mở, tăng theo số món | Đọc định mức hiện hành của mọi món một lần: 24 truy vấn, không đổi khi thêm món |
| Lịch làm tuần | Mỗi ca, mỗi vị trí đọc lại người thay thế và ca trùng giờ: 299 truy vấn | Đọc một lần cho cả tuần: 21 truy vấn |
| Báo cáo doanh thu, bảng điều khiển, xuất Excel doanh thu | Đọc lại toàn bộ dòng món của kỳ cho từng phần (xuất Excel đọc 14 lần) | Đọc một lần dùng chung; tổng kỳ trước tính trong cơ sở dữ liệu. Với 56 ngày dữ liệu mô phỏng: xuất Excel 4,7 giây còn 1,1 giây |

## 32. Rà soát trợ năng và trang Tải (27/10/2026)

| Việc | Trước | Sau |
|---|---|---|
| Phiếu dự phòng | Ô chọn ca có mã `i-shift` trùng mã biểu tượng Ca, biểu tượng Ca trên thanh điều hướng biến mất ở trang này | Đổi mã ô nhập; có kiểm thử chặn mã trùng biểu tượng |
| Bảng kích cỡ, tùy chọn, định mức trong Quản trị | Ô nhập không có nhãn, trình đọc màn hình chỉ đọc "ô nhập" | Mỗi ô có nhãn theo tiêu đề cột (bộ lọc `nhan`) |
| Trang Tải và thời gian chờ | Chữ thống kê "trung vị"; bảng 9 cột phải kéo ngang trên điện thoại | "Thời gian khách chờ món", câu quá tải nói bằng lời thường; mỗi khung giờ một thẻ |
| Biểu đồ rộng trên điện thoại | Biểu đồ cả hàng (doanh thu theo ngày, số ly theo giờ) thu nhỏ còn chữ khoảng 5 px | Giữ bề rộng tối thiểu lớn hơn, chữ khoảng 9 px, vuốt ngang để xem hết |

## 33. Rà soát cài mới: đi từ cơ sở dữ liệu trống tới một ca trọn vẹn (27/10/2026)

Đi thử như một quán vừa cài: chỉ có tài khoản Chủ quán, khai báo bàn, món, công thức, nguyên liệu, tồn đầu kỳ, nhân viên, mở ca, gọi món, pha, mang ra, thu tiền, kết ca và báo cáo cuối ca.

| Việc | Trước | Sau |
|---|---|---|
| Trang chủ khi chưa khai báo gì | Thẻ "Dữ liệu nền" đếm 0 mà không nhắc; tên thẻ khác tên mục "Quản trị" trên thanh điều hướng | Thẻ "Quản trị"; số 0 bàn, 0 món đang bán, 0 nhân viên, 0 nguyên liệu tô màu cảnh báo |
| Màn gọi món chưa có bàn hoặc món | Nói chung chung "chưa có dữ liệu" | Nói rõ nơi khai báo: "Chủ quán khai báo bàn ở Quản trị, mục Bàn", "Chủ quán mở bán ở Quản trị, mục Món và giá" |
| Tạo mới nhân viên, nguyên liệu, món | Lưu xong về danh sách, phải tìm lại để đặt mật khẩu, ghi tồn đầu kỳ hay thêm kích cỡ | Lưu xong mở luôn trang của bản ghi để làm tiếp bước đó |
| Ghi tồn đầu kỳ | Chỉ có số lượng; lô luôn "chưa rõ hạn"; giá trị tồn bằng 0 cho tới lần nhập hàng đầu | Thêm hạn sử dụng trên bao bì và giá mua mỗi đơn vị (không bắt buộc); câu xác nhận ghi rõ số lượng và đơn vị |
| Trang Tồn kho | Nguyên liệu chưa ghi tồn đầu kỳ hoặc đã hết sạch vẫn ghi "Ổn" | "Chưa ghi tồn đầu kỳ" kèm đường dẫn ghi ngay; "Hết hàng" khi đã dùng hết; cả hai tính vào "Dưới mức tồn an toàn" |
| Thu tiền một đơn | "Đã thu … cho các đơn 2710-001" | "… cho đơn 2710-001" |
| Kết ca còn vướng | Câu nhắc chung "thu tiền các bàn, chờ Chủ quán duyệt" cả khi vướng chỉ là chưa xác nhận tiền đầu ca | Mỗi mục vướng nói cách gỡ (ví dụ "ghi số tiền nhận bàn giao ở mục Ghi quỹ tiền mặt, két trống thì ghi 0"); câu thu tiền chỉ hiện khi còn đơn chưa thu |
| Đối soát cuối ca, đính chính | Số tiền không có "đ"; viết tắt "CK" | Có đơn vị; ghi đủ "chuyển khoản" |
| Kế hoạch mua một nguyên liệu | Bảng đơn đặt, các kỳ dự kiến và quyết định phải kéo ngang trên điện thoại | Mỗi dòng một thẻ |
| Kho khi chưa khai báo | Phiếu nhập, đặt hàng, hao hụt, kiểm kê, báo nhanh hiện ô chọn trống, không biết phải làm gì | Câu "Chưa có nguyên liệu nào đang dùng" hoặc "Chưa có nhà cung cấp nào" kèm đường dẫn thêm (Chủ quán) |
| Phiếu dự phòng khi chưa mở ca | Ô chọn ca trống, bấm Cấp dãy báo lỗi | Nói chưa có ca đang mở và chỉ chỗ mở ca |
| Tình trạng ca, báo cáo nguyên liệu khi chưa có dữ liệu | Bảng chỉ có hàng tiêu đề | Câu "Chưa có ca nào", "Chưa có nguyên liệu nào đang dùng" |
| Lịch của tôi | Nhắc "Bạn chưa đăng ký ca tuần sau" cả khi Chủ quán chưa tạo ca nào cho tuần sau | Chỉ nhắc khi tuần sau đã có ca để đăng ký |
| Người làm nhiều vị trí | Lời chào và trình đơn tài khoản chỉ ghi vị trí chính; vào ca chọn sẵn vị trí đầu danh sách | Ghi đủ, ví dụ "Thu ngân, Phục vụ"; vào ca chọn sẵn vị trí của ca trong lịch, không có thì vị trí chính |
| Ảnh đại diện chữ cái | Lấy chữ đầu của họ ("Nguyễn Văn An" thành N) | Lấy chữ đầu của tên gọi (A), giống góc trên màn hình |
| Tổng quan ca khi chưa mở ca | Câu "Chưa có ca nào đang mở" lặp hai lần | Một lần, tiêu đề ghi ngày |
| Việc chờ xử lý trên trang chủ (điện thoại) | Bảy ô số 0 chiếm nửa màn hình | Ô có việc lên trước; ô số 0 ẩn trên điện thoại, không có việc nào thì ghi "Không có việc nào đang chờ" |
| Chênh lệch tiền nhỏ khi đối soát | Chỉ hiện "-2.000 đ", không nói có cần làm gì | "Trong mức cho phép nên không phải giải trình; vẫn được cộng vào thiếu tiền tích lũy của tháng" |
| Ô đính chính báo cáo cuối ca | Số điền sẵn "48000" | "48.000" như các ô tiền khác |
| Ca của tôi khi chưa có ca | Bảo Chủ quán "chỉ định người duyệt, người duyệt dự phòng" (đã bỏ từ 12/10) và dẫn tới danh sách ca | Nút "Mở ca mới" mở thẳng biểu mẫu, tên ca và giờ điền sẵn theo ca gần nhất |
| Phiếu pha chế in ra | Đầu phiếu đếm số dòng ("2 món" dù một dòng 3 ly); in lại sau khi hủy bớt ly vẫn ghi số ly cũ | Đếm số ly; mỗi dòng ghi số ly còn phải pha |
| Hoàn tiền đã duyệt | Chỉ hiện ở Ca của tôi, thu ngân ở màn Thu ngân không thấy; chưa mở ca vẫn bấm được "Đã hoàn tiền" rồi mới báo lỗi | Hiện cả ở Thu ngân và trong Việc chờ xử lý trên trang chủ; chưa có ca đang mở thì nút mờ kèm câu giải thích |
| Tên yêu cầu hủy hóa đơn | "… 50.000 đồng" | "… 50.000 đ" như mọi chỗ khác |
| Cảnh báo ngoại lệ (hủy hóa đơn đã thanh toán, điều chỉnh bị từ chối…) | Chỉ ghi tên loại, không biết đơn nào; ngoại lệ gộp nhiều lần ghi lặp cả đoạn | Ghi mã đơn và nội dung lần mới nhất, ví dụ "Đơn 2710-001 · Hủy hóa đơn đã thanh toán 50.000 đ · duyệt bởi Lâm"; cảnh báo đang mở được cập nhật theo |
| Số lượng trong câu báo kho | "Tổng thiếu 1311 ml", "cần 2000 gram" | "1.311 ml", "2.000 gram" |
| Báo cáo kho khi chưa có dữ liệu | Vẽ đường giá trị tồn nằm ở 0 với trục 0–4; nút "Bảng số liệu" mở ra toàn số 0 | Câu "Chưa có dữ liệu trong kỳ"; bảng số liệu chỉ hiện khi có biểu đồ |
| Lịch làm tuần trống | "Tuần này chưa có ca" khi đang xem tuần sau | Ghi đúng tuần đang xem, ví dụ "Tuần 02/11 – 08/11 chưa có ca" |
| Trang lỗi khi chạy thật (`DJANGO_DEBUG=false`) | Trang 404 và 500 mặc định của Django bằng tiếng Anh | Trang tiếng Việt: "Không tìm thấy trang này", "Có lỗi xảy ra" kèm cách làm tiếp |
| Đổi mật khẩu | Nhân viên không tự đổi được, phải nhờ Chủ quán đặt lại | Mục "Đổi mật khẩu" trong trình đơn tài khoản: nhập mật khẩu đang dùng và mật khẩu mới, vẫn giữ đăng nhập trên máy đang dùng, các máy khác phải đăng nhập lại; có ghi nhật ký |
| Mật khẩu quá ngắn | Câu báo tiếng Anh "This password is too short…" (bản dịch của Django thiếu câu này) | "Mật khẩu quá ngắn, cần ít nhất 8 ký tự." ở cả trang đổi mật khẩu và trang Chủ quán đặt lại |
| Số trong chú thích biểu đồ và nhãn đọc màn hình | "tải 2.0", "khoảng 10%–90%: 27160–33950", "đang xử lý 20000 đồng" | "tải 2", "mức thấp 27.160, mức cao 33.950", "20.000 đồng" |
| Số lượng lớn ở trang lô hàng, tồn kho, dự báo, lịch tuần | "Có thể bỏ 1946 ml" | "Có thể bỏ 1.946 ml" |
| Nhập lịch sử bán không có dòng nào khớp | Vẫn tạo một lần nhập rỗng, báo "Đã nhập 0 ly trong 0 ngày ( đến )" | Báo "Không nhập được tệp: Không có dòng nào nhập được (…)" kèm lý do, không tạo lần nhập; nhập được một phần thì kể số dòng bị bỏ qua (ngày hỏng, ngày từ hôm nay trở đi); bảng các lần nhập mở ra xem được tên món không khớp |
| Trả nhà cung cấp bằng tiền mặt quỹ ca khi chưa mở ca | Chọn được, bấm rồi mới báo lỗi | Lựa chọn bị làm mờ, ghi "(chưa mở ca)" |
| Ghi chú Điều chỉnh theo mùa | Nhắc tới "mô hình" và cách trừ phần đã học | Chỉ ghi khi nào dùng và phải có căn cứ |
| Dấu phẩy trong tên khi ghi số tiền | Câu ngoại lệ "Đổi … sang Trà đào M (Ít đá. Ít đường)": mọi dấu phẩy trong câu bị đổi thành dấu chấm cùng với số tiền | Chỉ số tiền được định dạng, chữ giữ nguyên "(Ít đá, Ít đường)"; sửa ở câu ngoại lệ, khoản nộp chờ xác nhận, nhãn món ở màn duyệt, chú thích biểu đồ |
| Hạn sử dụng gõ nhầm năm | Nhập "2062" thay vì "2026" vẫn lưu, lô coi như không bao giờ hết hạn | Báo "Hạn sử dụng (27/10/2062) quá xa so với hôm nay; kiểm tra lại năm." ở phiếu nhập, tồn đầu kỳ và sửa lô (chấp nhận trong khoảng 2 năm trước tới 5 năm sau) |
| Ngày giao dự kiến khi đặt hàng | Để trống báo lỗi chung; gõ nhầm năm (2062) vẫn lưu, lần đặt không bao giờ bị coi là giao chậm | "Chọn ngày giao dự kiến.", "Ngày giao không được trước hôm nay.", hơn một năm thì "kiểm tra lại năm"; áp dụng ở màn Đặt hàng, đổi ngày giao, chấp nhận kế hoạch mua và Đã báo nhà cung cấp |
| Hạn trả sau ở phiếu nhập | Gõ chữ hay số rất lớn thì lỗi chung hoặc hạn trả tới năm 2300 | "Hạn trả sau là số ngày, từ 0 tới 365." |
| Ca tiền dài bất thường | Gõ nhầm tháng kết thúc (27/11 thay vì 27/10) vẫn lưu ca dài 31 ngày | "Một ca dài quá 24 giờ; kiểm tra lại ngày kết thúc." |
| Bổ sung giờ ra chọn nhầm ngày | Giờ ra rơi vào ngày hôm sau vẫn lưu, lượt làm 29 giờ được tính lương | Lượt làm dài hơn 18 giờ thì báo "kiểm tra lại ngày giờ ra" kèm giờ vào ca |
| Đơn giá ở phiếu nhập | Gõ giá theo kg hay theo hộp (65.000 thay vì 65 đ/gram) vẫn lưu, giá vốn và giá trị tồn sai gấp nghìn lần mà không ai biết | Dưới mỗi dòng hiện "Lần nhập trước 65 đ/gram"; lệch quá 3 lần thì chuyển màu cảnh báo "kiểm tra đơn vị tính"; lưu xong vẫn báo lại dòng có giá lệch |
| Hết phiên đăng nhập khi đang soạn đơn (để máy 15 phút) | Bấm gửi thì báo "Chưa chắc đơn đã tới máy chủ, bấm gửi lại", gửi lại mãi vẫn không được; đăng nhập lại thì rơi vào trang trắng | Đầu trang hiện "Phiên đăng nhập đã hết hạn. Nội dung đang soạn trên máy này vẫn còn. Đăng nhập lại"; đăng nhập xong quay về đúng màn đang làm, phiếu đang soạn vẫn còn |
| Mở đường dẫn chỉ dùng để gửi (ví dụ sau khi đăng nhập lại) | Trang trắng | Quay về màn tương ứng (Tạo đơn, Quầy pha chế, Thu ngân…) kèm lời nhắc thao tác trước chưa được lưu |
| Biểu mẫu gửi với mã bảo mật cũ (trang mở lâu, vừa đăng nhập lại ở thẻ khác) | Trang lỗi tiếng Anh "CSRF verification failed" | Trang "Trang đã cũ" bằng tiếng Việt, nút quay lại; màn dùng mã trang (tạo đơn) nhận câu báo tương tự |
| Màn Duyệt khi trống | "Yêu cầu do chính bạn tạo không hiện ở đây; nó được chuyển cho người duyệt khác" (còn từ thời có Quản lý ca; nay chỉ Chủ quán duyệt) | Ghi yêu cầu của nhân viên sẽ hiện ở đây và trên thanh báo đầu trang |
| Yêu cầu điều chỉnh quá thời hạn duyệt | Thông báo "Chuyển cấp duyệt… giờ chờ Quá hạn mọi cấp"; màn thu ngân, tổng quan ghi "quá hạn mọi cấp" | "Quá hạn duyệt: …, thu ngân được thu tiền theo món khách thực nhận"; các màn ghi "quá hạn duyệt"; tham số đổi tên "Thời hạn duyệt yêu cầu điều chỉnh" |
| Báo cáo doanh thu theo ngày hoặc theo ca qua hai tháng | Dòng xếp theo chữ nên 01/10 đứng trước 25/09 (cả trong tệp Excel) | Xếp theo thời gian thật |
| Tổng số ly ở báo cáo doanh thu | Dòng Tổng để trống cột Số ly; số đơn, số ly trên 999 không có dấu chấm ("1442") | Có tổng số ly ở trang và tệp Excel; "1.442" |
| Đăng ký ca khi Chủ quán vừa xóa một ca | Nhân viên bấm Gửi đăng ký thì gặp trang lỗi máy chủ, các ca khác cũng không được lưu | Các ca còn lại được lưu; báo "1 ca vừa bị Chủ quán xóa nên lựa chọn ở ca đó không được lưu" |
| Thêm ca trong Lịch làm mà thiếu giờ | Câu báo chung "Dữ liệu không hợp lệ" hoặc trang lỗi | "Nhập giờ bắt đầu và giờ kết thúc của ca, ví dụ 06:30." |
| Bấm Ra ca trên trang để mở từ hôm trước | Ghi giờ ra là lúc bấm, lượt làm hơn 20 giờ được tính công | Quá 18 giờ thì không ra ca được, báo nhờ Chủ quán bổ sung giờ ra đúng; vào ca khi còn lượt hôm trước chưa ra thì ghi rõ ngày của lượt đó |
| Ô giờ ra ở mục bổ sung giờ ra | Chỉ chặn giờ trước giờ vào | Thêm giới hạn trên: không quá 18 giờ sau giờ vào và không quá hiện tại; giờ gợi ý cũng nằm trong khoảng này |
| Thu tiền khi bàn vừa có thêm đơn | Thu ngân thấy "Thu 150.000 đ", trong lúc đó bàn có thêm đơn đã phục vụ; bấm Thu thì hệ thống ghi cả đơn mới (ví dụ 195.000 đ) trong khi khách chỉ trả 150.000 đ, quỹ ca thiếu | Không thu; báo "Bàn 3 vừa thay đổi: cần thu 195.000 đ, không phải 150.000 đ như trên màn lúc trước", màn Thu ngân hiện số mới để thu lại |
| Hai lần kiểm kê cùng nguyên liệu cùng chờ xác nhận (đếm lại vì nghi đếm sai) | Chủ quán xác nhận cả hai thì tồn bị trừ hai lần (sữa 4.000, đếm 3.600 rồi 3.500: tồn còn 3.100 thay vì 3.500); lần đếm sau đã điều chỉnh rồi vẫn xác nhận được lần cũ | Lần đếm cũ ghi "Đã đếm lại lúc …: lần này đã cũ, chọn Không xác nhận" và chỉ còn nút Không xác nhận; cố xác nhận cũng bị chặn |
| Nhân viên nghỉ việc hoặc bỏ bớt vai trò khi đã được xếp ca tuần sau | Tài khoản bị khóa nhưng tên vẫn nằm trong lịch, ca được tính là đủ người; lịch đã công bố vẫn ghi người đó | Các lượt từ hôm nay ở vị trí người đó không còn đảm nhận được bỏ ra (ghi lý do "Nghỉ việc" hoặc "Không còn đảm nhận vị trí này"), đăng ký tương ứng bị hủy; trang báo "Đã bỏ … ra khỏi N lượt ca từ hôm nay. Xem Lịch làm để xếp người thay", lịch hiện chỗ thiếu |
| Người được ủy quyền thu tiền theo món thực nhận đã nghỉ việc | Ca vẫn ghi người đó; yêu cầu quá hạn duyệt thì không ai thu được (người đó không đăng nhập được, Chủ quán bị từ chối vì ca đã có người ủy quyền) | Coi như ca chưa có người ủy quyền: Chủ quán thu thay, câu báo ở Thu ngân ghi "Chủ quán"; danh sách Ca ghi "(đã nghỉ việc, Chủ quán làm thay)" |
| Khoản nộp giữa ca ghi nhầm người nhận hoặc số tiền | Không có cách bỏ: người nhận đúng không xác nhận được, người bị chọn nhầm không nhận tiền nên không bấm; ca không bao giờ kết được | Người nộp hoặc Chủ quán mở "Ghi nhầm? Bỏ khoản này" ở mục Bút toán của ca, ghi lý do; người nhận có nút "Không nhận được". Chỉ bỏ được khoản chưa xác nhận khi ca còn mở; nội dung khoản giữ trong nhật ký |
| Chọn người nhận tiền nộp giữa ca | Danh sách có cả pha chế, phục vụ; họ không mở được màn Ca của tôi nên không bao giờ xác nhận được, ca bị kẹt. Người nhận (kể cả Chủ quán) không được báo ở trang chủ | Chỉ liệt kê Chủ quán và thu ngân, chọn người khác bị từ chối; trang chủ của người nhận hiện ô "Tiền nộp chờ tôi xác nhận" khi có khoản đang chờ |
| Chọn người được ủy quyền thu tiền theo món thực nhận cho ca | Danh sách có cả pha chế, phục vụ; chọn họ thì không ai thu được bàn có yêu cầu quá hạn duyệt (họ không mở được Thu ngân, Chủ quán bị từ chối) | Chỉ liệt kê Chủ quán và thu ngân; người đã chọn mà không còn vai trò thu tiền thì Chủ quán làm thay |
| Thêm bàn, nhóm món, món, nguyên liệu, nhà cung cấp trùng tên hoặc số với mục đã có | Trang lỗi máy chủ (lỗi trùng của cơ sở dữ liệu), không biết ô nào sai | Báo ngay dưới ô: "Đã có số bàn "5"; đặt khác hoặc sửa mục đã có."; sửa chính mục đó mà giữ tên thì không bị coi là trùng |
| Hai dòng kích cỡ (hoặc tùy chọn) trùng tên trong cùng món | Câu báo "Hãy sửa các dữ liệu trùng lặp cho name ." | "Có hai dòng trùng kích cỡ; mỗi dòng cần khác nhau." |
| Ô số ở Dữ liệu nền gõ ngoài giới hạn | "Đảm bảo giá trị này lớn hơn hoặc bằng với 0 .", "Đảm bảo rằng không có nhiều hơn 2 số thập phân." | "Nhập số từ 0 trở lên.", "Chỉ ghi tối đa 2 chữ số sau dấu phẩy.", "Số quá lớn; kiểm tra lại số đã gõ." |
| Mã đơn sau một năm chạy (mã chỉ có ngày và tháng, ví dụ 2710-001) | Sang năm sau cùng ngày, mỗi đơn mới hỏi cơ sở dữ liệu từng mã của năm trước (năm trước 300 đơn thì 300 lần hỏi cho mỗi đơn), tạo đơn chậm dần | Đọc các mã đã dùng một lần rồi chọn số kế tiếp còn trống; mã vẫn không trùng (đơn đầu ngày năm sau nối tiếp số của năm trước) |
| Sau khi chép mã mới vào máy chạy (runserver) | Trình duyệt có thể vẫn dùng app.css, app.js cũ thêm nhiều giờ (máy chủ thử không ghi hạn lưu, trình duyệt tự đoán): nút mới không có kiểu, phải bấm Ctrl+F5 | Đường dẫn tệp giao diện kèm giờ sửa tệp (`?v=…`) nên bản mới được tải ngay; bản chạy thật vẫn dùng tên tệp có mã băm. Trang mất kết nối vẫn có đủ giao diện |
| Chủ quán xếp thêm hoặc bỏ người khỏi ca sau khi đã công bố lịch tuần | Lịch của tôi đổi theo nhưng người đó không được báo; dễ đi làm theo lịch cũ | Người được xếp thêm hoặc bị bỏ ra nhận thông báo "Lịch làm tuần … thay đổi: Thêm ca 02/11 06:30–14:30 · Pha chế" hoặc "Bỏ ca …" (ca từ hôm nay trở đi) |
| Quên kết ca hôm trước và chưa mở ca hôm nay | Đơn và tiền thu sáng hôm sau âm thầm vào ca hôm trước (ca còn mở được coi là ca đang giữ quỹ); Tổng quan ca ghi "Tính từ 06:00" như ca hôm nay | Ở Thu ngân, Tổng quan ca và Bảng điều khiển: "Ca ngày 26/10/2026 đã quá giờ kết thúc (22:00 26/10) mà chưa kết. Tiền thu lúc này vẫn vào quỹ của ca đó…", kèm đường dẫn kết ca và mở ca mới (Chủ quán); đầu trang ghi ngày của ca khi không phải hôm nay. Trả muộn ít phút sau giờ đóng cửa (dưới 2 giờ) thì không báo |
| Bỏ chọn Đang dùng cho bàn còn đơn chưa thu | Bàn biến khỏi Tổng quan ca và danh sách chuyển bàn; đơn trên bàn đó bị lạc | Không lưu: "Bàn 5 còn 2 đơn chưa thu tiền; thu tiền hoặc chuyển đơn sang bàn khác rồi mới bỏ chọn Đang dùng." |
| Bỏ chọn Đang dùng cho nguyên liệu còn trong định mức của món đang bán | Nguyên liệu biến khỏi Tồn kho, Kiểm kê, Kế hoạch mua nhưng mỗi ly bán ra vẫn trừ kho; không ai thấy để mua thêm | Không lưu: "Sữa đặc còn trong định mức của Bạc xỉu, Cà phê sữa. Áp dụng định mức mới không dùng nguyên liệu này, hoặc chuyển món sang Ngừng bán…" (tính cả định mức đã hẹn ngày áp dụng) |
| Nhóm tùy chọn bắt buộc (ví dụ Mức đường) không còn tùy chọn nào đang dùng | Món vẫn hiện ở màn gọi món nhưng gửi đơn nào cũng bị từ chối "chưa chọn Mức đường" | Món không hiện ở màn gọi món; cột Điều kiện mở bán ghi "Thiếu: tùy chọn đang dùng cho nhóm bắt buộc Mức đường" |
| Nhập bù phiếu dự phòng gõ nhầm ngày (ví dụ tháng 11 thay vì tháng 10) | Được nhận: giá, định mức lấy theo ngày sai, hạn nhập bù tính sai | Thời điểm bán hoặc giờ có mạng lại sau hiện tại bị từ chối: "Thời điểm bán 14:20 27/11/2026 chưa tới; kiểm tra lại ngày giờ ghi trên phiếu." |
| Ghi khoản chi, nộp giữa ca, trả phiếu nhập hoặc trả nhà cung cấp bằng tiền két lớn hơn tiền đang có trong két (thường gõ thừa số 0) | Được nhận; số phải có trong két thành âm, đến lúc kết ca mới thấy chênh lệch lớn | Không lưu: "Két của Ca sáng theo sổ chỉ còn 525.000 đ, ít hơn khoản chi 5.000.000 đ. Kiểm tra lại số tiền đã gõ." Khoản nộp chưa xác nhận coi như đã ra khỏi két; ca chưa xác nhận tiền đầu ca thì câu báo nhắc xác nhận trước |
| Ghi khoản nộp giữa ca cho Chủ quán hay thu ngân | Người nhận chỉ thấy khi mở trang chủ; ca không kết được tới khi họ xác nhận | Người nhận nhận thông báo trên điện thoại "Xác nhận nhận 1.000.000 đ tiền nộp", bấm vào mở thẳng mục xác nhận |
| Nhân viên báo nhanh Đã hết một nguyên liệu | Chủ quán chỉ thấy khi đang mở ứng dụng | Chủ quán nhận thông báo "Đã hết Sữa đặc · Linh báo lúc 15:20" trên điện thoại; báo Sắp hết vẫn chỉ hiện ở trang Kho |
| Tham số gõ ngoài khoảng hợp lý (giờ mở cửa 25, hạn đăng ký thứ 9, ngưỡng kiểm kê 500%, giờ mở cửa sau giờ đóng cửa) | Được lưu; trang Kế hoạch mua, Tình trạng ca và Đăng ký ca báo lỗi máy chủ từ lúc đó (giờ 24, 25 không đọc được) | Báo ngay: "Giờ mở cửa (…): nhập từ 0 đến 23 giờ.", "… nhập từ 2 (thứ Hai) đến 8 (Chủ nhật).", "Giờ mở cửa (6 giờ) phải trước giờ đóng cửa (5 giờ)." Quán mở tới nửa đêm ghi giờ đóng cửa 24 |
| Bỏ một vai trò khỏi hồ sơ nhân viên (ví dụ thu ngân chuyển sang chỉ phục vụ) | Vai trò chọn đầu tiên lúc tạo tài khoản vẫn còn hiệu lực ngầm: người đó vẫn mở được Thu ngân, Quỹ ca dù hồ sơ ghi Phục vụ | Quyền theo đúng các vai trò đang chọn trong hồ sơ (kể cả dữ liệu cũ chưa lưu lại); tài khoản tạo với vai trò Chủ quán vẫn là Chủ quán và hồ sơ hiện ô Chủ quán đã chọn |
| Chủ quán sửa hồ sơ của chính mình sang Nghỉ việc hoặc bỏ ô Chủ quán | Tài khoản bị khóa hoặc mất quyền ngay; nếu là Chủ quán duy nhất thì không ai vào được Dữ liệu nền để mở lại | Không lưu: "Không tự chuyển mình sang Nghỉ việc hay bỏ vai trò Chủ quán của chính mình; nhờ một Chủ quán khác làm nếu thật cần." |
| Máy dùng chung ở quầy: phục vụ A soạn dở phiếu order rồi đăng xuất, phục vụ B đăng nhập | B thấy nguyên phiếu của A và có thể gửi đơn dưới tên mình; nội dung form nhập dở (quỹ ca, phiếu nhập) cũng hiện cho người sau | Nháp lưu theo từng tài khoản: B thấy phiếu trống, A đăng nhập lại thì phiếu dở vẫn còn |
| Bấm Đăng xuất trong ứng dụng đã cài (hoặc gửi biểu mẫu sau khi hết phiên) | Trang hiện một đoạn chữ JSON "Phiên đăng nhập đã hết hạn…" thay vì về trang đăng nhập: qua service worker, trình duyệt đánh dấu lần mở trang giống yêu cầu của mã JavaScript | Phân biệt theo chế độ mở trang (`Sec-Fetch-Mode: navigate`): đăng xuất về trang đăng nhập; hết phiên khi gửi biểu mẫu thì về trang đăng nhập rồi quay lại; mã bảo mật cũ hiện trang báo tiếng Việt |
| Phục vụ, thu ngân, pha chế bật thông báo trên điện thoại | Chỉ trang Cảnh báo (Chủ quán, pha chế) có nút bật; phục vụ và thu ngân không bật được nên không nhận lịch làm, tiền nộp chờ xác nhận | Khối "Thông báo trên điện thoại" ở cuối Lịch của tôi; máy chủ chưa gửi được thì khối ẩn với nhân viên (Chủ quán vẫn thấy lý do ở trang Cảnh báo) |
| Máy dùng chung: người trước đã bật thông báo rồi đăng xuất | Máy vẫn hiện thông báo của người trước (lịch làm, yêu cầu duyệt), người đang dùng không nhận gì | Đăng xuất thì thôi gửi thông báo của người đó tới máy này; người đăng nhập sau (đã cho phép thông báo) tự nhận thông báo của mình trên máy đó |
| Thu ngân mở sẵn màn Thu ngân trong lúc phục vụ mang món ra, khách gọi thêm | Màn đứng yên: bàn vẫn ghi "chưa phục vụ xong" tới khi thu ngân tự tải lại; bàn mới chờ thu không hiện | Mỗi 8 giây màn kiểm tra; có thay đổi thì nổi một khung ở dưới "Các bàn vừa có thay đổi… Tải lại danh sách". Không tự tải lại để nút Thu tiền không đổi chỗ dưới tay thu ngân |
| Thu ngân gõ nhầm tiền đầu ca, hoặc ghi khoản chi trước rồi mới xác nhận tiền đầu ca | Không có chỗ sửa tiền đầu ca; ô "Xác nhận tiền đầu ca" biến mất ngay khi ca đã có một khoản bất kỳ, nên két lệch suốt ca | Ô xác nhận còn hiện tới khi ca đã có tiền đầu ca. Người đã xác nhận hoặc Chủ quán sửa ở "Gõ nhầm? Sửa tiền đầu ca" (phải ghi lý do, có nhật ký thay đổi); không nhận số làm két theo sổ bị âm |
