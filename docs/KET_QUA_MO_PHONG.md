# Chạy thử bằng dữ liệu mô phỏng: dự báo mua nguyên liệu và chia ca (26/10/2026)

Hai yêu cầu chạy thử hai chức năng ra quyết định là kế hoạch mua nguyên liệu và gợi ý số người cho từng ca. Nếu chưa ổn thì tìm một mô hình đã được dùng rộng rãi, phù hợp với quán, rồi chạy tới khi hoạt động tốt. Tài liệu này ghi lại cách chạy thử, kết quả trước và sau khi sửa, lý do chọn từng mô hình và những việc còn cần Hai quyết.

## Tóm tắt

| Chức năng | Trước khi sửa | Sau khi sửa |
|---|---|---|
| Kế hoạch mua | 1,24 lần thiếu mỗi tháng trên 18 nguyên liệu mô phỏng; quy ra cả quán khoảng 3,4 lần mỗi tháng, trong khi BO-02 chỉ cho 1 lần | 0,36 lần mỗi tháng (giảm 71%); quy ra cả quán khoảng 0,9 lần. Đổi lại xoài và bơ hết hạn nhiều hơn 3 đến 5 điểm phần trăm |
| Gợi ý số người | Gợi ý 116 giờ công mỗi ngày, gấp 2,2 lần lịch hiện nay (53 giờ), vì năng suất tự học chỉ bằng 1/3 sức làm thật | 57 giờ mỗi ngày khi Chủ quán đặt sức làm, 61 giờ khi để hệ thống tự ước lượng. 96% số giờ đạt chuẩn chờ 10 phút; giờ đông đạt chuẩn tăng từ 74% lên 90–92% |
| Xếp người theo đăng ký | Cách tham lam (ô khan hiếm trước) | Giữ nguyên: so với lời giải tối ưu trên 40 tuần ngẫu nhiên, chỉ 2 tuần thiếu 1 chỗ |

Hai mô hình được đưa vào hệ thống:

- **Mua nguyên liệu:** tính phần tồn sẽ hết hạn trước khi dùng kịp (EWA của Broekmeulen và van Donselaar 2009). Mức phục vụ được chia theo nhóm: hàng tươi 95%, hàng để lâu 98%.
- **Chia ca:** số người từng giờ theo mô hình hàng đợi Erlang C, rồi chia vào ca bằng bài toán phủ. Đây là quy trình lập lịch nhân sự dịch vụ chuẩn (Thompson 1998; Ernst và cộng sự 2004).

**Lưu ý quan trọng:** đây là dữ liệu mô phỏng. Kết quả cho biết logic quyết định đúng hay sai trong một quán giống LAM Coffee, không thay cho việc kiểm chứng trên số thật sau vài tuần vận hành.

## 1. Cách chạy thử

Hai quán giả lập nằm ngay trong mã, không đọc hay ghi cơ sở dữ liệu. Hệ thống không biết các thông số "thật" của quán giả lập, chỉ thấy những gì nó sẽ thấy ở quán thật: đơn bán, giờ gửi pha chế, giờ pha xong, chấm công, phiếu nhập.

| Quán giả lập | Tệp | Lệnh chạy lại |
|---|---|---|
| Mua nguyên liệu: một năm, 18 nguyên liệu tiêu biểu của thực đơn LAM | `apps/forecast/simulation.py` | `python manage.py mo_phong_ke_hoach_mua --hat-giong 1,2,3,4,5` (thêm `--cach truoc-2610` để chạy cách cũ) |
| Chia ca: từng khách, từng ly, từng người trong ngày | `apps/schedule/simulation.py` | `python manage.py mo_phong_xep_ca --hat-giong 1,2,3` (thêm `--tai 1.3` để thử ngày đông hơn 30%) |

Mỗi cách được chạy với nhiều hạt giống ngẫu nhiên (5 cho mua hàng, 3 cho chia ca). Bảng dưới đây ghi số trung bình.

## 2. Kế hoạch mua nguyên liệu

### 2.1. Quán giả lập

Quán bán trung bình khoảng 185 ly mỗi ngày theo tỷ trọng nhóm món của thực đơn thật, và dùng định mức thật trong `apps/catalog/thuc_don_lam.py`. Quán giả lập có những điều hệ thống không biết trước:

- Ngày trong tuần, cuối tuần đông hơn khoảng 25%.
- Mùa hè: nước ép, sinh tố tăng 30%, cà phê gần như không đổi.
- Tết đóng cửa Mùng 1 đến Mùng 3, trước và sau Tết đông, các ngày lễ.
- Mức bán trôi dần, ngày đổi thời tiết lệch chung cả quán ±10%, nhu cầu phân tán hơn Poisson.
- Từ ngày thứ 200, mức bán giảm lâu dài 12%, ví dụ quán đối diện khai trương.
- Ước tính tuần ban đầu của Chủ quán lệch tới ±20%.
- Nhà cung cấp giao trễ một ngày với xác suất 8%; mua gấp chỉ được một nửa số lần.

Mỗi tối hệ thống chạy đúng hàm dự báo và hàm chính sách đang dùng (`methods.forecast_ingredient`, `policy.compute`), và Chủ quán giả lập làm theo đề xuất. Ly thiếu nguyên liệu thì không bán được; mỗi nguyên liệu tính tối đa một trường hợp thiếu mỗi ngày (BRU-26). Hàng dùng lô cũ trước, lô quá hạn bị bỏ cuối ngày.

### 2.2. Kết quả cách cũ

| Cách | Lần thiếu mỗi tháng (18 nguyên liệu) | Tháng tệ nhất | Ly mất | Xoài hết hạn | Bơ hết hạn |
|---|---|---|---|---|---|
| Chủ quán đặt theo thói quen, không dùng hệ thống | 16–22 | | | | |
| Hệ thống trước 26/10 | 1,24 | 5 lần | 0,09% | 21,6% | 14,1% |

Hệ thống đã tốt hơn nhiều so với đặt theo thói quen, nhưng chưa đạt BO-02. Có hai nguyên nhân:

1. **Coi toàn bộ tồn là dùng được.** Một hộp sữa còn một ngày hạn vẫn được tính như hộp mới. Hệ thống tưởng còn đủ nên không đặt, hôm sau lô cũ bị bỏ và quán hết hàng. Trong 15 lần thiếu mỗi năm, 12 lần rơi vào 6 nguyên liệu tươi (sữa tươi, chanh, tắc, cam, xoài, bơ); riêng bơ 5,6 lần và xoài 3 lần.
2. **Hàng để lâu chỉ giữ mức phục vụ 90% mỗi tuần.** Mỗi nguyên liệu khô thiếu khoảng 0,26 lần mỗi năm. Con số này nhỏ, nhưng quán có khoảng 43 nguyên liệu loại này nên cộng lại hơn 11 lần mỗi năm.

### 2.3. Mô hình chọn

**Tính phần sẽ hết hạn (EWA, Estimated Withdrawal and Aging).** Đây là cách Broekmeulen và van Donselaar (2009) đề xuất cho hàng tươi ở siêu thị Hà Lan, khi nhu cầu đổi theo ngày và có thời gian giao. Hệ thống dựng lại các lô đang có trong kho theo nguyên tắc nhập trước xuất trước, đi ngược từ phiếu nhập mới nhất cho tới khi đủ số tồn vật lý. Hạn của mỗi lô lấy theo hạn ghi trên phiếu nhập; phiếu không ghi thì lấy ngày nhập cộng hạn dùng trừ một ngày. Sau đó hệ thống chạy dòng tồn từng ngày: nhu cầu lấy từ lô gần hết hạn trước, và lượng lô đến hạn mà chưa dùng hết thì bị loại. Lượng dự kiến hết hạn trong cửa sổ được trừ khỏi vị thế tồn. Tồn không khớp phiếu nhập nào, như tồn đầu kỳ hay kiểm kê tăng, được coi là không hết hạn, tức giữ cách tính cũ cho phần đó.

**Chia mức phục vụ theo nhóm.** BO-02 là một chỉ tiêu cho cả quán: tối đa một trường hợp thiếu mỗi tháng. Silver, Pyke và Thomas (2017, chương về chỉ tiêu tổng số lần thiếu) chỉ ra cách chia chỉ tiêu này cho từng mặt hàng sao cho tổng chi phí giữ tồn nhỏ nhất. Mặt hàng mà giữ thêm tồn tốn ít thì nên được giao mức phục vụ cao; mặt hàng mà giữ thêm tồn tốn nhiều thì mức thấp hơn.

