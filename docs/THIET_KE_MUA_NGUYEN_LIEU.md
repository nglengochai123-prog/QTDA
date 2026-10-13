# Thiết kế dự báo nhu cầu và đề xuất mua nguyên vật liệu LAM Coffee

Oct 13, 2026 · @Hai

## 1. Mục tiêu và phạm vi

Thiết kế này chuyển trọng tâm của phân hệ dự báo từ dự báo số ly từng món sang quyết định mua nguyên vật liệu. Đầu ra chính là nhu cầu nguyên liệu theo tuần và tháng, điểm đặt hàng lại hoặc mức tồn mục tiêu, thời điểm nên đặt và số lượng đề xuất mua cho từng nguyên liệu. Mục tiêu nghiệp vụ là giúp Chủ quán mua kịp thời, hạn chế hết hàng và tránh mua dư, đặc biệt với nguyên liệu dễ hỏng.

Phạm vi gồm bốn phần. Thứ nhất là xác định lại đối tượng dự báo và cách làm sạch dữ liệu tiêu hao. Thứ hai là áp dụng lý thuyết quản trị tồn kho xác suất để tính tồn an toàn, điểm đặt hàng lại và mức tồn mục tiêu. Thứ ba là xử lý hàng đang về, đơn trùng, quy cách đóng gói và hạn sử dụng. Thứ tư là đánh giá riêng chất lượng dự báo và chất lượng quyết định tồn kho.

Ngoài phạm vi là việc hệ thống tự gửi đơn tới nhà cung cấp, tối ưu hóa chi phí đặt hàng khi chưa có dữ liệu chi phí và quản lý tồn theo lô. Mọi đề xuất chỉ là căn cứ tham khảo; Chủ quán xem xét và xác nhận trước khi tạo đơn mua, đúng nguyên tắc BRU-37 và NFR-22 của tài liệu yêu cầu.

Trong tài liệu, phần **lý thuyết đã công bố** được trích dẫn kèm nguồn tại mục 14. Phần ghi **lựa chọn thiết kế của LAM Coffee** là quyết định riêng của dự án, không phải phát biểu của tác giả được trích dẫn. Các số liệu trong ví dụ là số minh họa, không phải dữ liệu kinh doanh thật của quán.

## 2. Rà soát hệ thống hiện tại

Nền tồn kho hiện tại đủ chính xác để làm đầu vào cho chính sách đặt hàng, nhưng phần dự báo và đề xuất còn thiếu tồn an toàn tính từ sai số, mức phục vụ, kiểm tra dòng tồn theo thời gian và một số trạng thái đơn mua. Rà soát dựa trên mã nguồn tại D:\\QTDA nhánh main, bản 7972893, đọc ngày 13/10/2026, cùng báo cáo yêu cầu, DOI\_CHIEU\_YEU\_CAU, KE\_HOACH và docs/DU\_BAO.md.

### 2.1. Tồn kho, định mức và biến động

| Thành phần | Cách hệ thống đang làm | Vị trí mã |
| --- | --- | --- |
| Tồn vật lý | Mỗi nguyên liệu một dòng tồn; thay đổi chỉ qua sổ biến động chỉ thêm, có kiểm tra tồn bằng tổng sổ | inventory/models.py:219, stock.py:40, :117 |
| Tồn đang giữ | Lượng giữ cho món đã gửi pha chế chưa pha xong; giữ cả đơn trong một giao dịch, nhả khi hủy trước pha, chuyển thành tiêu hao khi pha xong | stock.py:69, :90, :99; orders/services.py:140, :203 |
| Tồn có thể dùng | Tồn vật lý trừ tồn đang giữ; phần đề xuất đặt hàng đã dùng đại lượng này | models.py:240; forecast/services.py:491 |
| Loại biến động | Tồn đầu kỳ, pha chế, nhập hàng, hao hụt, kiểm kê; mỗi dòng có nguồn nghiệp vụ và người thực hiện | models.py:247 |
| Hủy sau pha chế | Không ghi biến động mới; tiêu hao pha chế vẫn giữ nguyên, chỉ tăng số ly hủy đã pha | orders/models.py:304; adjustments.py:243 |
| Định mức | Có phiên bản và thời điểm hiệu lực; lượng dùng của từng dòng món được chụp lại khi nhận đơn; mỗi nguyên liệu một đơn vị chuẩn g, ml, cái, quả hoặc gói, chưa có bảng quy đổi đơn vị mua | models.py:35, :82, :169; orders/models.py:104 |
| Thiếu nguyên liệu | Tối đa một trường hợp mỗi nguyên liệu mỗi ngày, từ báo Đã hết hoặc điều chỉnh do hết nguyên liệu | models.py:314 |
| Lô và hạn dùng | Chưa có; thời hạn sử dụng chỉ là một số ngày khai báo cho nguyên liệu | models.py:54 |

### 2.2. Đơn đặt hàng và phiếu nhập

Mỗi đơn đặt hàng chứa một nguyên liệu và một nhà cung cấp, với số lượng đặt, số lượng đã nhận và ngày giao dự kiến. Lượng còn phải giao được tính đúng bằng lượng đặt trừ lượng đã nhận. Trạng thái hiện có là Đã đặt, Giao một phần, Đã giao đủ và Giao chậm; chưa có trạng thái nháp và đã hủy. Lô quá ngày giao không được tính là hàng đang về cho đến khi Chủ quán cập nhật ngày mới. Phiếu nhập có thể liên kết với đơn đặt và cập nhật lượng đã nhận; nhận vượt số đặt hiện được chấp nhận mà không cảnh báo. Danh mục nguyên liệu có quy cách đóng gói, thời gian giao, chu kỳ đặt, hạn sử dụng, sức chứa và tồn an toàn nhập tay; chưa có lượng đặt tối thiểu và chưa có thời gian giao theo từng nhà cung cấp.

### 2.3. Dự báo và đề xuất hiện tại

Hệ thống đang dự báo số ly của từng món và kích cỡ theo ngày bằng mô hình Poisson Bayes động, mô phỏng 1.000 đường, rồi quy đổi sang nguyên liệu bằng định mức đang áp dụng. Nhu cầu trong thời gian giao được cộng đúng theo từng ngày dự báo, kể cả phần còn lại của hôm nay theo hồ sơ bán từng giờ. Cảnh báo Cần đặt hàng được tạo khi tồn dự kiến khi hàng về thấp hơn tồn an toàn nhập tay, và được đồng bộ không trùng khi tác vụ định kỳ chạy lại. Số lượng đề xuất bằng nhu cầu một chu kỳ đặt cộng tồn an toàn trừ tồn dự kiến, giới hạn theo hạn sử dụng và sức chứa, làm tròn lên theo quy cách.

### 2.4. Điểm cần thiết kế lại

| Vấn đề | Hệ quả | Xử lý trong thiết kế |
| --- | --- | --- |
| Dự báo độc lập mọi món và kích cỡ theo ngày | Nhiều chuỗi thưa, đường mô phỏng các món độc lập với nhau nên có thể đánh giá thấp biến động tổng của nguyên liệu | Mục 4: dự báo chuỗi tiêu hao của từng nguyên liệu |
| Tồn an toàn nhập tay, không có mức phục vụ | Không liên hệ được giữa rủi ro hết hàng và lượng tồn | Mục 6: tính từ sai số dự báo đo được và mức phục vụ chu kỳ |
| Lịch sử bán không tính ly hủy sau pha chế, tiêu hao thực tế lại tính | Hai chuỗi so sánh lệch nhau, dễ cộng trùng hoặc bỏ sót | Mục 5: tách bốn nguồn tiêu hao |
| Quy đổi tương lai dùng định mức hiện hành, bỏ qua tùy chọn không bán trong 56 ngày | Sai khi có định mức hẹn ngày hiệu lực | Mục 5: dùng phiên bản hiệu lực tại từng ngày |
| Gắn cờ ngày thiếu chỉ xét nguyên liệu của kích cỡ, không xét tùy chọn | Ngày bị giới hạn nguồn cung có thể lọt vào dữ liệu học | Mục 5: gắn cờ theo nguyên liệu |
| Chỉ so tổng tồn dự kiến tại một thời điểm | Lô về sau ngày dự kiến hết có thể che rủi ro | Mục 8: kiểm tra dòng tồn theo ngày |
| Đề xuất trống khi chưa khai chu kỳ đặt; 58 nguyên liệu nhập từ thực đơn thật đang có quy cách 1 và chưa có chu kỳ | Chưa dùng được cho dữ liệu thật | Mục 7 và 13: tham số mặc định theo nhóm, ghi rõ là giả định |
| Cảnh báo Cần đặt hàng đã đóng tay có thể không bao giờ mở lại cho nguyên liệu đó | Bỏ sót nguy cơ hết hàng về sau | Mục 8: khóa chống trùng theo chu kỳ |
| Gửi lại cùng thao tác xác nhận đề xuất có thể gây lỗi khi lưu đề xuất lần hai | Phá tính chống ghi trùng | Mục 8 |
| Cột nhu cầu 90% trong thời gian giao tính dư một ngày so với cột kỳ vọng | Hai số không cùng cửa sổ | Mục 6: một cửa sổ bảo vệ duy nhất |

Ba điểm cuối là lỗi có khả năng xảy ra, phát hiện khi đọc mã, chưa chạy thử để xác nhận.

## 3. Lý thuyết áp dụng và nguồn học thuật

Mục này chỉ trình bày các kết quả đã công bố, kèm điều kiện áp dụng. Cách LAM Coffee vận dụng các kết quả đó được ghi tách riêng ở cuối mục và ở các mục 6, 7.

### 3.1. Vị thế tồn kho và các dạng chính sách

Trong bài giảng môn ESD.260J Logistics Systems của Chris Caplice và Yossi Sheffi tại MIT, quyết định đặt hàng dưới nhu cầu ngẫu nhiên được đưa ra trên **vị thế tồn kho**, tức tồn hiện có cộng hàng đã đặt chưa về trừ nhu cầu đã cam kết chưa đáp ứng, chứ không chỉ trên tồn vật lý. Lý do là hàng đã đặt sẽ về trong thời gian giao và đã góp phần bảo vệ cho chu kỳ đó; nếu chỉ nhìn tồn vật lý, hệ thống sẽ đặt lặp lại mỗi lần kiểm tra. Bài giảng phân biệt bốn dạng chính sách cơ bản:

| Chính sách | Cách vận hành | Tham số |
| --- | --- | --- |
| Kiểm tra liên tục, lượng đặt cố định, ký hiệu s, Q | Mỗi khi vị thế tồn xuống tới hoặc dưới s thì đặt một lượng Q | Điểm đặt hàng lại s, lượng đặt Q |
| Kiểm tra liên tục, đặt lên mức mục tiêu, ký hiệu s, S | Mỗi khi vị thế tồn xuống tới hoặc dưới s thì đặt đủ để đưa vị thế tồn lên S | s và mức tồn mục tiêu S |
| Kiểm tra định kỳ, đặt lên mức mục tiêu, ký hiệu R, S | Cứ mỗi R ngày kiểm tra một lần và đặt đủ để đưa vị thế tồn lên S | Chu kỳ kiểm tra R và S |
| Kiểm tra định kỳ có ngưỡng, ký hiệu R, s, S | Mỗi R ngày kiểm tra; chỉ đặt khi vị thế tồn không quá s | R, s và S |

Với kiểm tra liên tục, khoảng thời gian cần được bảo vệ khỏi biến động là thời gian giao L. Với kiểm tra định kỳ, khoảng cần bảo vệ là R cộng L, vì một đơn đặt hôm nay phải đủ dùng tới khi đơn của lần kiểm tra kế tiếp về tới quán. Bài giảng 12 của môn này trình bày trực tiếp mức tồn mục tiêu cho chính sách R, S theo cửa sổ R cộng L.

### 3.2. Điểm đặt hàng lại, tồn an toàn và hai thước đo mức phục vụ

