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

Chọn nhà cung cấp, từng dòng nguyên liệu, số lượng thực nhận, đơn giá, hạn sử dụng in trên bao bì, số lô của nhà sản xuất (không bắt buộc), lần đặt liên quan. **Luôn phải có ảnh hóa đơn** (AC-55). Không nhập được lô đã quá hạn. Mỗi dòng tạo một lô mã `<mã phiếu>/<số dòng>`; dòng để trống hạn mà nguyên liệu có thời hạn sử dụng thì hạn được ước tính bằng ngày nhập cộng thời hạn. Lưu phiếu thì tăng tồn vật lý và tạo khoản phải trả:

- *Trả sau*: hạn trả theo số ngày chọn; Chủ quán ghi thanh toán từng phần ở `/kho/phai-tra/`.
- *Trả ngay bằng quỹ ca*: tự ghi một khoản chi "Nguyên vật liệu" vào quỹ ca đang giữ (GD-09).
- Gắn lần đặt: cập nhật Đã giao đủ / Giao một phần; nhận vượt số đặt vẫn ghi nhưng báo cho Chủ quán.

### 9.5. Kiểm kê (FR-25) — `/kho/kiem-ke/`

Nhập số đếm được. Hệ thống so với tồn vật lý **lúc đếm**:

- Chênh lệch trong ngưỡng 5%: điều chỉnh ngay.
- Vượt ngưỡng: bắt buộc ghi lý do, chờ Chủ quán xác nhận. Khi xác nhận, hệ thống điều chỉnh đúng phần chênh lúc đếm, nên các biến động phát sinh trong lúc chờ không bị xóa.
- Tồn sổ sách bằng 0 hoặc âm thì mọi chênh lệch đều coi là vượt ngưỡng.
- Thiếu kiểm kê tích lũy trong tháng của một nguyên liệu vượt ngưỡng (mặc định bằng một quy cách) → ngoại lệ kèm tên người kiểm kê (AC-58).
- Kiểm kê nguyên liệu **trọng yếu** được áp dụng → đối chiếu tiêu hao với lần kiểm kê trước (FR-16): tiêu hao thực tế = kiểm kê trước + nhập − kiểm kê này − hao hụt; so với tiêu hao theo đơn; lệch quá 5% → ngoại lệ.
- Kiểm kê xong tự đóng các đề nghị kiểm kê lại của nguyên liệu đó.

### 9.6. Hao hụt (FR-26) — `/kho/hao-hut/`

Chọn lý do bắt buộc (hư hỏng, hết hạn, đổ vỡ, pha hỏng, khác), số lượng, và lô bị hỏng nếu biết. Để trống lô thì hệ thống trừ theo thứ tự lấy lô; lý do Hết hạn thì trừ lô quá hạn trước. Giảm tồn vật lý. Không được ghi vượt tồn vật lý trên sổ; sổ sai thì kiểm kê trước. Chủ quán có thể đánh dấu *sự cố đơn lẻ* để không làm lệch tỷ lệ hao hụt khi dự báo.

### 9.7. Đặt hàng (FR-30) — `/kho/dat-hang/`

Ghi lần đặt: nhà cung cấp, nguyên liệu, số lượng, ngày giao dự kiến. Trạng thái Nháp → Đã đặt → Giao một phần → Đã giao đủ, hoặc Đã hủy (có lý do). Quá ngày giao mà chưa nhận đủ thì thành **Giao chậm** và không còn tính là hàng đang về cho đến khi có ngày giao mới (AC-69).

### 9.8. Sổ kho và báo cáo — `/kho/so-kho/`, `/kho/bao-cao/`

Sổ kho lọc theo nguyên liệu, loại, ngày, có tổng và liên kết sang đơn. Báo cáo kho tháng: hao hụt theo lý do, hủy sau pha chế, kiểm kê, trường hợp thiếu. Báo cáo kho có biểu đồ cho Chủ quán ở `/bao-cao/kho/` (mục 14).

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

