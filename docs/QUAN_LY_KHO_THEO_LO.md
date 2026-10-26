# Quản lý kho theo lô

Tài liệu này giải thích phần kho theo lô của Hai's LAM Coffee: lô hàng là gì, hệ thống gợi ý lấy lô nào trước theo quy tắc nào, vì sao mỗi loại nguyên liệu dùng quy tắc đó, và các màn hình, cảnh báo, báo cáo đi kèm. Mã nguồn chính nằm ở `apps/inventory/lots.py`, `apps/inventory/views_lots.py` và `apps/reports/inventory.py`.

## 1. Lô hàng là gì

Mỗi lần hàng vào kho tạo một lô (`StockLot`). Một lô có:

| Thông tin | Ý nghĩa |
|---|---|
| Mã lô | Duy nhất trong cửa hàng, in trên phiếu lấy hàng và nhãn dán thùng. |
| Số lô trên bao bì | Số lô của nhà sản xuất, không bắt buộc. Dùng khi nhà cung cấp thu hồi một lô. |
| Nguồn | Phiếu nhập, tồn đầu kỳ, dư khi kiểm kê, hoặc tồn có từ trước khi bật theo dõi lô. |
| Ngày nhập | Lúc lô vào kho. |
| Hạn sử dụng | Ngày cuối còn dùng được; từ hôm sau là quá hạn. |
| Hạn ước tính | Có đánh dấu khi phiếu nhập không ghi hạn và hệ thống tự tính bằng ngày nhập cộng thời hạn sử dụng của nguyên liệu. |
| Số lượng nhập, còn lại | Còn lại giảm dần khi pha chế, hao hụt, kiểm kê thiếu. |
| Đơn giá | Giá nhập thực tế của lô, dùng để tính giá trị tồn và giá vốn. |

Mã lô theo nguồn:

| Nguồn | Mã | Ví dụ |
|---|---|---|
| Phiếu nhập | Mã phiếu / số dòng | `PN2610-03/2` là dòng thứ hai của phiếu thứ ba ngày 26/10 |
| Tồn đầu kỳ | `DK` + ngày + mã nguyên liệu | `DK261001-5` |
| Dư khi kiểm kê | `KK` + số biến động kho | `KK812` |
| Tồn trước khi theo dõi lô | `TON-` + mã nguyên liệu | `TON-5` |

Mọi thay đổi lượng của một lô đều ghi một dòng xuất nhập theo lô (`LotDraw`) gắn với dòng sổ kho gây ra nó. Dòng này chỉ được thêm, không sửa, không xóa, giống sổ kho.

## 2. Quy tắc lấy lô cho từng loại nguyên liệu

Hệ thống có ba quy tắc:

- **FEFO** (First Expired, First Out, hết hạn trước xuất trước): lô có hạn sớm nhất lấy trước.
- **FIFO** (First In, First Out, nhập trước xuất trước): lô nhập sớm nhất lấy trước, không xét hạn.
- **LIFO** (Last In, First Out, nhập sau xuất trước): lô nhập gần nhất lấy trước.

Áp dụng cho quán như sau:

| Loại nguyên liệu | Ví dụ ở quán | Quy tắc | Lý do |
|---|---|---|---|
| Hàng tươi, hạn ngắn | Sữa tươi (7 ngày), kem muối (5 ngày), trái cây | FEFO | Hai lô sữa giao cách nhau hai ngày có thể có hạn không theo thứ tự nhập (khác nhà máy, khác đợt). Lấy theo hạn là cách duy nhất không để lô nào hỏng trong tủ. |
| Hàng khô có in hạn | Cà phê rang, trà, matcha, sữa đặc, đào ngâm, trân châu, siro | FEFO | Nhà cung cấp có thể giao hàng tồn kho cũ của họ, hạn ngắn hơn lô đang có. FIFO sẽ để lô hạn ngắn đó nằm lại. |
| Hàng không có hạn dùng | Ly nhựa, ống hút, nắp, túi | FIFO (mặc định) hoặc LIFO | Không hỏng theo thời gian nên thứ tự chỉ ảnh hưởng tới thao tác. LIFO hợp khi thùng mới chồng lên trên và lấy thùng dưới mất công. |

Cách hệ thống chọn:

1. Ô **Quy tắc xuất lô** của nguyên liệu để trống là mặc định và nên để trống cho hầu hết nguyên liệu. Khi đó hệ thống luôn sắp theo FEFO; lô không ghi hạn xếp sau, giữa chúng là nhập trước xuất trước. Vì vậy nguyên liệu có hạn dùng chạy FEFO, còn nguyên liệu không có hạn dùng (ly, ống hút) thực chất chạy FIFO.
2. Chủ quán có thể chọn cố định FEFO, FIFO hoặc LIFO ở **Dữ liệu nền › Nguyên vật liệu**. Danh sách nguyên vật liệu có cột **Quy tắc xuất lô** để xem nhanh.
3. **Không cho LIFO với hàng có hạn dùng.** Nếu nguyên liệu có thời hạn sử dụng mà chọn LIFO, form báo lỗi "Hàng có hạn dùng không xuất theo LIFO: lô cũ sẽ nằm lại tới khi hỏng". Với hàng có hạn, LIFO gần như chắc chắn để lô cũ quá hạn.
4. **Lô quá hạn luôn đứng cuối**, với mọi quy tắc. Hệ thống không bao giờ gợi ý lấy lô quá hạn khi còn lô dùng được.

Dữ liệu mẫu của quán dùng đúng cách này: mọi nguyên liệu để trống (tự chọn), riêng ly nhựa đặt LIFO để minh họa.

## 3. Hệ thống trừ lô thế nào

Mọi thay đổi tồn đi qua một hàm duy nhất `stock.move()`. Hàm này ghi sổ kho rồi gọi phân bổ vào lô trong cùng giao dịch, nên sổ kho và lô không bao giờ lệch nhau.

| Nghiệp vụ | Cách trừ hoặc cộng lô |
|---|---|
| Nhập hàng, tồn đầu kỳ | Tạo lô mới. Nếu sổ kho đang âm (quầy đã pha khi sổ ghi thiếu), lô mới bù phần âm trước. |
| Pha chế (đóng món) | Trừ lần lượt theo thứ tự lấy lô của nguyên liệu. |
| Hao hụt | Trừ theo thứ tự lấy lô, hoặc trừ đúng lô người ghi chọn. Hao hụt vì hết hạn thì trừ lô quá hạn trước. |
| Kiểm kê thiếu | Trừ lô quá hạn trước (phần dễ đã bị bỏ đi mà chưa ghi), rồi theo thứ tự lấy lô. |
| Kiểm kê dư | Trả lại các lô còn dùng được đã bị trừ; phần còn thừa thành lô mới nguồn "Dư khi kiểm kê". |
| Hủy lô | Ghi hao hụt đúng phần còn lại của lô đó. Lô quá hạn ghi lý do Hết hạn; lô chưa quá hạn phải ghi lý do. |

Bất biến được kiểm tra trong lệnh `python manage.py kiem_tra_toan_ven` (gọi `lots.problems()`):

- Lượng còn lại của mỗi lô bằng tổng các dòng xuất nhập của lô.
- Tổng còn lại các lô của một nguyên liệu bằng tồn vật lý, hoặc bằng 0 khi sổ kho đang âm.

## 4. Hạn dùng và trạng thái lô

**Hạn ghi trên phiếu nhập.** Mỗi dòng phiếu nhập có ô "Hạn sử dụng in trên bao bì" và "Số lô của nhà sản xuất". Hệ thống không cho nhập lô đã quá hạn.

**Hạn ước tính.** Dòng nhập để trống hạn mà nguyên liệu có thời hạn sử dụng thì hạn = ngày nhập + thời hạn − 1 ngày, đánh dấu "ước tính". Người dùng sửa lại hạn thật ở trang chi tiết lô khi xem bao bì; sửa xong bỏ dấu ước tính và ghi nhật ký.

**Trạng thái:**