Kết quả chuẩn của bài giảng 11 là điểm đặt hàng lại bằng nhu cầu kỳ vọng trong thời gian giao cộng tồn an toàn:

```latex
s = \hat{x}_L + k\,\sigma_L
```

Trong đó x mũ L là dự báo nhu cầu cộng dồn trong thời gian giao, k là hệ số an toàn và σ L là độ lệch chuẩn của **sai số dự báo** cộng dồn trong thời gian giao, ước lượng bằng căn trung bình bình phương sai số. Bài giảng nhấn mạnh đây là sai số dự báo chứ không phải độ lệch chuẩn của chính số bán, vì phần biến động đã được dự báo giải thích thì không cần dự phòng thêm.

Hai thước đo mức phục vụ thường bị lẫn với nhau:

- **Mức phục vụ chu kỳ**, ký hiệu CSL, là xác suất không hết hàng trong một chu kỳ bổ sung, bằng P của nhu cầu thời gian giao không vượt s. Nếu sai số phân phối chuẩn thì CSL bằng Φ của k, ví dụ k bằng 1,645 cho CSL 95%.
- **Tỷ lệ đáp ứng**, ký hiệu IFR hoặc P2, là tỷ lệ lượng nhu cầu được đáp ứng ngay từ tồn. Với chính sách s, Q và sai số chuẩn, lượng thiếu kỳ vọng mỗi chu kỳ bằng σ L nhân hàm tổn thất chuẩn đơn vị G của k, nên tỷ lệ đáp ứng bằng 1 trừ σ L nhân G của k chia Q.

```latex
CSL = P[x_L \le s] = \Phi(k), \qquad E[US] = \sigma_L\,G(k), \qquad IFR = 1 - \frac{\sigma_L\,G(k)}{Q}
```

Hai thước đo cho kết quả khác nhau: cùng một CSL, lượng đặt Q càng lớn thì tỷ lệ đáp ứng càng cao vì số lần đối mặt rủi ro ít hơn. Điều kiện của các công thức trên là dự báo không chệch, sai số cộng dồn xấp xỉ chuẩn, thời gian giao cố định và nhu cầu thiếu được ghi nợ chờ giao. Tại quán cà phê, khách thường đổi món hoặc bỏ đi nên nhu cầu thiếu là nhu cầu mất; theo Silver, Pyke và Peterson, khác biệt giữa hai giả định này nhỏ khi mức phục vụ cao, nên thiết kế vẫn dùng công thức ghi nợ và nêu rõ đây là xấp xỉ.

### 3.3. Thời gian giao biến động

Khi thời gian giao L là biến ngẫu nhiên độc lập với nhu cầu ngày, phương sai nhu cầu trong thời gian giao theo Silver, Pyke và Peterson 1998, giáo trình chính của môn ESD.260J, là:

```latex
\sigma^2_{DL} = E[L]\,\sigma_D^2 + \bar{D}^2\,\sigma_{L}^2
```

Điều kiện là nhu cầu các ngày độc lập cùng phân phối và thời gian giao độc lập với nhu cầu. Khi nhu cầu có mùa vụ theo ngày trong tuần, điều kiện cùng phân phối không thỏa, nên công thức chỉ dùng như xấp xỉ.

### 3.4. Nhu cầu không dừng và tồn an toàn thích nghi

Stephen Graves cùng David Simchi-Levi giảng môn 15.763J Manufacturing System and Supply Chain Design tại MIT. Nội dung bài giảng của môn tập trung vào thiết kế hệ thống, nên cơ sở tồn kho của Graves được lấy từ các bài báo gốc. Graves 1999 xét nhu cầu theo quá trình trung bình trượt tích hợp bậc 0, 1, 1, tức mức nhu cầu trôi dần theo thời gian, và chính sách mức tồn cơ sở thích nghi dùng dự báo san bằng mũ với hệ số α. Kết quả chính là phương sai sai số dự báo cộng dồn trong L kỳ bằng:

```latex
\operatorname{Var}\Big[\sum_{i=1}^{L} e_{t+i}\Big] = \sigma^2 \sum_{i=0}^{L-1} (1 + i\alpha)^2
```

Với α lớn hơn 0, đại lượng này tăng nhanh hơn L, nên tồn an toàn tăng nhanh hơn căn bậc hai của thời gian giao. Khi nhu cầu có xu hướng trôi, quy tắc nhân độ lệch chuẩn một ngày với căn bậc hai số ngày sẽ đánh giá thấp rủi ro. Graves và Willems 2000 mở rộng ý tưởng mức tồn cơ sở sang chuỗi cung ứng nhiều tầng; thiết kế này chỉ dùng kết quả một tầng.

### 3.5. Hàng dễ hỏng và bài toán một kỳ

Bài giảng 14 của ESD.260J trình bày mô hình một kỳ: khi hàng không bán hết trong kỳ thì mất giá trị, lượng đặt tối ưu là phân vị của phân phối nhu cầu tại tỷ số tới hạn bằng chi phí thiếu một đơn vị chia cho tổng chi phí thiếu và chi phí dư một đơn vị. Điều kiện là biết hai chi phí đó và nhu cầu của kỳ. Mô hình này là cơ sở lý thuyết cho việc giới hạn lượng mua nguyên liệu tươi theo hạn dùng.

### 3.6. Lượng đặt kinh tế

Công thức lượng đặt kinh tế bằng căn bậc hai của hai lần chi phí mỗi lần đặt nhân nhu cầu năm, chia chi phí giữ hàng mỗi đơn vị mỗi năm. Điều kiện là nhu cầu đều, biết chi phí đặt hàng cố định, đơn giá và tỷ lệ chi phí giữ hàng, và hạn dùng không ràng buộc.

### 3.7. Dự báo Bayes và đánh giá dự báo xác suất

West và Harrison 1997 trình bày mô hình tuyến tính động Bayes với hệ số chiết khấu: trạng thái mức và mùa vụ được cập nhật theo định lý Bayes sau mỗi quan sát, độ bất định tăng dần khi dữ liệu cũ mất giá trị, và mô hình cho phân phối dự báo đầy đủ thay vì một con số. West, Harrison và Migon 1985 mở rộng sang dữ liệu đếm, là cơ sở của mô hình Poisson đang có trong dự án. Gneiting và Raftery 2007 định nghĩa điểm xác suất liên tục xếp hạng CRPS để chấm dự báo phân phối. Hyndman và Athanasopoulos trình bày đánh giá theo gốc dự báo trượt, mỗi lần chỉ dùng dữ liệu tới gốc để dự báo về sau.

### 3.8. Ranh giới giữa lý thuyết và lựa chọn thiết kế

| Nội dung | Thuộc lý thuyết đã công bố | Thuộc lựa chọn thiết kế của LAM Coffee |
| --- | --- | --- |
| Ra quyết định trên vị thế tồn kho | Có, Caplice | Định nghĩa cụ thể tồn có thể dùng, hàng đang về trong cửa sổ và cam kết chưa trừ, mục 5 |
| s bằng nhu cầu thời gian giao cộng kσ L | Có, Caplice | Đo σ trực tiếp theo cửa sổ bằng đánh giá gốc trượt; mức CSL mặc định theo nhóm |
| Cửa sổ bảo vệ R cộng L | Có, Caplice | R bằng 7 ngày cho nhóm ổn định |
| Tồn an toàn tăng nhanh hơn căn L khi nhu cầu trôi | Có, Graves 1999 | Không dùng quy tắc căn h khi đã có số đo; chỉ dùng làm phương án dự phòng có ghi nhãn |
| Giới hạn theo hạn dùng | Mô hình một kỳ cho lý do | Quy tắc chặn lượng mua và làm tròn xuống có điều kiện, mục 6 |
| Dự báo Bayes | Có, West và Harrison | Dùng kinh nghiệm mua hàng của Chủ quán làm tiên nghiệm |
| Kiểm tra dòng tồn theo ngày | Không phải kết quả riêng của nguồn nào | Quy tắc của dự án để lô về trễ không che rủi ro, mục 8 |

## 4. Đối tượng dự báo và phương pháp dự báo

### 4.1. Đối tượng dự báo

**Lựa chọn thiết kế của LAM Coffee.** Đối tượng dự báo chính là lượng tiêu hao do bán hàng của từng nguyên liệu, tính theo đơn vị chuẩn của nguyên liệu đó là g, ml, cái, quả hoặc gói. Kết quả được trình bày theo tuần từ thứ Hai đến Chủ nhật và theo tháng dương lịch. Bên trong, mỗi nguyên liệu vẫn được tính theo ngày vì hai lý do. Thứ nhất, thời gian giao tối đa một ngày nên nhu cầu trong thời gian giao phụ thuộc mạnh vào ngày cụ thể: một tối thứ Năm cần bảo vệ cho thứ Sáu và thứ Bảy, khác hẳn một tối Chủ nhật. Thứ hai, chênh lệch giữa cuối tuần và ngày thường là thành phần mùa vụ lớn nhất của quán. Dự báo theo ngày ở đây là theo ngày của khoảng 58 nguyên liệu, không phải theo ngày của từng món và kích cỡ như hiện nay.

### 4.2. So sánh hai hướng tiếp cận

Hướng A dự báo trực tiếp chuỗi tiêu hao của từng nguyên liệu. Hướng B dự báo số ly theo món hoặc nhóm món rồi quy đổi sang nguyên liệu qua định mức.

| Tiêu chí | Hướng A, tiêu hao nguyên liệu | Hướng B, món hoặc nhóm món qua định mức |
| --- | --- | --- |
| Số chuỗi cần dự báo | Khoảng 58, mỗi chuỗi có lượng lớn và ít ngày bằng 0 | Hàng chục tổ hợp món, kích cỡ, tùy chọn; nhiều chuỗi thưa |
| Biến động tổng của nguyên liệu | Đo trực tiếp, đã gồm tương quan giữa các món dùng chung nguyên liệu | Phải mô hình hóa tương quan giữa món; nếu coi các món độc lập thì đánh giá thấp biến động khi cả quán cùng đông |
| Đổi định mức | Cần dựng lại chuỗi lịch sử theo định mức mới, xem mục 5 | Tự nhiên, chỉ cần đổi hệ số quy đổi |
| Món mới, đổi thực đơn, khuyến mãi một món | Yếu, vì chuỗi nguyên liệu chưa phản ánh thay đổi | Mạnh, vì tác động đặt đúng vào món |
| Giải thích cho Chủ quán | Trực tiếp: quán dùng bao nhiêu sữa mỗi tuần | Gián tiếp qua nhiều món |
| Đối chiếu với kinh nghiệm mua hàng | Khớp cách Chủ quán nghĩ: mỗi tuần mua khoảng bao nhiêu hộp | Khó đối chiếu |
| Chi phí tính và kiểm thử | Thấp | Cao hơn, đã có mã |

**Khuyến nghị.** Dùng Hướng A làm đường chính cho quyết định mua. Chuỗi tiêu hao không lấy thẳng từ sổ biến động mà được dựng lại từ các dòng bán có tính tiền nhân định mức, nhờ vậy tách được ly hủy sau pha chế, xử lý được đổi định mức và phiếu dự phòng nhập bù, xem mục 5.

Chuyển sang Hướng B, hoặc cộng thêm một phần điều chỉnh theo Hướng B, trong các trường hợp sau:

- Món mới hoặc tùy chọn mới chiếm phần đáng kể trong tiêu hao của một nguyên liệu, ví dụ trên 20% theo ước tính của Chủ quán.
- Thực đơn đổi lớn, ngừng bán món, hoặc khuyến mãi riêng một món.
- Tỷ trọng các món dùng chung một nguyên liệu dịch chuyển rõ, ví dụ khi một món mới hút khách khỏi món cũ.
- Nguyên liệu chỉ dùng cho một món ít bán, khi chuỗi nguyên liệu quá thưa.

Mô hình Poisson theo món hiện có vẫn được giữ cho các trường hợp trên và cho nhu cầu dự báo số ly phục vụ việc sắp ca. Nó không còn là nguồn mặc định cho quyết định mua.