- Với hàng để lâu (nhóm B), giữ thêm vài gói gần như không mất gì vì không hỏng, nên đặt 98%.
- Với hàng tươi (nhóm A), mỗi đơn vị giữ thêm có thể bị bỏ, nên đặt 95%.

Trước khi chọn cách này, đã thử chia đều chỉ tiêu cho từng nguyên liệu (T0, T1 trong bảng dưới). Cách đó đòi 99,5% cho mọi nguyên liệu, gần như hết thiếu hàng, nhưng xoài hết hạn tới 38% nên không dùng.

### 2.4. Kết quả các cách đã thử

| Cách | Lần thiếu mỗi tháng | Tháng tệ nhất | Ly mất | Thiếu mỗi năm: hàng tươi / hàng để lâu | Xoài hết hạn | Bơ hết hạn |
|---|---|---|---|---|---|---|
| Trước 26/10: CSL 95% trọng yếu, 90% còn lại | 1,24 | 5 | 0,094% | 11,8 / 3,2 | 21,6% | 14,1% |
| E1: thêm EWA, giữ CSL cũ | 0,69 | 3 | 0,034% | 5,2 / 3,2 | 24,5% | 14,9% |
| **E2: EWA, hàng tươi 95%, hàng để lâu 98% (đã chọn)** | **0,36** | **3** | **0,040%** | **4,0 / 0,4** | **26,5%** | **17,2%** |
| E3: EWA, hàng tươi 97%, hàng để lâu 98% | 0,31 | 4 | 0,038% | 3,2 / 0,6 | 28,7% | 18,8% |
| T0: chia đều BO-02 cho từng nguyên liệu (99,5%), không EWA | 0,15 | 1 | 0,010% | 1,6 / 0,2 | 32,1% | 21,8% |
| T1: như T0, có EWA | 0,05 | 1 | 0,004% | 0,4 / 0,2 | 38,5% | 26,2% |
| E2, xoài và bơ mua lẻ từng quả thay vì túi 4 quả | 0,45 | 4 | 0,018% | 4,6 / 0,8 | 15,4% | 15,4% |

Cách đọc:

- **EWA giảm một nửa số lần thiếu của hàng tươi** (11,8 xuống 5,2 mỗi năm) ở cùng mức phục vụ. Lý do là hệ thống không còn tính hàng sắp bỏ là hàng dùng được.
- **Nâng hàng để lâu lên 98% gần như xóa hết thiếu ở nhóm này** (3,2 xuống 0,4 mỗi năm). Đổi lại, tồn trung bình của nhóm này tăng khoảng nửa ngày dùng (8,5 lên 9 ngày), và không có thêm hàng hỏng.
- Nâng hàng tươi lên 97% (E3) chỉ bớt thêm 0,05 lần mỗi tháng mà xoài, bơ bị bỏ thêm 2 điểm phần trăm, nên giữ 95%.
- Đổi lại, xoài và bơ bị bỏ nhiều hơn: xoài từ 21,6% lên 26,5%, bơ từ 14,1% lên 17,2%. Xoài chỉ dùng khoảng 1,3 quả mỗi ngày nhưng mua theo túi 4 quả và để được 5 ngày. Bơ dùng khoảng 7 quả mỗi ngày nhưng chỉ để được 4 ngày và dao động mạnh theo ngày. Giữ đủ để ít khi hết thì thế nào cũng bỏ một phần.

### 2.5. Quy ra cả quán

Thực đơn thật có 58 nguyên liệu kho. Hạn dùng thật của từng nguyên liệu chưa nhập đủ, nên tạm ước khoảng 15 nguyên liệu tươi và 43 nguyên liệu để lâu. Nhân tỷ lệ thiếu mỗi nguyên liệu trong mô phỏng ra cả quán:

| Cách | Hàng tươi (15) | Hàng để lâu (43) | Cả quán mỗi tháng |
|---|---|---|---|
| Trước 26/10 | 15 × 1,97 = 29,5 lần/năm | 43 × 0,26 = 11,2 lần/năm | **3,4** |
| Đã chọn (E2) | 15 × 0,67 = 10,0 lần/năm | 43 × 0,03 = 1,2 lần/năm | **0,9** |

Kết quả đạt BO-02 nhưng không dư nhiều. Nếu quán có nhiều nguyên liệu tươi hơn ước tính thì sẽ sát hoặc vượt 1 lần mỗi tháng. Báo cáo BO-02 hằng tháng trên bảng điều khiển sẽ cho biết số thật.