| Trạng thái | Điều kiện |
|---|---|
| Quá hạn | Hôm nay đã sau ngày hạn. |
| Sắp hết hạn | Còn từ N ngày trở xuống, N = số lớn hơn giữa **2 ngày** và **20% thời hạn sử dụng**. Sữa tươi 7 ngày báo trước 2 ngày; siro 1 năm báo trước khoảng 73 ngày. Hai con số này chỉnh ở tham số hệ thống, nhóm "Kho theo lô". |
| Còn hạn | Còn lâu hơn N ngày. |
| Chưa rõ hạn | Nguyên liệu có thời hạn sử dụng nhưng lô không có ngày hạn (thường là tồn trước khi bật theo dõi lô). |
| Không có hạn | Nguyên liệu không có thời hạn sử dụng (ly, ống hút). Đây không phải thiếu thông tin. |

## 5. Dự kiến dùng kịp và "dự kiến bỏ"

Biết hạn của từng lô chưa đủ: một lô còn 5 ngày nhưng quán chỉ dùng hết sau 8 ngày vẫn sẽ hỏng một phần. Hệ thống mô phỏng từng ngày:

1. Tốc độ dùng = lượng pha chế bình quân mỗi ngày trong 4 tuần gần nhất. Nguyên liệu mới theo dõi chưa đủ 4 tuần thì chia cho số ngày đã có sổ kho, để không tính thiếu tốc độ.
2. Mỗi ngày lấy đúng lượng đó theo thứ tự lấy lô.
3. Lô nào tới ngày sau hạn mà còn hàng thì phần còn lại tính là **dự kiến bỏ**.

Kết quả hiện ở mọi nơi có lô: ngày dự kiến dùng hết của từng lô, lượng và tiền dự kiến bỏ, số ngày tồn còn đủ dùng. Đây là tín hiệu để đẩy món dùng nguyên liệu đó, giảm lượng đặt lần sau hoặc chuyển sang làm món khác trước khi hàng hỏng.

## 6. Màn hình

| Màn hình | Địa chỉ | Dùng để |
|---|---|---|
| Tồn kho | `/kho/` | Mỗi nguyên liệu một dòng: quy tắc xuất, có thể dùng, đủ dùng bao nhiêu ngày, lô nên lấy trước, số lô, giá trị, tình trạng. Bốn ô đầu trang (lô quá hạn, sắp hết hạn, dự kiến bỏ, dưới mức an toàn) bấm vào để lọc. |
| Phiếu lấy hàng | `/kho/lay-hang/` | Màn hình cho quầy pha chế. Mỗi nguyên liệu một thẻ: lấy lô nào trước, hạn, còn bao nhiêu ngày, lô kế tiếp. Lô quá hạn hiện riêng, có nút hủy ngay. Thẻ có lô quá hạn và lô sắp hết hạn xếp lên đầu. |
| Lô hàng | `/kho/lo/` | Mọi lô đang còn, lọc theo Quá hạn, Sắp hết hạn, Dự kiến bỏ, Chưa rõ hạn và theo nguyên liệu. |
| Chi tiết lô của một nguyên liệu | `/kho/lo/nguyen-lieu/<id>/` | Thứ tự lấy lô (lô số 1 lấy trước), biểu đồ lịch dùng dự kiến so với hạn, sửa hạn và số lô, hủy lô, lịch sử xuất nhập theo lô, các lô đã dùng hết gần đây. |
| Phiếu nhập | `/kho/phieu-nhap/` | Mỗi dòng nhập ghi hạn và số lô; lưu xong báo mã lô đã tạo. |
| Hao hụt | `/kho/hao-hut/` | Chọn lô bị hỏng, hoặc để hệ thống tự chọn theo quy tắc. |

Giá trị tiền chỉ hiện cho người có quyền xác nhận đặt hàng (Chủ quán).

## 7. Cảnh báo lô quá hạn

Mỗi lô còn hàng mà đã quá hạn sinh một cảnh báo "Lô … (…) đã quá hạn":

- Giao cho Pha chế, mức Quan trọng, hạn xử lý cuối ngày.
- Đường dẫn tới Phiếu lấy hàng, nơi có nút hủy lô.
- Quá hạn xử lý thì chuyển lên Chủ quán.
- Tự đóng khi lô được hủy hoặc dùng hết, kèm ghi chú cách xử lý.

## 8. Giá trị tồn và giá vốn