### 4.3. Tầm dự báo

Tầm dự báo là tham số cấu hình, không cố định 14 ngày. Có hai tầm:

- **Tầm quyết định** của mỗi nguyên liệu bằng thời gian giao cộng chu kỳ kiểm tra hoặc khoảng cách mua mong muốn, cộng thêm hạn dùng nếu cần kiểm tra lượng dùng được trước khi hết hạn, cộng một ngày dự phòng. Với nhóm kiểm tra hằng tuần, tầm quyết định khoảng 9 ngày; với sữa tươi hạn dùng 7 ngày, khoảng 9 ngày.
- **Tầm hiển thị** mặc định 35 ngày để có nhu cầu tuần này, tuần sau và tháng này. Phần vượt tầm quyết định chỉ để Chủ quán lập kế hoạch, không dùng để tính tồn an toàn.

Tham số hiện có giới hạn tầm tối đa 60 ngày được giữ.

### 4.4. Phương pháp dự báo và vai trò của Bayes

Bayes là một phương pháp dự báo, không phải công thức điểm đặt hàng lại. Mọi phương pháp dưới đây đều chỉ cung cấp nhu cầu kỳ vọng theo ngày và thước đo sai số; chính sách tồn kho ở mục 6 dùng chung các đầu ra đó.

| Phương pháp | Mô tả | Khi dùng |
| --- | --- | --- |
| M0. Ước tính của Chủ quán | Chủ quán cho lượng mua thường lệ mỗi tuần, mức thấp và mức cao; phân bổ theo ngày bằng hồ sơ ngày trong tuần | Khi chưa đủ dữ liệu, và làm tiên nghiệm cho M2 |
| M1. Trung bình theo thứ | Trung bình tiêu hao cùng thứ trong 4 đến 8 tuần gần nhất, chỉ trên ngày đủ điều kiện | Phương pháp đơn giản bắt buộc phải so sánh |
| M2. Mô hình tuyến tính động Bayes | Trạng thái mức và hệ số theo thứ, cập nhật mỗi ngày đủ điều kiện, hệ số chiết khấu mức 0,95 và mùa vụ 0,99 lấy theo tham số hiện có | Khi có đủ dữ liệu và thắng M1 trong đánh giá |

**Tiên nghiệm từ kinh nghiệm Chủ quán.** Chủ quán thường nhớ theo đơn vị mua, ví dụ mỗi tuần khoảng 20 hộp sữa một lít, tuần thấp 16 hộp, tuần cao 25 hộp. Thiết kế quy đổi sang đơn vị chuẩn, lấy mức thường lệ làm trung bình tuần và coi khoảng thấp đến cao là khoảng tin cậy 90%, nên độ lệch chuẩn tiên nghiệm của tổng tuần bằng độ rộng khoảng chia 3,29. Trong ví dụ này trung bình 20.000 ml mỗi tuần và độ lệch chuẩn khoảng 2.740 ml. Độ bất định được ghi rõ trên màn hình, không ẩn đi. Cách làm này cùng tinh thần với hàm chuyển nhận định chuyên gia sang tiên nghiệm Gamma đã có trong mã.

**Bộ dữ liệu mô phỏng 6 tháng** chỉ dùng để kiểm thử kỹ thuật: mô hình chạy, không lỗi số, cập nhật đúng khi bỏ qua ngày đóng cửa. Kết quả trên dữ liệu đó không phải bằng chứng về độ chính xác trên dữ liệu thật của quán.

**Chọn phương pháp.** Phương pháp được chọn cho từng nguyên liệu theo sai số của tổng nhu cầu trong cửa sổ bảo vệ, đo bằng đánh giá gốc dự báo trượt ở mục 12. Theo BRU-37, phương pháp chỉ được thay khi sai số thấp hơn rõ rệt trong một khoảng đủ dài; thiết kế đề xuất thấp hơn ít nhất 5% trên ít nhất 4 tuần gốc dự báo, ghi là giả định cấu hình.

**Khi dữ liệu ngắn.** Ba giai đoạn theo BRU-21 được ánh xạ như sau:

| Giai đoạn | Số ngày đủ điều kiện | Nhu cầu kỳ vọng | Sai số dùng cho tồn an toàn | Nhãn hiển thị |
| --- | --- | --- | --- | --- |
| Ước tính ban đầu | Dưới 14 | M0 | Từ khoảng thấp cao của Chủ quán | Tạm thời, theo ước tính Chủ quán |
| Thống kê bước đầu | 14 đến 55 | M1, hoặc M2 có tiên nghiệm M0 | Độ lệch phần dư nhân căn số ngày, có ghi nhãn | Thống kê bước đầu, độ tin cậy thấp |
| Mô hình | Từ 56 | Phương pháp thắng trong đánh giá | Đo trực tiếp theo cửa sổ | Đã đánh giá |

Khi dữ liệu ngắn, hệ thống không hiển thị khoảng tin cậy hẹp như thể đã chắc chắn; nhãn giai đoạn luôn đi kèm con số.

## 5. Luồng dữ liệu và định nghĩa đại lượng

### 5.1. Luồng dữ liệu

Luồng xử lý gồm năm bước, chạy lại toàn bộ mỗi ngày sau khi chốt ngày, và chạy riêng phần chính sách cho một nguyên liệu sau mỗi biến động tồn của nguyên liệu đó.

1. **Dựng chuỗi tiêu hao.** Từ dòng món có tính tiền của ngày đủ điều kiện, quy đổi qua định mức sang lượng nguyên liệu theo ngày; tính riêng tỷ lệ hủy sau pha chế, tỷ lệ hao hụt vận hành và chênh lệch kiểm kê có hệ thống; gắn cờ ngày đóng cửa, chưa chốt và hết hàng.
2. **Dự báo.** Chạy M0, M1, M2 cho từng nguyên liệu, cho nhu cầu kỳ vọng theo ngày trong tầm hiển thị.
3. **Đo sai số cửa sổ.** Đánh giá gốc trượt cho độ lệch chuẩn sai số của tổng nhu cầu trong các cửa sổ 1 đến 10 ngày, chọn phương pháp.
4. **Tính chính sách.** Đọc tồn, đơn đặt hàng, tham số nguyên liệu; dựng dòng tồn dự kiến theo ngày; tính vị thế tồn, tồn an toàn, điểm đặt hàng lại, mức tồn mục tiêu, ngày rủi ro, ngày phải đặt và lượng đề xuất.
5. **Trình Chủ quán.** Ghi kết quả vào bảng kế hoạch nguyên liệu có khóa chống trùng, đồng bộ cảnh báo, hiển thị đề xuất. Chỉ khi Chủ quán xác nhận mới tạo đơn đặt hàng ở trạng thái Nháp.

| Nguồn dữ liệu hiện có | Dùng cho |
| --- | --- |
| Dòng món có tính tiền, kích cỡ, tùy chọn | Chuỗi tiêu hao bán hàng |
| Phiên bản định mức và ngày hiệu lực | Quy đổi lịch sử và tương lai |
| Hủy sau pha chế | Tỷ lệ tiêu hao không tính tiền |
| Phiếu hao hụt theo lý do | Tỷ lệ hao hụt vận hành; chỉ số hàng hết hạn |
| Phiếu kiểm kê | Chênh lệch có hệ thống |
| Trạng thái ngày, trường hợp thiếu nguyên liệu, báo Sắp hết và Đã hết | Cờ ngày |
| Tồn vật lý và tồn đang giữ | Tồn có thể dùng |
| Đơn đặt hàng và phiếu nhập | Hàng đang về, lịch sử thời gian giao |
| Hồ sơ bán theo giờ | Phần nhu cầu còn lại của hôm nay |

### 5.2. Định nghĩa đại lượng

Mọi đại lượng tính theo đơn vị chuẩn của nguyên liệu. Quy cách đóng gói chỉ xuất hiện ở bước làm tròn cuối cùng.

| Ký hiệu | Tên | Định nghĩa |
| --- | --- | --- |
| P | Tồn vật lý | Theo BRU-18: lần kiểm kê đã xác nhận gần nhất cộng nhập trừ tiêu hao khi Đã pha chế trừ hao hụt |
| G | Tồn đang giữ | Nhu cầu của món đã gửi pha chế nhưng chưa pha xong |
| A | Tồn có thể dùng | P trừ G; đã trừ sẵn nhu cầu đã cam kết trong quán |
| O(W) | Hàng đang về trong cửa sổ W | Tổng lượng còn phải giao của đơn Nháp, Đã đặt hoặc Giao một phần, có ngày giao dự kiến chưa quá hạn và hàng dùng được trước cuối cửa sổ W |
| C | Cam kết chưa trừ | Nhu cầu đã phát sinh nhưng chưa vào tồn đang giữ và chưa trừ kho; hiện chỉ gồm lượng ước tính của phiếu dự phòng chưa nhập bù |
| IP(W) | Vị thế tồn theo cửa sổ | A cộng O(W) trừ C |
| d(t) | Nhu cầu dự báo ngày t | Tiêu hao bán hàng kỳ vọng cộng các tỷ lệ ở mục 5.3 |
| μ(W), σ(W) | Nhu cầu và sai số cửa sổ | Tổng d(t) trong W; độ lệch chuẩn sai số của tổng đó |
| I(t) | Tồn dự kiến cuối ngày t | A trừ C cộng hàng về tới t trừ nhu cầu cộng dồn tới t |

Vị thế tồn được viết chính xác là:

```latex
IP(W) = \underbrace{(P - G)}_{A} + O(W) - C
```

**Không trừ hai lần.** Tồn đang giữ đã là nhu cầu cam kết của các món đang chờ pha; vì A đã trừ G nên C không được cộng lại các món đó. Khi món được pha xong, P và G cùng giảm một lượng nên A không đổi; tiêu hao lúc đó không được tính vào nhu cầu tương lai nữa vì đã phát sinh. Phần nhu cầu còn lại của hôm nay chỉ gồm các đơn chưa nhận, ước tính bằng tỷ lệ bán còn lại theo hồ sơ giờ. Trường hợp phiếu dự phòng khi mất mạng là ngoại lệ duy nhất: món đã bán và đã dùng nguyên liệu nhưng chưa trừ kho cho tới khi nhập bù, nên lượng đó vào C nếu đã biết.

### 5.3. Tách các nguồn tiêu hao

Thay đổi tồn vật lý của một nguyên liệu trong ngày t được phân rã như sau:

```latex
\Delta P_t = \text{Nhập}_t - \underbrace{\big(U^{b}_t + U^{h}_t\big)}_{\text{Tiêu hao pha chế}} - H^{vh}_t - H^{tk}_t + K_t
```

Trong đó U b là tiêu hao của ly có tính tiền, U h là tiêu hao của ly đã pha rồi hủy, H vh là hao hụt vận hành, H tk là hao hụt do tồn kho gồm hư hỏng và hết hạn, K là điều chỉnh kiểm kê. Nhu cầu dự báo được xây dựng từ từng thành phần:

| Thành phần | Cách đưa vào nhu cầu | Lý do |
| --- | --- | --- |
| Tiêu hao bán hàng U b | Dự báo ngẫu nhiên bằng M0, M1 hoặc M2 | Thành phần lớn nhất và biến động nhất |
| Hủy sau pha chế U h | Cộng tỷ lệ U h chia U b của 8 tuần gần nhất, nhân với dự báo U b | Nguyên liệu đã thực sự mất; theo BRU-18 không tạo biến động mới nhưng đã nằm trong tiêu hao pha chế |
| Hao hụt vận hành H vh, gồm pha hỏng, đổ vỡ và lý do khác | Cộng tỷ lệ theo U b, loại trừ sự cố đơn lẻ do Chủ quán đánh dấu | Lặp lại theo khối lượng công việc |
| Hao hụt do tồn kho H tk, gồm hư hỏng và hết hạn | Không cộng vào nhu cầu; dùng làm chỉ số đánh giá quyết định ở mục 12 | Là hệ quả của việc mua dư; cộng vào nhu cầu sẽ làm mua dư hơn và hỏng thêm |
| Kiểm kê K | Chỉ cộng khi âm liên tiếp ít nhất 4 lần kiểm kê, tính theo tỷ lệ trên U b | Chênh lệch ngẫu nhiên không phải nhu cầu; chênh lệch có hệ thống cho thấy định mức thực tế cao hơn khai báo |