### 2.6. Xoài và bơ: cần Hai chọn

Không mức phục vụ nào vừa ít thiếu vừa ít bỏ cho hai món này. Các cách thường dùng:

1. **Mua lẻ từng quả ở chợ** thay vì theo túi: xoài hết hạn giảm từ 26,5% xuống 15,4%, ít ly mất hơn, nhưng mua thường hơn (khoảng 260 lần một năm thay vì 160).
2. **Đặt mức phục vụ riêng thấp hơn** cho xoài và bơ ở trang nguyên liệu, ví dụ 85%, nếu khách hết xoài thường chịu đổi món.
3. **Dùng xoài đông lạnh hoặc cốt xoài** (để lâu) cho sinh tố, giữ xoài tươi cho món cần quả tươi.

Hệ thống vẫn để Chủ quán đặt mức phục vụ riêng cho từng nguyên liệu; số Chủ quán đặt luôn được ưu tiên.

## 3. Gợi ý số người cần cho từng ca

### 3.1. Quán giả lập

Quán giả lập mô phỏng từng khách, từng ly và từng người trong ngày:

- **Khách:** đến theo giờ, dày nhất 7–9 giờ sáng và 19–21 giờ tối, cuối tuần tối đông hơn. Ngày thường 190 ly, cuối tuần 260 ly. Mỗi đơn 1–4 ly (75% đơn một ly).
- **Pha chế:** pha theo thứ tự gửi, mỗi người một ly một lúc. Thời gian pha theo nhóm món, ví dụ cà phê 1,3 phút, sinh tố 3,2 phút, lệch ±50%.
- **Phục vụ:** nhận order (1,5 phút), mang món khi cả đơn xong (0,7 phút), dọn bàn khi khách về (1 phút). Mang món được làm trước nhận order, nhận order trước dọn bàn.
- **Thu ngân:** mỗi lần thanh toán 1,5 phút.

Hệ thống đo như ở quán thật (`apps/orders/workload.py`). Mỗi khung một giờ có tải theo hệ số nhóm món Chủ quán khai, thời gian chờ trung vị từ gửi pha chế tới mang ra, và cờ quá tải. Quán chạy 8 tuần theo lịch cố định hiện nay để có dữ liệu học, rồi chạy thử từng cách xếp người trong 4 tuần với cùng một chuỗi khách.

### 3.2. Vấn đề của cách cũ

Cách cũ làm tròn lên tải chia năng suất, lấy giờ cao nhất của từng ca. Năng suất là trung vị của tải mỗi người trong các giờ không quá tải.

1. **Năng suất học được chỉ bằng 1/3 sức làm thật.** Trung vị tải mỗi người ở giờ không quá tải tính cả lúc rảnh. Một pha chế pha được khoảng 46 tải mỗi giờ khi bận liên tục, nhưng trung vị chỉ khoảng 16, nên hệ thống tưởng cần gấp ba số người.
2. **Làm tròn lên tải chia năng suất cho phép làm 100% công suất.** Nếu năng suất đúng bằng sức làm thật, ở giờ cao điểm người làm chạy hết công suất và hàng chờ dài ra không giới hạn. Đây là kết quả cơ bản của lý thuyết hàng đợi: cần chừa khoảng trống cho lúc khách đến dồn.
3. **Ca chồng giờ bị tính hai lần.** Mỗi ca lấy giờ cao nhất của mình, nên nếu ca chiều 14–22 giờ và ca cao điểm tối 18–22 giờ cùng có giờ 19, cả hai ca đều được gợi ý đủ người cho giờ 19.

### 3.3. Mô hình chọn

Đây là quy trình lập lịch nhân sự dịch vụ được dùng rộng rãi ở ngân hàng, tổng đài, cửa hàng ăn nhanh (Thompson 1998; Ernst và cộng sự 2004). Code nằm ở `apps/schedule/staffing.py`; phần đọc dữ liệu ở `apps/schedule/services.py`.