- **Giá trị tồn** tính theo **giá thực tế đích danh**: mỗi lô nhân đơn giá nhập thực của chính lô đó. Lô không có đơn giá (tồn đầu kỳ, dư kiểm kê) dùng giá nhập gần nhất của nguyên liệu.
- **LIFO ở đây chỉ là thứ tự lấy hàng vật lý**, không phải phương pháp tính giá. Thông tư 200/2014/TT-BTC đã bỏ phương pháp tính giá xuất kho nhập sau xuất trước; vì vậy quy tắc lấy lô không làm thay đổi cách tính giá trị tồn.
- **Giá vốn ly bán** trên bảng điều khiển và báo cáo doanh thu lấy từ lượng nguyên liệu thực trừ kho khi đóng món, nhân giá nhập gần nhất tại ngày bán.

## 9. Báo cáo kho

Trang `/bao-cao/kho/` dùng các biểu đồ khác nhau cho từng câu hỏi:

| Biểu đồ | Câu hỏi trả lời |
|---|---|
| Giá trị tồn theo ngày (đường) | Tiền đang nằm trong kho tăng hay giảm? |
| Xuất kho theo tuần (cột chồng: tiêu hao, hao hụt) | Hao hụt chiếm bao nhiêu so với lượng thực dùng? |
| Lịch hết hạn (cột theo tuần) | Tuần nào có nhiều tiền hàng tới hạn? Cột đầu là hàng đã quá hạn còn trong kho. |
| Đủ dùng so với thời gian giao hàng (thanh ngang có vạch) | Nguyên liệu nào có thể hết trước khi hàng mới về nếu đặt hôm nay? |
| Hao hụt theo lý do, hao hụt nhiều nhất (thanh ngang) | Hỏng vì gì, ở nguyên liệu nào? |
| Nhập theo nhà cung cấp (thanh ngang) | Tiền nhập dồn vào nhà cung cấp nào? |
| Tuổi hàng trong kho (cột theo nhóm ngày) | Bao nhiêu tiền hàng nằm lâu, dễ hỏng? |

Phần **Nhận định** đầu trang tự viết vài câu từ số liệu: lô quá hạn cần hủy, nguyên liệu có thể hết trước khi hàng về, nguyên liệu hao hụt nhiều nhất kèm gợi ý theo lý do, giá trị dự kiến bỏ và số ngày tồn kho bình quân (DIO).

## 10. Chuyển dữ liệu cũ sang theo dõi lô

Migration `inventory 0011_backfill_lots` tạo lô cho dữ liệu đã có:

- Mỗi dòng phiếu nhập cũ thành một lô (mã phiếu / số dòng), lấy hạn và đơn giá trên dòng. Dòng không ghi hạn thì tính hạn ước tính như phiếu mới.
- Tồn vật lý hiện tại được chia cho các lô theo nhập trước xuất trước, tức là đi ngược từ phiếu mới nhất. Phần đã dùng của mỗi lô ghi một dòng trừ "Đã dùng trước khi theo dõi lô".
- Phần tồn không khớp phiếu nhập nào (tồn đầu kỳ, dư kiểm kê) thành lô `TON-<mã>`, trạng thái Chưa rõ hạn. Nên mở trang lô, xem bao bì và nhập hạn cho các lô này.

Trước khi chạy migrate trên máy thật đã sao lưu bốn cơ sở dữ liệu (đuôi `.truoc-lo.bak`).

## 11. Dữ liệu mẫu

- `python manage.py tao_du_lieu_mau`: mỗi nguyên liệu có thời hạn sử dụng và hạn tồn đầu kỳ khác nhau. Ví dụ sữa tươi hạn 7 ngày, tồn đầu còn 4 ngày; kem muối hạn 5 ngày, còn 3 ngày; có thêm ly nhựa (không hạn, LIFO) dùng cho mọi kích cỡ.
- `python manage.py tao_du_lieu_nghiem_thu`: hai tuần vận hành giả lập.
  - Bốn nhà cung cấp giao theo chu kỳ riêng (sữa tươi hai ngày một lần), hạn in trên bao bì thay đổi theo lô.
  - Có vài lần đổ vỡ, hỏng; sáng nào cũng hủy lô quá hạn.
  - Phiếu nhập xen kẽ trả ngay và trả sau.

Chạy xong, `/kho/lay-hang/` và `/kho/lo/` có đủ các trường hợp: lô quá hạn, lô sắp hết hạn, lô dự kiến bỏ, lô LIFO.