```latex
d(t) = \hat{U}^{b}_t\,\big(1 + r_h + r_{vh} + r_{k}\big)
```

Phép kiểm đối soát bắt buộc: trên dữ liệu lịch sử, tổng U b cộng U h tính lại từ dòng món phải bằng tổng biến động pha chế trong sổ, sai lệch trên 1% thì báo lỗi dữ liệu. Nhờ phép kiểm này, ly hủy sau pha chế không bị tính hai lần và cũng không bị bỏ sót, khắc phục chỗ lệch hiện tại giữa chuỗi bán và chuỗi tiêu hao thực tế.

### 5.4. Định mức khi dựng chuỗi

Chuỗi lịch sử được dựng lại bằng cấu hình món, kích cỡ và tùy chọn của từng dòng nhân với định mức có hiệu lực tại ngày được dự báo, không phải định mức tại ngày bán. Nhờ vậy, khi giảm lượng sữa trong một món từ tuần sau, dự báo cho tuần sau đã phản ánh định mức mới ngay, không cần chờ mô hình học lại. Khi không có định mức hẹn ngày, kết quả trùng với lượng dùng đã chụp trên dòng đơn. Tùy chọn được tính đầy đủ từ dòng đơn thật, không còn quy tắc bỏ tùy chọn không bán trong 56 ngày. Phần quy đổi bán thành phẩm sang nguyên liệu thô tiếp tục theo quy tắc sẵn có của thực đơn.

### 5.5. Ngày đóng cửa, ngày chưa chốt và ngày hết hàng

| Loại ngày | Nhận biết | Xử lý khi học | Xử lý khi dự báo |
| --- | --- | --- | --- |
| Đóng cửa | Lịch mở cửa, trạng thái ngày hiện có | Bỏ qua, mô hình chỉ tăng độ bất định | Nhu cầu bằng 0, không tính vào cửa sổ |
| Chưa chốt | Trạng thái ngày hiện có | Bỏ qua cho tới khi chốt | Không áp dụng |
| Hết hàng của chính nguyên liệu | Có trường hợp thiếu nguyên liệu, hoặc báo Đã hết, hoặc tồn có thể dùng về 0 trong giờ mở cửa | Bỏ qua và đếm số ngày bị chặn; không dùng để đo sai số | Không áp dụng |
| Bị ảnh hưởng gián tiếp | Món dùng nguyên liệu này bị ngừng bán do thiếu nguyên liệu khác, và món đó chiếm từ 20% tiêu hao thường lệ của nguyên liệu này | Bỏ qua | Không áp dụng |

Doanh số thấp trong ngày hết hàng là nhu cầu bị chặn, không phải nhu cầu thấp. Nếu đưa vào mô hình, dự báo sẽ thấp xuống, hệ thống mua ít hơn và hết hàng lặp lại. Thiết kế bỏ ngày đó cho nguyên liệu liên quan và chưa ước tính nhu cầu bị mất. Cờ được xét theo từng nguyên liệu, gồm cả nguyên liệu của tùy chọn, khắc phục giới hạn hiện tại chỉ xét nguyên liệu của kích cỡ. Nếu một nguyên liệu bị chặn trên 20% số ngày trong 8 tuần, hệ thống báo rằng dự báo có thể thấp và trở lại dùng ước tính của Chủ quán.

## 6. Công thức và điều kiện áp dụng

Các công thức dưới đây là cách LAM Coffee vận dụng lý thuyết ở mục 3. Thời gian tính theo ngày mở cửa; ngày đóng cửa không nằm trong cửa sổ.

### 6.1. Thời gian giao và cửa sổ bảo vệ

Chủ quán cho biết nguyên liệu thường về tới quán nhiều nhất sau một ngày. Thiết kế định nghĩa **số ngày phơi nhiễm** ℓ là số ngày bán hàng trọn vẹn có thể trôi qua từ lúc đặt tới lúc hàng dùng được, trong trường hợp xấu. Với đơn đặt lúc đóng cửa và hàng có thể về bất kỳ lúc nào trong ngày hôm sau, giá trị thận trọng là ℓ bằng 1: toàn bộ nhu cầu ngày hôm sau phải được tồn hiện có che chở. Nếu Chủ quán xác nhận hàng luôn về trước giờ mở cửa, ℓ bằng 0. Đây là giả định cần xác nhận ở mục 13.

Quán ra quyết định mua ít nhất mỗi ngày một lần khi đóng cửa, nên về thực chất đây là kiểm tra định kỳ với chu kỳ R. Theo Caplice, khoảng cần bảo vệ của kiểm tra định kỳ là R cộng thời gian giao. Thiết kế dùng hai cửa sổ, đều bắt đầu từ thời điểm tính:

| Cửa sổ | Độ dài | Dùng để |
| --- | --- | --- |
| W s, cửa sổ kích hoạt | Phần còn lại của hôm nay cộng R cộng ℓ ngày | Quyết định có cần đặt ngay không, vì nếu để tới lần kiểm tra sau thì hàng về muộn thêm R ngày |
| W S, cửa sổ mục tiêu | Phần còn lại của hôm nay cộng T cộng ℓ ngày, với T không nhỏ hơn R | Quyết định đặt bao nhiêu để đủ dùng tới khi lô mua kế tiếp dùng được |

T là khoảng cách mong muốn giữa hai lần mua, do Chủ quán chọn theo thói quen đi chợ hoặc lịch giao của nhà cung cấp. Với nhóm kiểm tra hằng tuần, T bằng R bằng 7 và hai cửa sổ trùng nhau.

### 6.2. Nhu cầu cửa sổ và sai số cửa sổ

Nhu cầu kỳ vọng của cửa sổ là tổng đúng theo từng ngày, không nhân trung bình ngày với số ngày:

```latex
\mu(W) = f_{0}\,d(t_0) + \sum_{t \in W,\ t > t_0} d(t)
```

f 0 là tỷ lệ bán còn lại của hôm nay theo hồ sơ giờ, bằng 0 khi tính sau giờ đóng cửa. Độ lệch chuẩn sai số σ h của cửa sổ dài h ngày được đo trực tiếp: với mỗi gốc o trong 8 đến 12 tuần gần nhất, dự báo bằng dữ liệu tới o, cộng sai số của h ngày mở cửa kế tiếp, bỏ gốc có ngày hết hàng trong cửa sổ:

```latex
e_o(h) = \sum_{j=1}^{h} \big(x_{o+j} - \hat{x}_{o+j\mid o}\big), \qquad \sigma_h = \sqrt{\frac{1}{N}\sum_{o} e_o(h)^2}, \qquad b_h = \frac{1}{N}\sum_o e_o(h)
```

b h là độ chệch. Nếu độ chệch vượt 0,5 σ h, hệ thống cảnh báo dự báo lệch hệ thống và không dùng phương pháp đó cho tới khi sửa, vì công thức tồn an toàn giả định dự báo không chệch. Đo trực tiếp theo từng h là cách tôn trọng kết quả của Graves 1999: khi nhu cầu trôi, sai số cộng dồn tăng nhanh hơn căn bậc hai của h.

**Phương án dự phòng khi lịch sử ngắn.** Khi có dưới 8 gốc cho cửa sổ h, dùng σ h bằng căn h nhân σ 1, kèm nhãn Ước lượng tạm. Khi chưa có σ 1, lấy từ khoảng thấp cao của Chủ quán ở mục 4.4. Hai cách này có xu hướng đánh giá thấp rủi ro nên chỉ dùng tạm thời.

### 6.3. Tồn an toàn, điểm đặt hàng lại và mức tồn mục tiêu

```latex
SS(W) = k\,\sigma(W), \qquad s = \mu(W_s) + SS(W_s), \qquad S = \mu(W_S) + SS(W_S), \qquad k = \Phi^{-1}(CSL)
```

**Quy tắc kích hoạt.** Cần đặt khi IP(W s) nhỏ hơn hoặc bằng s. Vị thế tồn dùng cùng cửa sổ với s, nên hàng đang về sau cuối cửa sổ không được tính. Không kích hoạt chỉ dựa trên tồn vật lý.

**Khi dùng phân phối dự báo.** Nếu phương pháp dự báo cho phân phối của tổng cửa sổ, ví dụ M2 bằng mô phỏng đường, thì điểm đặt hàng lại là phân vị tại mức phục vụ và tồn an toàn chỉ là con số suy ra để hiển thị:

```latex
s = q_{CSL}\big(X(W_s)\big), \qquad SS(W_s) = s - \mu(W_s)
```

Không cộng thêm kσ vào phân vị. Mỗi nguyên liệu chỉ dùng một trong hai cách. Cách phân vị chỉ được bật khi độ phủ thực tế của phân vị đó trong đánh giá gốc trượt nằm trong khoảng CSL cộng trừ 3 điểm phần trăm; nếu không, dùng trung bình cộng kσ đo được. Một cửa sổ duy nhất được dùng cho cả cột kỳ vọng và cột phân vị, sửa lệch một ngày hiện nay.

### 6.4. Mức phục vụ

**Mức phục vụ chu kỳ** là tham số cài đặt: xác suất một lần bổ sung kết thúc mà tồn có thể dùng chưa về 0. Mặc định 95%, k bằng 1,645, cho nguyên liệu đánh dấu trọng yếu; 90%, k bằng 1,282, cho nguyên liệu khác. Đây là giả định, Chủ quán có thể đổi theo từng nguyên liệu. Với hàng dễ hỏng, nếu biết lãi gộp mất khi thiếu một đơn vị c u và giá vốn mất khi một đơn vị hết hạn c o, có thể chọn CSL theo tỷ số tới hạn của mô hình một kỳ:

```latex
CSL^{*} = \frac{c_u}{c_u + c_o}
```

**Tỷ lệ đáp ứng** là kết quả đo, không phải tham số cài đặt, vì quán không ghi được nhu cầu bị mất khi hết hàng. Hệ thống ước tính xấp xỉ bằng nhu cầu dự báo trong khoảng thời gian hết hàng, xem mục 12. Hai thước đo được hiển thị tách biệt và không được gọi chung là mức phục vụ.

### 6.5. Thời gian giao biến động

Khi chưa có lịch sử, dùng ℓ cấu hình theo mục 6.1. Khi một nguyên liệu có từ 10 đơn đã giao, hệ thống tính số ngày phơi nhiễm thực tế của từng đơn từ ngày chuyển sang Đã đặt tới ngày nhận. Thiết kế chọn cách đơn giản là lấy ℓ bằng phân vị 90% của số ngày phơi nhiễm, làm tròn lên, rồi áp dụng các công thức trên với cửa sổ tương ứng. Cách này giữ được mùa vụ theo thứ. Công thức phương sai của Silver, Pyke và Peterson ở mục 3.3 được giữ làm phương án so sánh cho nhóm nhu cầu ổn định, vì điều kiện nhu cầu ngày cùng phân phối không thỏa khi có mùa vụ theo thứ.

### 6.6. Dòng tồn dự kiến, ngày rủi ro và ngày phải đặt

```latex
I(t) = A - C + \sum_{j:\ a_j \le t} o_j - \mu\big([t_0, t]\big)
```

o j là lượng còn phải giao của đơn j, a j là ngày hàng dùng được theo giả định ℓ. Đơn quá hạn không nằm trong tổng.

- **Ngày dự kiến hết hàng** là ngày đầu tiên I(t) âm.
- **Ngày rủi ro** là ngày đầu tiên I(t) nhỏ hơn kσ của cửa sổ từ nay tới t, tức xác suất hết hàng trước t vượt 1 trừ CSL.
- **Ngày phải đặt chậm nhất** là ngày kiểm tra muộn nhất mà đơn đặt hôm đó còn dùng được trước ngày rủi ro, bằng ngày rủi ro lùi ℓ cộng 1 ngày mở cửa. Nếu ngày này đã qua, hệ thống ghi Đặt ngay và đánh dấu khả năng phải mua gấp.