1. **Tải từng giờ** = số ly dự báo của ngày × tỷ lệ bán theo giờ × hệ số tải bình quân mỗi ly, giữ như cũ.
2. **Số người từng giờ theo Erlang C (M/M/c):** chọn số người ít nhất sao cho ít nhất 70% việc không phải chờ quá 4 phút mới có người làm. Độ biến động được hiệu chỉnh theo Allen–Cunneen, vì đơn đến theo nhóm nhiều ly (hệ số đo từ số ly mỗi đơn của 8 tuần gần nhất) và thời gian pha không đều. Mỗi giờ được tính như một hàng đợi riêng (xấp xỉ SIPP của Green, Kolesar và Soares 2001). Cách này hợp vì thời gian pha chỉ vài phút so với khung một giờ.
3. **Chia vào ca bằng bài toán phủ (Dantzig 1954):** chọn số người mỗi ca của ngày sao cho giờ nào cũng đủ người, tổng giờ công ít nhất. Hai ca chồng giờ cùng gánh giờ đông.
4. **Sức làm mỗi người** (tải một người làm được trong một giờ bận liên tục):
   - Nếu Chủ quán đặt ở trang Tham số thì dùng số đó.
   - Nếu để 0, pha chế được đo lúc mọi pha chế đều bận. Hệ thống dùng giờ gửi pha chế và giờ bấm "Xong" của từng dòng món, cùng số pha chế đang chấm công: tải pha xong trong các khoảng đó chia cho số giờ-người bận. Trên quán giả lập cách đo này ra 45,8 so với sức làm thật 45,7. Hệ thống cần ít nhất 3 giờ-người bận mới tin số đo, và bỏ các dòng món treo quá 60 phút (quên bấm Xong).
   - Phục vụ và thu ngân không có giờ bắt đầu, kết thúc từng việc nên không đo được kiểu này. Khi Chủ quán chưa đặt, hệ thống lấy giờ đông nhất mà vị trí đó vẫn làm kịp (phân vị 98 của tải mỗi người ở giờ không quá tải). Số này thường thấp hơn sức làm thật nên gợi ý dư người. Màn lịch tuần nhắc Chủ quán đo và đặt số.

Màn **Lịch làm tuần** có thêm khối **Căn cứ gợi ý**: số người cần từng giờ cho mỗi vị trí, sức làm đang dùng và nguồn của nó, số ly dự kiến, và các giờ quán mở mà chưa có ca nào phủ.

### 3.4. Kết quả

Ngày bình thường (190 ly ngày thường, 260 ly cuối tuần). "Giờ đạt chuẩn" là tỷ lệ khung giờ có thời gian chờ trung vị không quá 10 phút (BO-03 đòi ít nhất 90%). "Giờ đông" là các khung từ 20 ly trở lên, nơi phần lớn khách rơi vào.

| Cách | Giờ đạt chuẩn | Giờ đông đạt chuẩn | Giờ công mỗi ngày |
|---|---|---|---|
| Lịch cố định hiện nay: mỗi ca 1 pha chế, 1 phục vụ (cuối tuần 2), 1 thu ngân | 93,2% | 73,9% | 52,6 |
| Gợi ý trước 26/10, 2 ca | 99,1% | 100% | 115,8 |
| Gợi ý trước 26/10, 4 ca có ca cao điểm | 99,3% | 100% | 173,7 |
| Gợi ý mới, Chủ quán chưa đặt sức làm, 2 ca | 96,2% | 91,7% | 72,8 |
| Gợi ý mới, Chủ quán chưa đặt sức làm, 4 ca | 96,1% | 90,3% | 61,1 |
| Gợi ý mới, Chủ quán đã đặt sức làm, 2 ca | 96,3% | 91,2% | 66,3 |
| **Gợi ý mới, Chủ quán đã đặt sức làm, 4 ca** | **96,0%** | **92,1%** | **57,1** |

Ngày đông hơn 30% (khách tăng nhưng dự báo theo kịp):

| Cách | Giờ đạt chuẩn | Giờ đông đạt chuẩn | Giờ công mỗi ngày |
|---|---|---|---|
| Lịch cố định hiện nay | **87,2%** (không đạt BO-03) | 68,0% | 52,6 |
| Gợi ý trước 26/10, 2 ca | 99,1% | 100% | 150,9 |
| Gợi ý mới, chưa đặt sức làm, 4 ca | 96,5% | 94,5% | 73,3 |
| Gợi ý mới, đã đặt sức làm, 4 ca | 97,3% | 96,1% | 63,2 |

Cách đọc:

- **Lịch cố định hiện nay** đạt BO-03 tính theo số giờ, vì phần lớn giờ trong ngày vắng khách. Nhưng ở giờ đông, cứ 4 giờ thì có 1 giờ khách chờ quá 10 phút. Khi quán đông hơn 30% thì lịch này không còn đạt BO-03.
- **Gợi ý cũ** an toàn nhưng tốn gấp 2,2 đến 3,3 lần giờ công. Chủ quán sẽ không dùng được, và BO-03 đòi chi phí nhân công không cao hơn mức nền.
- **Gợi ý mới** thêm người đúng vào giờ đông. Giờ đông đạt chuẩn từ 74% lên khoảng 92%, đổi lại khoảng 4,5 giờ công mỗi ngày (8,5%) khi Chủ quán đã đặt sức làm.
- **Thêm ca ngắn cao điểm** (7–11 giờ, 18–22 giờ) tiết kiệm 9 đến 12 giờ công mỗi ngày so với chỉ có 2 ca 8 tiếng, vì không phải giữ người cả ca chỉ để gánh 2–3 giờ đông.

### 3.5. Chọn mức 4 phút, 70%

Với ca cao điểm và sức làm đã đặt:

| Mục tiêu | Giờ đạt chuẩn | Giờ đông đạt chuẩn | Giờ công mỗi ngày | Ngày đông +30%: giờ đông đạt chuẩn |
|---|---|---|---|---|
| 60% việc chờ ≤ 4 phút | 96,6% | 92,2% | 54,3 | 91,3% |
| **70% việc chờ ≤ 4 phút (mặc định)** | **96,0%** | **92,1%** | **57,1** | **96,1%** |
| 80% việc chờ ≤ 4 phút | 97,3% | 95,0% | 59,4 | 98,3% |

4 phút chờ trong hàng, cộng thời gian pha và mang ra, vẫn dưới chuẩn 10 phút của AC-79. 70% giữ được giờ đông khi quán bất ngờ đông lên mà không tốn thêm nhiều giờ công. Cả hai số ở trang Tham số (`schedule_wait_target_minutes`, `schedule_service_percent`) và được ghi là giả định chờ Chủ quán xác nhận.

### 3.6. Hai đo sức làm như thế nào

Đo trong một giờ đông, khi người đó làm liên tục:

- **Pha chế:** hệ thống tự đo được sau vài tuần dùng màn quầy pha chế đúng cách (bấm Xong ngay khi pha xong). Không cần nhập.
- **Phục vụ:** bấm giờ vài lần một người làm trọn một đơn (nhận order, mang món, dọn bàn). Ví dụ trung bình 3,2 phút mỗi đơn. Mỗi đơn khoảng 1,4 ly, mỗi ly khoảng 1,4 tải, nên một đơn khoảng 1,9 tải. Sức làm bằng 60 ÷ 3,2 × 1,9, khoảng 35 tải mỗi giờ.
- **Thu ngân:** tương tự với thời gian một lần thanh toán. Ví dụ 1,5 phút thì sức làm bằng 60 ÷ 1,5 × 1,9, khoảng 75 tải mỗi giờ.

Nhập ở Kiểm soát › Tham số: `schedule_productivity_phuc_vu`, `schedule_productivity_thu_ngan`. Khi có số này, giờ công gợi ý giảm từ khoảng 61 xuống 57 giờ mỗi ngày trên quán giả lập.

## 4. Xếp người theo đăng ký

Cách đang có xếp ô khan hiếm trước, trong ô ưu tiên người ít giờ trong tuần, rồi người đăng ký sớm. Cách này được so với lời giải tối ưu, tìm bằng cách duyệt hết, trên 40 tuần ngẫu nhiên: 11 nhân viên với kỹ năng khác nhau, 4 ca mỗi ngày, mỗi người đăng ký 30–80% số ca. Cách tham lam xếp đủ như lời giải tối ưu ở 38 tuần; 2 tuần còn lại thiếu 1 chỗ. Vì vậy cách này được giữ, và vẫn đúng các quy tắc AC-86, AC-87.

## 5. Những gì đã đổi trong hệ thống