**Xem xét (chỉ Chủ quán, FR-17):** chọn Hợp lệ, Nhắc nhở hoặc Vi phạm, ghi biện pháp. Có tổn thất tiền thì phải gắn vào một vụ việc trước. Kết quả không sửa; muốn đổi phải lập bản đính chính có lý do. Ngoại lệ chưa xem xét quá 3 ngày được nhắc lại. Trang chi tiết hiện chuỗi thao tác của đơn và lịch sử của nhân viên.

**Vụ việc tổn thất** (`/kiem-soat/vu-viec/`, mã `VV-001`…): bằng chứng là ngoại lệ hoặc khoản chênh lệch tiền; mỗi bằng chứng thuộc tối đa một vụ việc; cùng một giao dịch chỉ tính một lần. Ghi xác minh, đính chính có lý do, thu hồi; hệ thống tính phần còn lại.

**Giá trị kiểm soát tạm tính của tháng** so với mục tiêu 200.000 đ (BRU-16) hiện ở bảng điều khiển và báo cáo kiểm soát doanh thu, cộng các nhóm không trùng nhau.

## 11. Trung tâm cảnh báo — `/canh-bao/`

Mỗi lần tác vụ định kỳ chạy, hệ thống quét các điều kiện ở Bảng 5.4, rồi:

- đối tượng mới thỏa điều kiện → tạo cảnh báo, giao người xử lý chính, đặt thời hạn (theo tham số);
- điều kiện không còn → tự đóng kèm ghi chú;
- quá hạn → chuyển cấp lên Chủ quán hoặc nhắc lại;
- đóng tay phải ghi kết quả; đối tượng đã đóng tay không tự mở lại (GD-22).

Loại cảnh báo: Nguyên liệu Đã hết (Khẩn), phiếu dự phòng chưa nhập bù hoặc chờ xác nhận, dữ liệu ca trễ hạn, chênh lệch tiền vượt ngưỡng, ngoại lệ chờ xem xét, giao chậm, chênh lệch kiểm kê chờ xác nhận, khoản phải trả đến hạn, cần kiểm kê lại (giao Pha chế), kiểm kê trọng yếu trễ, **Cần đặt hàng** (từ kế hoạch mua), **Lô quá hạn còn trong kho** (mỗi lô một cảnh báo, giao Pha chế, Quan trọng, hạn cuối ngày, quá hạn chuyển Chủ quán, tự đóng khi lô được hủy hoặc dùng hết). Cảnh báo Khẩn và Quan trọng gửi thông báo đẩy tới điện thoại (NFR-17). Trang có thống kê tuần (NFR-23).

## 12. Chấm công, tải công việc, lịch làm

**Chấm công** (`/cham-cong/`): nhân viên vào ca chọn vai trò mình đảm nhận, ra ca khi về. Lượt thiếu giờ ra không được tính giờ công; tác vụ định kỳ nhắc Chủ quán một lần, Chủ quán bổ sung giờ ra kèm lý do (AC-77, AC-78). Một người được tính có mặt trong khung giờ khi làm ít nhất nửa khung (GD-20).

**Tải và thời gian chờ** (`/tai/`, Chủ quán): theo từng khung một giờ:

- tải = số ly × hệ số tải của nhóm món (theo giờ gửi pha chế);
- thời gian chờ = trung vị từ gửi pha chế đến mang ra;
- món tồn quầy cuối khung;
- **Quá tải** khi thời gian chờ trung vị vượt 10 phút hoặc tồn quầy vượt 15 ly;
- số người có mặt theo vai trò.

Trang có ba biểu đồ: số ly theo khung giờ (cột đỏ là khung quá tải), thời gian chờ trung vị so với đường chuẩn, và người có mặt theo vai trò; nút chuyển ngày trước, ngày sau.

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