Quy tắc kích hoạt ở mục 6.3 và ngày rủi ro cho cùng kết luận khi các lô đang về đều nằm trong cửa sổ. Khi có lô về sau ngày rủi ro, chỉ dòng tồn theo ngày mới thấy được khoảng thiếu trước khi lô đó về, nên cả hai đều được tính và hệ thống lấy kết luận khắt khe hơn.

### 6.7. Số lượng đặt

Thời điểm đặt và số lượng đặt là hai quyết định khác nhau. Số lượng được tính theo trình tự sau, mọi bước trước làm tròn đều theo đơn vị chuẩn.

1. Lượng thiếu so với mức mục tiêu:

```latex
Q_{0} = \max\big(0,\ S - IP(W_S)\big)
```

2. Giới hạn hạn dùng, giả định dùng hàng cũ trước. Gọi a là ngày lô mới dùng được, SL là hạn dùng tính từ ngày nhận và I trước a là tồn dự kiến cũ hơn lô mới tại lúc lô về. Lượng tối đa dùng hết trước hạn là:

```latex
Q_{hd} = \max\Big(0,\ \mu\big([a,\ a + SL)\big) - I(a^{-})\Big)
```

3. Giới hạn sức chứa: Q nhỏ hơn hoặc bằng sức chứa trừ I trước a.
4. Làm tròn theo quy cách p và lượng đặt tối thiểu MOQ tính bằng số gói:

```latex
n = \max\Big(\Big\lceil \tfrac{Q_0}{p} \Big\rceil,\ MOQ\Big), \qquad \Delta = n\,p - Q_0
```

Δ là phần làm tròn và luôn được hiển thị.

5. Nếu n nhân p vượt Q hd hoặc sức chứa: thử số gói lớn nhất không vượt giới hạn. Nếu với số gói đó vị thế tồn vẫn không thấp hơn s, dùng số gói đó và ghi rằng lần mua kế tiếp sẽ sớm hơn T. Nếu không, dùng số gói nhỏ nhất đưa vị thế tồn lên s và cảnh báo lượng dự kiến hết hạn.
6. Với nhóm kiểm tra hằng tuần, nếu Q 0 nhỏ hơn một nửa gói thì không đề xuất mua tuần này, tương đương chính sách R, s, S.

**Lượng đặt kinh tế không dùng mặc định.** Nếu sau này muốn chọn T theo lượng đặt kinh tế, cần chi phí mỗi lần đặt A gồm phí giao và thời gian đi mua, đơn giá v, tỷ lệ chi phí giữ hàng r theo năm, nhu cầu năm D tương đối đều và hạn dùng không ràng buộc. Khi đó T bằng lượng đặt kinh tế chia nhu cầu ngày, làm tròn về số ngày và vẫn bị giới hạn bởi hạn dùng:

```latex
EOQ = \sqrt{\frac{2AD}{v\,r}}
```

## 7. Chính sách theo nhóm nguyên liệu

### 7.1. Dự báo hằng tuần không có nghĩa là kiểm tra hằng tuần

Nhu cầu được trình bày theo tuần để Chủ quán dễ đọc, nhưng tần suất kiểm tra tồn và đặt hàng là quyết định riêng của từng nguyên liệu. Về kỹ thuật, hệ thống có thể kiểm tra liên tục sau mỗi biến động tồn vì mỗi lần tính cho một nguyên liệu rất nhẹ. Tuy nhiên mô hình kiểm tra liên tục thuần túy giả định có thể đặt hàng bất kỳ lúc nào, trong khi Chủ quán thực tế đặt qua điện thoại hoặc đi chợ, thường vào cuối ngày hoặc sáng sớm. Thiết kế vì vậy tách hai việc: **giám sát liên tục** sau mỗi biến động để phát hiện sớm rủi ro, và **quyết định mua định kỳ** theo chu kỳ R của từng nhóm.

### 7.2. Hai nhóm chính sách

| Thuộc tính | Nhóm A, dễ hỏng hoặc tiêu hao nhanh | Nhóm B, ổn định, hạn dùng dài |
| --- | --- | --- |
| Ví dụ | Sữa tươi, kem tươi dùng làm kem muối, trái cây tươi, bánh tươi nếu có | Cà phê bột, đường, sữa đặc, bột cacao, bột matcha, siro, mứt, trà gói, trân châu khô, ly, ống hút |
| Tiêu chí mặc định | Hạn dùng từ 14 ngày trở xuống, hoặc Chủ quán xếp vào nhóm này | Các nguyên liệu còn lại |
| Chính sách | Kiểm tra hằng ngày lúc đóng cửa với R bằng 1, dạng R, s, S | Kiểm tra hằng tuần với R bằng 7, dạng R, S có ngưỡng bỏ qua đơn quá nhỏ |
| Cửa sổ kích hoạt | R cộng ℓ, mặc định 2 ngày | R cộng ℓ, mặc định 8 ngày |
| Cửa sổ mục tiêu | T cộng ℓ, T mặc định 2 ngày, không vượt hạn dùng | Trùng cửa sổ kích hoạt |
| Ngày kiểm tra | Mỗi tối lúc chốt ngày | Một ngày cố định trong tuần, mặc định tối Chủ nhật |
| Giới hạn hạn dùng | Luôn kiểm tra | Kiểm tra nếu có khai báo hạn dùng |
| Giám sát giữa hai lần kiểm tra | Sau mỗi biến động; cảnh báo ngay nếu ngày rủi ro rơi vào trước lần kiểm tra kế tiếp cộng ℓ | Sau mỗi biến động; cùng quy tắc, sinh đề xuất mua gấp nằm ngoài lịch tuần |
| CSL mặc định | 95% nếu trọng yếu, 90% nếu không | 95% nếu trọng yếu, 90% nếu không |

Trân châu cần lưu ý: trân châu khô mua về có hạn dùng dài nên thuộc nhóm B; trân châu đã nấu chỉ dùng trong vài giờ là bài toán sơ chế trong ngày, không phải bài toán mua, và nằm ngoài phạm vi thiết kế này. Kem muối được xử lý qua nguyên liệu thô của nó là kem tươi, muối và sữa, theo quy tắc quy đổi bán thành phẩm đã có. Danh sách cụ thể của 58 nguyên liệu sẽ do Chủ quán xác nhận khi khai báo quy cách và hạn dùng.

### 7.3. Vì sao chính sách này phù hợp với cách quán vận hành

Thứ nhất, thời gian giao tối đa một ngày nên quán không cần giữ tồn lớn; rủi ro chính là quên đặt hoặc đặt muộn trước cuối tuần, điều mà giám sát liên tục và ngày phải đặt giải quyết trực tiếp. Thứ hai, nhóm A có hạn dùng ngắn nên mua thưa và nhỏ giọt là hợp lý, T bằng 2 ngày là mức cân bằng giữa số lần mua và lượng hết hạn. Thứ ba, nhóm B gom vào một lần kiểm tra mỗi tuần giúp Chủ quán gộp đơn cho cùng nhà cung cấp, giảm số lần gọi đặt hàng; đổi lại tồn an toàn phải che chở 8 ngày. Thứ tư, giám sát liên tục chỉ sinh cảnh báo khi rủi ro rơi vào trước lần kiểm tra kế tiếp, nên không làm phiền Chủ quán bằng cảnh báo sau mỗi ly bán.

Nếu Chủ quán thực tế mua theo lịch cố định khác, ví dụ nhà cung cấp sữa giao thứ Hai, thứ Tư, thứ Sáu, thì R và T của nguyên liệu đó được đặt theo lịch giao, công thức giữ nguyên.

### 7.4. Tham số theo nguyên liệu

| Tham số | Mặc định | Nguồn |
| --- | --- | --- |
| Nhóm chính sách | Theo hạn dùng | Chủ quán có thể đổi |
| R, T, ngày kiểm tra | Theo bảng 7.2 | Chủ quán có thể đổi |
| ℓ | 1 | Chủ quán xác nhận; sau 10 đơn thì tính từ lịch sử |
| CSL | 95% hoặc 90% | Chủ quán có thể đổi |
| Quy cách, MOQ | Phải khai báo; MOQ mặc định 1 gói | Chủ quán |
| Hạn dùng, sức chứa | Bắt buộc với nhóm A | Chủ quán |
| Trọng yếu | Theo trường hiện có | Chủ quán |

Tồn an toàn nhập tay hiện có không còn là tham số đầu vào chính. Nó được giữ làm mức sàn: nếu Chủ quán nhập một số lớn hơn tồn an toàn tính được, hệ thống dùng số của Chủ quán và ghi rõ lý do trên đề xuất.

## 8. Hàng đang về, đơn trùng và chống ghi trùng

### 8.1. Trạng thái đơn đặt hàng

| Trạng thái | Ý nghĩa | Tính vào hàng đang về | Mới hay có sẵn |
| --- | --- | --- | --- |
| Nháp | Chủ quán đã chấp nhận đề xuất, chưa báo nhà cung cấp | Có, để không sinh đề xuất trùng; hiển thị riêng là Chưa đặt với nhà cung cấp và nhắc lại nếu tới ngày phải đặt | Mới |
| Đã đặt | Đã báo và nhà cung cấp đã xác nhận | Có, phần còn phải giao | Có sẵn |
| Giao một phần | Đã nhận một phần | Có, chỉ phần còn lại | Có sẵn |
| Giao chậm | Quá ngày giao dự kiến mà chưa đủ, xác định khi đọc | Không, cho tới khi Chủ quán cập nhật ngày mới | Có sẵn |
| Đã giao đủ | Lượng nhận bằng hoặc vượt lượng đặt | Không | Có sẵn |
| Đã hủy | Chủ quán hủy, giữ lại để truy vết | Không | Mới |

Lượng còn phải giao luôn là lượng đặt trừ lượng đã nhận, không nhỏ hơn 0. Nhận vượt số đặt vẫn được ghi nhận nhưng có cảnh báo để Chủ quán biết. Đơn Nháp tồn tại quá ngày phải đặt chậm nhất sẽ không còn được tính là hàng đang về và được nhắc ngay, để một bản nháp bị quên không che rủi ro.

### 8.2. Lô về muộn không được che rủi ro

Vị thế tồn cổ điển cộng mọi hàng đang về bất kể ngày về. Nếu một lô về sau ngày dự kiến hết hàng, vị thế tồn có thể vẫn cao hơn điểm đặt hàng lại trong khi quán sẽ hết hàng trước khi lô đó tới. Thiết kế xử lý bằng hai cơ chế đã nêu ở mục 5 và 6: chỉ tính hàng đang về dùng được trong cửa sổ, và luôn dựng dòng tồn dự kiến theo ngày. Khi dòng tồn cho thấy rủi ro trước ngày một lô đã đặt về, hệ thống đưa ra một trong ba hành động:

| Tình huống | Hành động đề xuất | Lượng |
| --- | --- | --- |
| Có lô Đã đặt về sau ngày rủi ro, nhà cung cấp có thể giao sớm | Thúc giao, đề nghị ngày giao mới không muộn hơn ngày rủi ro | Không đổi |
| Có lô về sau ngày rủi ro, không thể giao sớm | Mua bổ sung | Đủ để dòng tồn không xuống dưới mức an toàn cho tới ngày lô đó về, làm tròn theo quy cách |
| Lô quá hạn giao | Thúc giao hoặc cập nhật ngày mới; trong lúc chờ, tính như không có lô | Theo công thức mục 6.7 |

### 8.3. Tránh đề xuất trùng