| Phần | Thay đổi |
|---|---|
| `apps/forecast/policy.py` | Dòng tồn theo lô và trừ phần dự kiến hết hạn (EWA) khi biết các lô đang có. Không có lô thì tính như cũ |
| `apps/forecast/planning.py` | Dựng lô từ phiếu nhập theo nhập trước xuất trước; mức phục vụ tối thiểu 98% cho hàng để lâu; ghi nguồn mức phục vụ; phiên bản cách tính `ke-hoach-mua-3` |
| Màn chi tiết kế hoạch mua | Thêm dòng "Dự kiến hết hạn trước khi dùng kịp"; mức phục vụ ghi rõ nguồn |
| `apps/schedule/staffing.py` (mới) | Erlang C, Allen–Cunneen, bài toán phủ ca, đo sức làm lúc bận liên tục |
| `apps/schedule/services.py` | Gợi ý số người theo ngày: số người từng giờ rồi chia vào các ca của ngày |
| Màn lịch tuần | Giải thích mới; khối "Căn cứ gợi ý" theo ngày |
| Tham số | Mới: `plan_csl_long_life_percent` 98, `schedule_wait_target_minutes` 4, `schedule_service_percent` 70. Đổi: `plan_csl_normal_percent` 90 → 95; ba tham số năng suất nay là sức làm khi bận liên tục |
| Quán giả lập và lệnh chạy lại | `apps/forecast/simulation.py`, `apps/schedule/simulation.py`, `mo_phong_ke_hoach_mua`, `mo_phong_xep_ca` |
| Kiểm thử | `apps/schedule/tests/test_staffing.py`, thêm vào `apps/forecast/tests/test_policy.py` và `test_planning.py` |

Không có thay đổi cấu trúc cơ sở dữ liệu nên không cần chạy migrate.

## 6. Cần Hai xác nhận

1. Mức phục vụ 95% cho hàng tươi và 98% cho hàng để lâu thay cho 90% trước đây (mục 2).
2. Cách xử lý xoài và bơ (mục 2.6).
3. Mục tiêu chờ 4 phút cho 70% việc (mục 3.5).
4. Đo và nhập sức làm phục vụ, thu ngân (mục 3.6).
5. Nhập hạn dùng cho từng nguyên liệu và hạn trên phiếu nhập khi có. Phần trừ hàng sắp hết hạn chỉ chạy với nguyên liệu có hạn dùng.
6. Gợi ý số người cần có thể ra 0 cho một vị trí ở ca cao điểm, nếu ca chính đã đủ. Mức tối thiểu `schedule_min_per_role` nay áp cho từng giờ quán mở, không áp cho từng ca.

## 7. Giới hạn

- Quán giả lập được dựng theo thực đơn, định mức và mô tả của Hai, nhưng phút pha, phút phục vụ, nhịp khách theo giờ và hạn dùng là số giả định. Logic đã đúng trên quán giả lập; mức con số cần đo lại trên dữ liệu thật sau 4–8 tuần vận hành.
- Mô hình hàng đợi coi mỗi giờ là một hàng riêng và mỗi việc một người làm. Pha chế nhiều ly cùng lúc (pha mẻ) làm sức làm thật cao hơn; số đo lúc bận liên tục đã gồm hiệu ứng này.
- Phục vụ làm cả ba việc với ưu tiên khác nhau. Mô hình gộp thành một hàng là xấp xỉ, nhưng trên quán giả lập vẫn cho kết quả tốt.

## Tài liệu tham khảo

- Broekmeulen, R. A. C. M., van Donselaar, K. H. (2009). A heuristic to manage perishable inventory with batch ordering, positive lead-times, and time-varying demand. *Computers & Operations Research* 36(11).
- Silver, E. A., Pyke, D. F., Thomas, D. J. (2017). *Inventory and Production Management in Supply Chains*, 4th ed. CRC Press.
- Thompson, G. M. (1998). Labor scheduling, part 1–4. *Cornell Hotel and Restaurant Administration Quarterly* 38–39.
- Ernst, A. T., Jiang, H., Krishnamoorthy, M., Sier, D. (2004). Staff scheduling and rostering: A review of applications, methods and models. *European Journal of Operational Research* 153(1).
- Green, L. V., Kolesar, P. J., Soares, J. (2001). Improving the SIPP approach for staffing service systems that have cyclic demands. *Operations Research* 49(4).
- Dantzig, G. B. (1954). A comment on Edie's "Traffic delays at toll booths". *Journal of the Operations Research Society of America* 2(3).
- Allen, A. O. (1990). *Probability, Statistics, and Queueing Theory*, 2nd ed. Academic Press (xấp xỉ Allen–Cunneen cho G/G/c).