Vì mọi đơn Nháp, Đã đặt và Giao một phần còn hiệu lực đều nằm trong vị thế tồn của cửa sổ, lần tính sau khi Chủ quán đã chấp nhận một đề xuất sẽ tự cho lượng thiếu bằng 0. Một đề xuất mới chỉ xuất hiện khi vẫn còn thiếu, và khi đó được gắn nhãn **Mua bổ sung**, kèm danh sách đơn liên quan, thay vì một đề xuất mua mới như lần đầu.

### 8.4. Chạy lại không sinh bản ghi trùng

| Đối tượng | Khóa chống trùng | Hành vi khi chạy lại |
| --- | --- | --- |
| Kết quả tính cho một nguyên liệu | Nguyên liệu, ngày tính và mã phiên bản dữ liệu gồm biến động tồn cuối, lần sửa đơn đặt hàng cuối, bản dự báo và bản tham số | Cùng dữ liệu thì trả về đúng bản đã có; dữ liệu đổi thì tạo bản mới và đánh dấu bản cũ đã thay thế |
| Xác nhận đề xuất thành đơn Nháp | Khóa thao tác của biểu mẫu qua cơ chế chạy một lần hiện có | Gửi lại trả về đơn đã tạo; việc lưu đề xuất nằm trong cùng thao tác, sửa lỗi lưu lần hai hiện nay |
| Cảnh báo Cần đặt hàng | Nguyên liệu và đợt rủi ro, xác định bằng ngày bắt đầu đợt | Một đợt chỉ có một cảnh báo; khi vị thế tồn đã lên trên s rồi lại xuống, đợt mới có cảnh báo mới dù cảnh báo cũ đã đóng tay |
| Giám sát sau biến động | Nguyên liệu và mã biến động | Chạy sau khi giao dịch ghi tồn đã hoàn tất; nhiều biến động liền nhau chỉ cần lần tính cuối |

Mọi lần tính đều là đọc và ghi kết quả tính toán; không lần tính nào tự tạo đơn đặt hàng hay gửi tin cho nhà cung cấp.

## 9. Đầu ra cho Chủ quán

### 9.1. Thông tin cho từng nguyên liệu

| Trường | Nội dung |
| --- | --- |
| Tồn vật lý và tồn có thể dùng | P và A tại thời điểm tính, kèm số ngày đủ dùng |
| Tồn đang giữ | G |
| Hàng đang về | Từng đơn còn hiệu lực với lượng còn phải giao, ngày dự kiến, trạng thái; đơn quá hạn hiển thị riêng |
| Dự báo tuần này, tuần sau, tháng này | Nhu cầu kỳ vọng và khoảng 80%, theo đơn vị chuẩn và quy ra số gói |
| Nhu cầu trong thời gian giao | μ của cửa sổ kích hoạt, có ghi cửa sổ gồm những ngày nào |
| Tồn an toàn | SS theo đơn vị chuẩn, CSL đang dùng và cách tính σ: đo trực tiếp, ước lượng tạm hoặc theo Chủ quán |
| Điểm đặt hàng lại và mức tồn mục tiêu | s và S |
| Vị thế tồn | IP của cửa sổ, liệt kê thành phần để Chủ quán thấy đơn nào được tính, đơn nào không |
| Ngày dự kiến hết hàng và ngày rủi ro | Theo mục 6.6 |
| Ngày phải đặt chậm nhất | Theo mục 6.6; ghi Đặt ngay nếu đã qua |
| Lượng đề xuất | Q 0 theo đơn vị chuẩn, số gói n, phần làm tròn Δ, giới hạn nào đã ràng buộc |
| Hành động | Mua, Mua bổ sung, Thúc giao, Không cần mua |
| Đơn liên quan | Các đơn đã được tính vào vị thế tồn hoặc bị loại ra |
| Lý do | Một đến hai câu tự sinh từ số liệu |
| Giai đoạn dữ liệu và phương pháp | Ước tính ban đầu, Thống kê bước đầu hoặc Mô hình; M0, M1 hoặc M2 |
| Thời điểm cập nhật | Thời điểm tính và mã phiên bản dữ liệu |

Mẫu câu lý do, ví dụ với sữa tươi ở mục 10: Tồn có thể dùng 3.900 ml, đủ tới khoảng giữa ngày thứ Bảy. Lô 2.000 ml đã đặt về thứ Hai, sau ngày dự kiến hết nên không được tính. Cần đặt trong hôm nay 7 hộp để hàng về trước thứ Bảy.

### 9.2. Màn hình và thao tác

Màn hình tổng hợp liệt kê nguyên liệu theo thứ tự ngày phải đặt, nhóm Đặt ngay lên đầu, kế đến Đặt trong 2 ngày, cuối cùng là Đủ hàng. Màn hình chi tiết của một nguyên liệu có biểu đồ dòng tồn dự kiến theo ngày với đường mức an toàn, các lô đang về đánh dấu trên trục thời gian, và bảng dự báo tuần, tháng.

Chủ quán có bốn thao tác, đều ghi người và thời điểm:

1. **Chấp nhận** tạo đơn ở trạng thái Nháp với số gói đề xuất.
2. **Sửa rồi chấp nhận** lưu cả số đề xuất và số cuối cùng, bắt buộc ghi chú khi hai số khác nhau như BRU-24 và cơ chế hiện có.
3. **Bỏ qua** kèm lý do; đề xuất vẫn được lưu để đánh giá về sau.
4. **Đã báo nhà cung cấp** chuyển đơn Nháp sang Đã đặt, có thể sửa ngày giao dự kiến theo xác nhận của nhà cung cấp.

Hệ thống không tự gửi đơn cho nhà cung cấp. Có thể có nút sao chép nội dung đơn để Chủ quán tự dán vào tin nhắn.

### 9.3. Kênh cảnh báo

Cảnh báo Cần đặt hàng hiện có được giữ và đổi điều kiện sang ngày phải đặt: cảnh báo bật khi ngày phải đặt là hôm nay hoặc đã qua. Danh sách cần đặt được gom vào màn hình chốt ngày để Chủ quán xem một lần vào buổi tối, còn cảnh báo tức thời trong ngày chỉ dành cho trường hợp giám sát liên tục phát hiện rủi ro trước lần kiểm tra kế tiếp.

## 10. Ví dụ tính hoàn chỉnh

Mọi số liệu trong mục này là số minh họa để kiểm tra logic, không phải số liệu thật của quán. Đơn vị thống nhất là ml cho sữa tươi và g cho cà phê bột.

### 10.1. Sữa tươi, nhóm A

**Tham số.** Quy cách hộp 1.000 ml, MOQ 1 hộp, hạn dùng 7 ngày từ ngày nhận, sức chứa tủ mát dành cho sữa 20.000 ml, nguyên liệu trọng yếu nên CSL 95% và k bằng 1,645. R bằng 1, T bằng 2, ℓ bằng 1.

**Thời điểm tính.** Tối thứ Năm 15/10/2026 lúc 22 giờ, sau khi chốt ngày, nên f 0 bằng 0.

**Tồn và đơn đặt.** Tồn vật lý 3.900 ml, tồn đang giữ 0 vì quán đã đóng, tồn có thể dùng 3.900 ml, không có phiếu dự phòng chưa nhập bù nên C bằng 0. Có một đơn Đã đặt 2.000 ml giao dự kiến thứ Hai 19/10.

**Dự báo.** Nhu cầu kỳ vọng đã gồm tiêu hao bán hàng cộng tỷ lệ hủy sau pha chế 1% và hao hụt vận hành 2%; ví dụ thứ Sáu là khoảng 2.524 ml tiêu hao bán hàng nhân 1,03.

| Ngày | T6 16/10 | T7 17/10 | CN 18/10 | T2 19/10 | T3 20/10 | T4 21/10 | T5 22/10 | Tổng 7 ngày |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| d(t), ml | 2.600 | 3.300 | 3.400 | 2.300 | 2.300 | 2.350 | 2.400 | 18.650 |

Sai số cửa sổ đo bằng đánh giá gốc trượt: σ 1 bằng 420 ml, σ 2 bằng 700 ml, σ 3 bằng 950 ml. Nếu dùng quy tắc căn bậc hai, σ 2 và σ 3 chỉ là 594 ml và 727 ml, thấp hơn số đo, đúng hiện tượng Graves 1999 mô tả.

**Bước 1. Cửa sổ và các mức.**

| Đại lượng | Cửa sổ | Tính | Kết quả |
| --- | --- | --- | --- |
| μ(W s) | T6, T7, bằng R cộng ℓ bằng 2 ngày | 2.600 + 3.300 | 5.900 ml |
| SS(W s) |  | 1,645 × 700 | 1.152 ml |
| s |  | 5.900 + 1.152 | 7.052 ml |
| μ(W S) | T6, T7, CN, bằng T cộng ℓ bằng 3 ngày | 2.600 + 3.300 + 3.400 | 9.300 ml |
| SS(W S) |  | 1,645 × 950 | 1.563 ml |
| S |  | 9.300 + 1.563 | 10.863 ml |

**Bước 2. Vị thế tồn.** Lô 2.000 ml về thứ Hai, nằm ngoài cả hai cửa sổ, nên không được tính. IP(W s) bằng IP(W S) bằng 3.900 ml. Vì 3.900 nhỏ hơn 7.052, cần đặt.

**Bước 3. Dòng tồn dự kiến nếu không đặt.**

| Cuối ngày | T6 | T7 | CN | T2 |
| --- | --- | --- | --- | --- |
| I(t), ml | 1.300 | −2.000 | −5.400 | −5.700 |
| kσ từ nay tới t, ml | 691 | 1.152 | 1.563 |  |

Cuối thứ Sáu còn 1.300 ml, cao hơn 691 ml. Cuối thứ Bảy âm. Vậy ngày rủi ro và ngày dự kiến hết hàng đều là thứ Bảy 17/10; theo nhu cầu kỳ vọng, sữa hết sau khoảng 40% lượng bán của thứ Bảy. Ngày phải đặt chậm nhất là thứ Bảy lùi ℓ cộng 1 ngày, tức thứ Năm 15/10, chính là hôm nay.

**Bước 4. Số lượng.**

| Bước | Tính | Kết quả |
| --- | --- | --- |
| Q 0 | 10.863 − 3.900 | 6.963 ml |
| Giới hạn hạn dùng | Lô dùng được từ thứ Sáu, hạn tới hết thứ Năm 22/10; nhu cầu 7 ngày 18.650 trừ tồn cũ 3.900 dùng trước | 14.750 ml, không ràng buộc |
| Giới hạn sức chứa | 20.000 − 3.900 | 16.100 ml, không ràng buộc |
| Số hộp | 6.963 chia 1.000, làm tròn lên | 7 hộp |
| Phần làm tròn Δ | 7.000 − 6.963 | 37 ml |

Lô 2.000 ml của thứ Hai dùng sau lô mới theo thứ tự nhập, hạn tới Chủ nhật 25/10, cũng dùng hết trước hạn nên không cần đổi.

**Bước 5. Dòng tồn sau khi đặt,** giả định xấu là 7 hộp về cuối ngày thứ Sáu:

| Cuối ngày | T6 | T7 | CN | T2 |
| --- | --- | --- | --- | --- |
| I(t), ml | 8.300 | 5.000 | 1.600 | 1.300 |

Thứ Sáu vẫn đủ nhờ 3.900 ml tồn cũ. Lần kiểm tra tối thứ Bảy sẽ tính lại với lô thứ Hai nằm trong cửa sổ mới.

**Kết quả hiển thị.** Mua 7 hộp sữa tươi, đặt trong hôm nay. Lý do: tồn hiện có hết vào thứ Bảy, lô đã đặt về thứ Hai là quá muộn.

**So sánh với cách tính sai.**

| Cách tính | Kết luận | Hậu quả |
| --- | --- | --- |
| Chỉ bảo vệ thời gian giao 1 ngày, bỏ qua chu kỳ kiểm tra: s bằng 2.600 + 691 bằng 3.291 | Với 3.900 ml, không cần đặt | Tối thứ Sáu mới đặt, hàng có thể về cuối thứ Bảy; hết sữa phần lớn ngày thứ Bảy |
| Tính mọi hàng đang về bất kể ngày về: IP bằng 5.900 | Mua 10.863 − 5.900 bằng 4.963 ml, tức 5 hộp | Cuối Chủ nhật âm 400 ml, hết sữa tối Chủ nhật trước khi lô thứ Hai về |
| Dùng phân vị 95% của tổng 3 ngày, giả sử 10.950 ml, rồi cộng thêm 1.563 | S bằng 12.513 | Tính tồn an toàn hai lần; đúng phải là S bằng 10.950 và SS hiển thị bằng 1.650 |

**Dự báo theo tuần.** Tuần 19/10 đến 25/10, nếu hồ sơ ngày giữ như bảng trên, là khoảng 18.650 ml, tức khoảng 19 hộp, phù hợp với mức 16 đến 25 hộp mỗi tuần trong ước tính minh họa của Chủ quán ở mục 4.4.

### 10.2. Cà phê bột, nhóm B

**Tham số.** Túi 1.000 g, MOQ 1 túi, hạn dùng 90 ngày, trọng yếu nên k bằng 1,645, kiểm tra tối Chủ nhật với R bằng 7 và ℓ bằng 1, nên cửa sổ là 8 ngày từ thứ Hai tuần này tới thứ Hai tuần sau.

| Đại lượng | Tính | Kết quả |
| --- | --- | --- |
| μ của 8 ngày | Tổng dự báo từng ngày | 16.000 g |
| σ 8 đo được | Đánh giá gốc trượt; quy tắc căn bậc hai với σ 1 bằng 600 chỉ cho 1.697 | 2.100 g |
| SS | 1,645 × 2.100 | 3.455 g |
| S | 16.000 + 3.455 | 19.455 g |
| IP | Tồn có thể dùng 6.800, không có đơn đang về | 6.800 g |
| Q 0 | 19.455 − 6.800 | 12.655 g |
| Số túi và Δ | Làm tròn lên | 13 túi, Δ bằng 345 g |
| Giới hạn hạn dùng | Nhu cầu 90 ngày khoảng 180.000 g | Không ràng buộc |

Nếu giữa tuần có một đơn đặt lớn ngoài dự kiến làm ngày rủi ro rơi vào trước thứ Hai tuần sau, giám sát liên tục sinh đề xuất Mua gấp với cùng công thức, không chờ tối Chủ nhật.

## 11. Tái sử dụng và bổ sung

### 11.1. Giữ nguyên hoặc tái sử dụng

| Thành phần hiện có | Vai trò trong thiết kế mới |
| --- | --- |
| Tồn vật lý, tồn đang giữ, sổ biến động và các hàm giữ, nhả, tiêu hao | Giữ nguyên; là nguồn của P, G, A |
| Phiên bản định mức và hàm tìm định mức hiệu lực tại một thời điểm | Dùng để dựng chuỗi theo định mức của ngày được dự báo |
| Lượng dùng chụp trên dòng đơn | Dùng để đối soát với sổ biến động |
| Trạng thái ngày đóng cửa, chưa chốt, đủ điều kiện | Giữ, bổ sung cờ theo nguyên liệu |
| Mô hình Poisson Bayes theo món, mô phỏng đường | Giữ cho Hướng B và cho sắp ca |
| Hàm chuyển nhận định chuyên gia sang tiên nghiệm | Mở rộng cho tiên nghiệm lượng mua theo tuần |
| Khung đánh giá gốc trượt và so với phương pháp cơ sở | Mở rộng sang sai số của tổng cửa sổ theo nguyên liệu |
| Tổng nhu cầu theo đúng từng ngày và phần còn lại hôm nay theo hồ sơ giờ | Giữ |
| Hàm làm tròn theo quy cách | Giữ, thêm MOQ và hiển thị Δ |
| Cơ chế chạy một lần theo khóa thao tác | Giữ cho xác nhận đề xuất |
| Đồng bộ cảnh báo không trùng và tác vụ định kỳ | Giữ, đổi khóa cảnh báo theo đợt rủi ro |
| Bản ghi đề xuất với số đề xuất, số cuối cùng, người quyết định, ghi chú | Giữ, thêm liên kết tới bản tính toán |
| Tham số hệ số chiết khấu, số ngày lịch sử tối thiểu 56, giờ mở và đóng cửa | Giữ |

### 11.2. Bổ sung hoặc sửa

| Hạng mục | Nội dung | Loại |
| --- | --- | --- |
| Trường mới của nguyên liệu | Nhóm chính sách, CSL, R, T, ngày kiểm tra trong tuần, MOQ theo gói, ℓ | Mới, có di trú dữ liệu |
| Trạng thái đơn đặt hàng | Thêm Nháp và Đã hủy, ngày chuyển sang Đã đặt, cảnh báo nhận vượt | Sửa |
| Ngày hết hạn trên dòng phiếu nhập | Tùy chọn, chuẩn bị cho theo dõi lô về sau | Mới |
| Chuỗi tiêu hao nguyên liệu theo ngày | Bảng lưu sẵn gồm U b, U h, hao hụt theo nhóm, cờ ngày | Mới |
| Phương pháp M1 và M2 cho chuỗi nguyên liệu | Trung bình theo thứ; mô hình tuyến tính động Bayes với mức và hệ số theo thứ | Mới |
| Thống kê sai số cửa sổ | σ h, độ chệch, độ phủ cho h từ 1 đến 10 theo nguyên liệu và phương pháp | Mới |
| Bộ tính chính sách | Cửa sổ, IP, SS, s, S, dòng tồn, ngày rủi ro, ngày phải đặt, số lượng, hành động | Mới, thay phần tính đề xuất hiện tại |
| Bảng kế hoạch nguyên liệu | Kết quả mỗi lần tính, khóa duy nhất theo mục 8.4 | Mới |
| Giám sát sau biến động | Gọi bộ tính cho một nguyên liệu sau khi giao dịch ghi tồn hoàn tất | Mới |
| Màn hình kế hoạch mua | Tổng hợp, chi tiết, bốn thao tác của mục 9.2 | Mới, thay màn hình đề xuất hiện tại |
| Lỗi lưu đề xuất lần hai khi gửi lại | Đưa việc lưu vào trong thao tác chạy một lần | Sửa lỗi |
| Cảnh báo đã đóng tay không mở lại | Khóa theo đợt rủi ro | Sửa lỗi |
| Cột nhu cầu 90% lệch một ngày | Một cửa sổ cho mọi cột | Sửa lỗi |
| Cờ ngày thiếu bỏ sót nguyên liệu của tùy chọn | Xét theo từng nguyên liệu | Sửa lỗi |
| Di trú 58 nguyên liệu từ thực đơn thật | Điền quy cách, hạn dùng, nhóm và ước tính tuần cùng Chủ quán | Dữ liệu |

Tồn an toàn nhập tay và cờ Tạm thời hiện có được giữ với vai trò mức sàn và nhãn giai đoạn, không xóa. Các bảng dự báo theo món và bản phát hành dự báo được giữ để không phá truy vết cũ.

## 12. Đánh giá hiệu quả và kế hoạch kiểm chứng

Chất lượng dự báo và chất lượng quyết định tồn kho được đánh giá riêng. Một dự báo tốt vẫn có thể đi kèm quyết định kém nếu sai cửa sổ hoặc bỏ qua lô đang về, và ngược lại.

### 12.1. Chất lượng dự báo

Đo bằng đánh giá gốc trượt trên dữ liệu thật, chỉ trên ngày đủ điều kiện, cho từng nguyên liệu và cho tổng của các cửa sổ được dùng trong quyết định: R cộng ℓ, T cộng ℓ, tuần.

| Chỉ số | Ý nghĩa |
| --- | --- |
| Sai số tuyệt đối trung bình | Độ lớn sai số theo đơn vị chuẩn |
| Sai số tuyệt đối có trọng số trên toàn bộ nguyên liệu | So sánh giữa các nguyên liệu khác đơn vị |
| Độ chệch | Dự báo có thiên cao hay thấp hệ thống không |
| Căn trung bình bình phương sai số | Chính là σ h dùng cho tồn an toàn |
| CRPS | Chấm toàn bộ phân phối dự báo, theo Gneiting và Raftery 2007 |
| Độ phủ của khoảng 80% và phân vị CSL | Khoảng dự báo có trung thực không |

Phương pháp M2 chỉ được dùng cho một nguyên liệu khi thắng M1 theo quy tắc ở mục 4.4. Nếu không thắng, hệ thống dùng M1, đây là kết quả chấp nhận được và không phải lỗi.

### 12.2. Chất lượng quyết định tồn kho

| Chỉ số | Cách đo từ dữ liệu hiện có | Hướng tốt |
| --- | --- | --- |
| Số lần hết hàng | Số trường hợp thiếu nguyên liệu theo nguyên liệu và tháng | Giảm |
| Thời gian hết hàng | Số giờ mở cửa từ báo Đã hết tới phiếu nhập kế tiếp | Giảm |
| Tỷ lệ đáp ứng ước tính | 1 trừ nhu cầu dự báo trong giờ hết hàng chia tổng nhu cầu; là ước tính vì nhu cầu mất không được ghi | Tăng |
| Tỷ lệ chu kỳ không hết hàng | So với CSL đã cài | Gần CSL |
| Tồn dư | Số ngày đủ dùng trung bình lúc nhận hàng, so với T cộng SS | Không vượt xa mục tiêu |
| Hàng hết hạn | Lượng hao hụt lý do hết hạn và hư hỏng theo nguyên liệu | Giảm |
| Mua gấp | Phiếu nhập không xuất phát từ đề xuất và nhập trong ngày hoặc ngày kế tiếp sau một báo Sắp hết hoặc Đã hết | Giảm |
| Thúc giao | Số đề xuất Thúc giao và đơn giao chậm | Giảm |
| Mức chấp nhận đề xuất | Tỷ lệ chấp nhận, tỷ lệ sửa và độ lệch giữa số đề xuất với số cuối cùng | Đọc cùng ghi chú của Chủ quán |

### 12.3. Mô phỏng lại trên lịch sử

Trước khi dùng thật, chính sách được chạy lại từng ngày trên lịch sử: mỗi tối tính đề xuất chỉ với dữ liệu tới tối đó, giả định đơn về theo ℓ, trừ nhu cầu thực tế, rồi đếm số ngày hết hàng, tồn trung bình và lượng vượt hạn dùng. Kết quả được so với cách mua thực tế của quán trong cùng giai đoạn. Giới hạn: ngày hết hàng trong lịch sử không cho biết nhu cầu thật, nên mô phỏng dùng nhu cầu dự báo cho những ngày đó và ghi rõ.

Bộ dữ liệu mô phỏng 6 tháng chỉ dùng để kiểm thử mã và kiểm tra các kịch bản dưới đây, không dùng để kết luận về độ chính xác.

### 12.4. Kịch bản kiểm thử

| Kịch bản | Thiết lập | Kết quả mong đợi |
| --- | --- | --- |
| Tăng cuối tuần | Thứ Bảy, Chủ nhật gấp 1,4 lần ngày thường | Kiểm tra tối thứ Năm kích hoạt đặt dù tồn đủ cho một ngày thường; số lượng tính theo tổng từng ngày |
| Giảm mùa hè hoặc nghỉ hè của sinh viên | Mức nhu cầu giảm 25% trong 3 tuần | M1 và M2 bắt kịp; lượng đề xuất giảm; độ chệch được cảnh báo nếu kéo dài |
| Nhà cung cấp giao trễ | Đơn quá ngày giao | Đơn chuyển Giao chậm, bị loại khỏi hàng đang về, xuất hiện Thúc giao hoặc Mua bổ sung |
| Giao một phần | Đặt 10 hộp, nhận 6 | Chỉ 4 hộp còn lại được tính |
| Đã có lô đang về | Lô về trước ngày rủi ro, và trường hợp lô về sau ngày rủi ro như mục 10.1 | Trường hợp đầu không đề xuất; trường hợp sau đề xuất mua và không bị lô đó che |
| Nguyên liệu gần hết hạn sử dụng | Hạn dùng 3 ngày, Q 0 lớn hơn lượng dùng được | Lượng bị chặn bởi Q hd, có ghi chú mua sớm hơn hoặc cảnh báo hết hạn theo mục 6.7 |
| Đổi định mức | Phiên bản mới giảm 20% sữa cho một món, hiệu lực từ thứ Hai | Dự báo từ thứ Hai giảm tương ứng ngay; dự báo trước thứ Hai không đổi |
| Thiếu lịch sử | Nguyên liệu mới, 5 ngày dữ liệu | Dùng M0, nhãn Tạm thời, không hiển thị khoảng hẹp |
| Ngày hết hàng trong lịch sử | Một ngày có trường hợp thiếu cho nguyên liệu của tùy chọn | Ngày bị loại khỏi học và khỏi đo sai số |
| Hủy sau pha chế | 5 ly hủy sau khi pha | Chuỗi bán không gồm 5 ly; tỷ lệ hủy tăng; phép đối soát với sổ biến động khớp |
| Chạy lại cùng đề xuất | Chạy tác vụ định kỳ hai lần liên tiếp; gửi lại biểu mẫu xác nhận | Không có bản kế hoạch, cảnh báo hay đơn thứ hai; không lỗi |
| Cảnh báo đã đóng tay | Đóng cảnh báo, nhập hàng, rồi tồn lại xuống | Có cảnh báo mới cho đợt mới |
| Phân vị và tồn an toàn | Bật cách phân vị | s bằng phân vị, SS bằng phân vị trừ trung bình, không cộng kσ |
| Không gửi nhà cung cấp | Mọi luồng | Không có lời gọi ra ngoài; đơn chỉ được tạo khi Chủ quán xác nhận |

### 12.5. Đưa vào sử dụng

Thiết kế đề xuất chạy song song 4 tuần: hệ thống vẫn tính và hiển thị, Chủ quán mua theo cách cũ và ghi khi không đồng ý với đề xuất. Sau đó so các chỉ số ở mục 12.2 giữa cách mua thực tế và đề xuất của hệ thống trước khi Chủ quán quyết định dùng đề xuất làm căn cứ chính.

## 13. Giả định, giới hạn và điểm cần Chủ quán xác nhận

### 13.1. Giả định đang dùng

Các giả định sau được đưa vào dưới dạng tham số cấu hình, có thể đổi mà không sửa mã.

| Mã | Giả định | Giá trị mặc định | Ảnh hưởng nếu sai |
| --- | --- | --- | --- |
| GD1 | Hàng đặt tối nay có thể về bất kỳ lúc nào ngày mai | ℓ bằng 1 | Nếu hàng luôn về trước giờ mở cửa, nhóm A đang giữ dư khoảng một ngày nhu cầu |
| GD2 | Nhóm A kiểm tra mỗi tối, mua cách nhau khoảng 2 ngày; nhóm B kiểm tra tối Chủ nhật | R bằng 1, T bằng 2; R bằng 7 | Nếu quán mua theo lịch giao cố định, cần đặt R và T theo lịch đó |
| GD3 | Mức phục vụ chu kỳ | 95% trọng yếu, 90% còn lại | Tăng lên 98% làm tồn an toàn tăng khoảng 25% so với 95% |
| GD4 | Sai số cộng dồn xấp xỉ phân phối chuẩn | Áp dụng khi dùng trung bình cộng kσ | Nguyên liệu dùng ít, lệch phải mạnh sẽ bị thiếu tồn an toàn; kiểm tra bằng độ phủ ở mục 12.1 |
| GD5 | Nhu cầu thiếu là nhu cầu mất, xấp xỉ bằng công thức ghi nợ | Áp dụng | Sai lệch nhỏ khi CSL cao |
| GD6 | Dùng hàng cũ trước | Áp dụng cho giới hạn hạn dùng | Nếu nhân viên dùng hộp mới trước, lượng hết hạn thực tế cao hơn tính toán |
| GD7 | Hạn dùng tính từ ngày nhận, theo số ngày khai cho nguyên liệu | Áp dụng | Lô có hạn ngắn hơn thường lệ không được nhận biết |
| GD8 | Hư hỏng và hết hạn không phải nhu cầu; pha hỏng và đổ vỡ là nhu cầu | Áp dụng | Nếu một phần hư hỏng là do mở hộp dùng dở, cần chuyển phần đó sang hao hụt vận hành |
| GD9 | Khoảng thấp cao của Chủ quán là khoảng tin cậy 90% | Áp dụng cho M0 | Độ bất định ban đầu quá hẹp hoặc quá rộng |
| GD10 | Ngưỡng chuyển phương pháp, ngưỡng 20% cho món mới và ngày ảnh hưởng gián tiếp | 5% trên 4 tuần; 20% | Chỉ làm thay đổi thời điểm chuyển, không đổi công thức |
| GD11 | Các đơn mua nguyên liệu khác nhau độc lập | Áp dụng | Chưa tối ưu gộp đơn theo nhà cung cấp hay phí giao chung |

### 13.2. Giới hạn

1. **Không theo dõi lô và hạn dùng từng lô.** Giới hạn hạn dùng dựa trên GD6 và GD7 nên chỉ là ước tính. Hệ thống không biết trong tủ có bao nhiêu hộp sắp hết hạn. Trường ngày hết hạn tùy chọn trên phiếu nhập là bước chuẩn bị, không phải quản lý lô.
2. **Không ước tính nhu cầu bị mất.** Ngày hết hàng bị loại khỏi dữ liệu học. Nếu hết hàng thường xuyên, dữ liệu còn lại ít và có thể thiên về các ngày vắng khách.
3. **Không có dữ liệu chi phí.** Không tối ưu lượng đặt kinh tế, không chọn CSL theo tỷ số tới hạn cho tới khi có giá vốn và lãi gộp theo nguyên liệu.
4. **Không mô hình hóa thay thế.** Khi hết một nguyên liệu, khách đổi sang món khác làm tăng tiêu hao nguyên liệu khác; hiệu ứng này không được tách riêng.
5. **Dữ liệu thật còn ngắn.** Cho tới khi có 56 ngày đủ điều kiện, phần lớn nguyên liệu chạy ở giai đoạn Ước tính ban đầu hoặc Thống kê bước đầu; con số có nhãn tương ứng và không nên được hiểu là đã kiểm chứng.
6. **Chưa chạy thử.** Các lỗi nêu ở mục 2.4 được phát hiện khi đọc mã, chưa tái hiện bằng kiểm thử; việc tái hiện là bước đầu tiên khi triển khai.

### 13.3. Điểm cần Chủ quán xác nhận

Chỉ ba điểm sau làm thay đổi quyết định kinh doanh. Trong lúc chờ, thiết kế dùng giá trị mặc định đã nêu.

1. **Giờ hàng về.** Đã xác nhận ngày 13/10/2026: Chủ quán cho biết hàng đặt trong ngày có khi giao ngay, chậm nhất ngày hôm sau, giờ giao không cố định và không chắc trước giờ mở cửa. Thiết kế giữ ℓ bằng 1 như GD1.
2. **Cách mua.** Nhà cung cấp giao theo yêu cầu, không theo lịch cố định. Thiết kế giữ bảng nhóm A và B ở mục 7; Chủ quán có thể đổi nhóm từng nguyên liệu khi khai báo.
3. **Mức phục vụ.** Chưa chốt. 95% và 90% là mức đề xuất để bắt đầu, không tính từ dữ liệu của quán. Với sữa tươi mua khoảng 15 lần mỗi tháng, 95% tương ứng trung bình khoảng 1 lần mỗi tháng có nguy cơ hụt trước khi hàng về, 90% khoảng 1 đến 2 lần. Nếu Chủ quán cung cấp giá vốn mỗi gói và lãi mất khi không bán được một ly, CSL của từng nguyên liệu được chọn theo tỷ số tới hạn ở mục 6.4.

Các thông tin còn lại như quy cách, hạn dùng, sức chứa và ước tính lượng mua mỗi tuần của 58 nguyên liệu là dữ liệu cần nhập khi triển khai, không phải quyết định thiết kế.

## 14. Tài liệu tham khảo

Các nguồn từ 1 đến 6 đã được mở và đối chiếu khi viết tài liệu này. Các nguồn từ 7 đến 12 là giáo trình và bài báo chuẩn được trích theo thông tin xuất bản, chưa mở toàn văn trong lần viết này; các phát biểu dựa trên chúng nên được đối chiếu lại với bản gốc trước khi đưa vào báo cáo nộp.

1. Caplice, C. và Sheffi, Y. ESD.260J Logistics Systems, Fall 2006. MIT OpenCourseWare. Đề cương: https://ocw.mit.edu/courses/esd-260j-logistics-systems-fall-2006/pages/syllabus/
2. Caplice, C. ESD.260J, bài giảng 11, chính sách tồn kho với nhu cầu ngẫu nhiên, điểm đặt hàng lại, tồn an toàn, CSL và tỷ lệ đáp ứng. https://ocw.mit.edu/courses/esd-260j-logistics-systems-fall-2006/8b53c45fd26ffff706d815131e8d177e\_lect11.pdf
3. Caplice, C. ESD.260J, bài giảng 12, kiểm tra định kỳ và liên tục, mức tồn mục tiêu theo cửa sổ R cộng L. https://ocw.mit.edu/courses/esd-260j-logistics-systems-fall-2006/bc18dd1b2543535a61f826d00a8c6e42\_lect12.pdf
4. Caplice, C. ESD.260J, bài giảng 14, mô hình một kỳ. https://ocw.mit.edu/courses/esd-260j-logistics-systems-fall-2006/755a26f6aaebae8928294146a2484cd4\_lect14.pdf
5. Graves, S. C. và Simchi-Levi, D. 15.763J Manufacturing System and Supply Chain Design, Spring 2005. MIT OpenCourseWare. https://ocw.mit.edu/courses/15-763j-manufacturing-system-and-supply-chain-design-spring-2005
6. Graves, S. C. 1999. A Single-Item Inventory Model for a Nonstationary Demand Process. Manufacturing & Service Operations Management 1, số 1, trang 50 đến 61. DOI 10.1287/msom.1.1.50. Bản working paper MIT: https://dspace.mit.edu/bitstream/1721.1/2645/1/SWP-3944-36987303.pdf
7. Graves, S. C. và Willems, S. P. 2000. Optimizing Strategic Safety Stock Placement in Supply Chains. Manufacturing & Service Operations Management 2, số 1, trang 68 đến 83. https://pubsonline.informs.org/doi/10.1287/msom.2.1.68.23267
8. Silver, E. A., Pyke, D. F. và Peterson, R. 1998. Inventory Management and Production Planning and Scheduling, ấn bản 3. Wiley.
9. West, M. và Harrison, J. 1997. Bayesian Forecasting and Dynamic Models, ấn bản 2. Springer.
10. West, M., Harrison, P. J. và Migon, H. S. 1985. Dynamic Generalized Linear Models and Bayesian Forecasting. Journal of the American Statistical Association 80, số 389, trang 73 đến 83.
11. Gneiting, T. và Raftery, A. E. 2007. Strictly Proper Scoring Rules, Prediction, and Estimation. Journal of the American Statistical Association 102, số 477, trang 359 đến 378.
12. Hyndman, R. J. và Athanasopoulos, G. 2021. Forecasting: Principles and Practice, ấn bản 3. OTexts. https://otexts.com/fpp3/

Tài liệu nội bộ của dự án được đối chiếu: báo cáo yêu cầu nghiệp vụ với BRU-18 đến BRU-26, BRU-37, FR-20, FR-28 đến FR-31, FR-54 và AC-64 đến AC-71; DOI\_CHIEU\_YEU\_CAU; KE\_HOACH; docs/DU\_BAO.md; KET\_QUA\_THU\_DU\_BAO; Khung lý thuyết dự báo nhu cầu LAM Coffee; mã nguồn D:\\QTDA nhánh main bản 7972893.
