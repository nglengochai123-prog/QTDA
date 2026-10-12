# Dự báo nhu cầu và hỗ trợ đặt hàng

Cập nhật 12/10/2026. Làm theo tệp "Khung lý thuyết dự báo nhu cầu bằng học máy xác suất cho LAM Coffee" của Hai và các quy tắc BRU-21, BRU-22, BRU-24 của BRD. Mã nguồn ở `apps/forecast/`.

## 1. Cách tính

| Phần | Cách làm | Căn cứ |
|---|---|---|
| Đơn vị dự báo | Số ly của một món và một kích cỡ trong một ngày | Khung 2.2 |
| Ngày được học | Ngày đã qua, có ca, mọi ca đã kết và có báo cáo cuối ca | Khung 2.2 |
| Ngày không học | Ngày không có ca (đóng cửa), ngày chưa chốt dữ liệu; ngày có trường hợp thiếu nguyên liệu nằm trong định mức của món bị gắn cờ và không học cho món đó. Không ngày nào trong số này bị coi là bán 0 ly | Khung 2.2 |
| Ngày bán của phiếu dự phòng | Thời điểm bán ghi trên phiếu, không phải lúc nhập bù | Khung 2.2 |
| Mô hình | Số ly ~ Poisson(λ); log λ = mức nền động + hiệu ứng thứ trong tuần (thứ Hai là ngày tham chiếu). Cập nhật tuần tự bằng suy luận Bayes tuyến tính của mô hình tuyến tính tổng quát động; biến đổi trạng thái theo hệ số chiết khấu | Khung 3.1, 3.2; West, Harrison và Migon 1985 |
| Tiên nghiệm | Từ nhận định Chủ quán theo món, kích cỡ, ngày thường và cuối tuần: số ly điển hình, một ngày bán ít và một ngày bán nhiều (hiểu là khoảng 10%–90% số ly của một ngày tương lai). Độ rộng khoảng quyết định sức nặng của nhận định; sức nặng tối đa có giới hạn | Khung 2.1, 4.1 |
| Nhận định dựa trên chính số bán trong hệ thống | Không dùng làm tiên nghiệm độc lập | Khung 6.1 |
| Học lại | Mỗi lần phát hành tính lại từ tiên nghiệm gốc trên toàn bộ ngày đủ điều kiện, nên nhập bù làm đổi ngày cũ không bị cộng hai lần | Khung 3.2 |
| Dự báo | Từng ngày trong chân trời (mặc định 14 ngày, tự kéo dài để đủ thời gian giao cộng chu kỳ đặt hoặc hạn dùng): kỳ vọng và phân vị 10/50/90 | Khung 4.2 |
| Tổng nhiều ngày | Tính trên từng đường mô phỏng (1.000 đường) rồi mới lấy phân vị; không cộng các khoảng từng ngày | Khung 4.2 |
| Lưu phát hành | Mỗi lần phát hành giữ thời điểm, phiên bản mô hình, mã băm dữ liệu và tham số, không sửa | Khung 6.1 |
| Nhiễu quan sát | log λ_t = F'θ_t + ε_t: thêm biến động riêng từng ngày khi số bán phân tán hơn Poisson có điều kiện; mức nhiễu chọn qua đánh giá (0; 0,02; 0,05; 0,10) | Khung 3.1; Berry và West 2020 |
| Kiểm tra độ phân tán | Trung bình (y − μ)²/phương sai dự báo của các dự báo 1 ngày; gần 1 là mô tả đúng độ biến động, báo trên trang Đánh giá | Khung 3.1 |
| Chọn cấu hình | Mỗi món thử 3 hệ số thích nghi × 4 mức nhiễu trên nửa đầu các mốc; cấu hình tốt nhất chỉ được dùng khi phát hành sau khi Chủ quán bấm "Dùng mô hình" (lưu kèm bằng chứng) | Khung 3.1, 6.1 |
| Độ nhạy nhận định | CRPS khi nhân sức nặng nhận định ×0,5 và ×2, báo trên trang Đánh giá | Khung 2.1 |
| Kiểm tra nhận định | Trang chi tiết món sinh 2.000 tuần bán theo nhận định để Chủ quán đối chiếu tính hợp lý | Khung 6.1 |
| Đối chiếu phát hành | So các dự báo đã lưu với số bán thực theo thời hạn, đếm riêng điểm có nhập bù sau thời điểm phát hành | Khung 6.1 |
| Lịch sử bán từ tệp | Dự báo › Lịch sử bán: nhập CSV hoặc Excel .xlsx (ngày, món, kích cỡ, số ly, trạng thái đóng cửa hoặc thiếu hàng; với Excel tự chọn sheet có đủ các cột này); lịch sử thật và dữ liệu mô phỏng lưu riêng, dữ liệu mô phỏng không dùng cho dự báo thật | Khung 6.1 |
| Quy đổi nguyên liệu | Số ly × định mức đang áp dụng theo kích cỡ; tùy chọn theo tỷ lệ chọn rút từ hậu nghiệm Beta(1 + có chọn, 1 + không chọn) của 56 ngày gần nhất cho mỗi đường mô phỏng. Hao hụt và hủy sau pha không tính vào nhu cầu khách | Khung 6.2 |

## 2. Cách tính dùng cho đặt hàng

Mặc định mỗi món dùng **Ước tính ban đầu** (nhận định Chủ quán), đúng AC-64. Chủ quán chuyển sang **Mô hình Bayes động** ở trang Đánh giá dự báo khi kết quả đánh giá ngoài mẫu cho thấy mô hình tốt hơn (AC-65, khung 6.1); quyết định lưu kèm kết quả đánh giá lúc đó. Món chưa có nhận định thì dùng mô hình bắt đầu từ tiên nghiệm rất rộng và trang dự báo ghi rõ hạn chế này.

## 3. Cần đặt hàng và đề xuất số lượng

- **Tồn dự kiến khi hàng về** = tồn có thể dùng + các lô đã đặt về kịp trước khi hàng của lần đặt mới đến − nhu cầu ước tính (kỳ vọng) trong thời gian giao. Lô giao chậm không tính. Nhu cầu hôm nay chỉ tính phần còn lại theo tỷ lệ bán từng giờ trong 8 tuần gần nhất. Tồn có thể dùng đã trừ nguyên liệu giữ cho món đã gửi pha chế, nên nhu cầu của các đơn đó không bị tính lại (khung 6.2).
- **Cần đặt** khi tồn dự kiến khi hàng về thấp hơn tồn an toàn (BRU-22). Cảnh báo "Cần đặt hàng" mức Quan trọng giao Chủ quán, hạn là ngày đặt muộn nhất, tự đóng khi đã ghi lần đặt đủ (AC-66, AC-67).
- **Đề xuất** = nhu cầu từ ngày hàng về đến lần nhận kế tiếp theo chu kỳ đặt + tồn an toàn − tồn dự kiến khi hàng về, làm tròn lên theo quy cách; không vượt nhu cầu trong thời hạn sử dụng + tồn an toàn − tồn dự kiến; không vượt sức chứa (BRU-24, AC-70). Trang hiện từng thành phần.
- Chủ quán sửa được số lượng; khác đề xuất thì phải ghi lý do. Số đề xuất, số thực đặt và lần đặt đều được lưu (AC-71, NFR-22).
- Cột "90%" của nhu cầu trong thời gian giao chỉ để tham khảo, quyết định vẫn theo kỳ vọng và tồn an toàn như BRU-22.

## 4. Đánh giá chất lượng

Trang **Dự báo › Đánh giá dự báo**:
- Đánh giá cuốn chiếu: tại mỗi mốc chỉ dùng dữ liệu trước mốc, dự báo 1, 3 và 7 ngày sau.
- Ba cách trên cùng các ngày đích: Ước tính ban đầu, Cùng thứ tuần trước, Mô hình Bayes động.
- Hệ số thích nghi của mô hình được chọn trong {0,90; 0,95; 0,98} trên nửa đầu các mốc; số liệu báo cáo chỉ tính trên nửa sau.
- Chỉ tiêu: CRPS của cả phân phối, tỷ lệ số bán nằm trong khoảng 10%–90%, độ rộng khoảng, MAE của trung vị, sai số có dấu. Không dùng phần trăm sai số khi số bán bằng 0.
- Báo cáo riêng từng món và từng thời hạn; không đặt một tỷ lệ chính xác chung.
- Có thêm bảng đối chiếu hằng tuần nhu cầu nguyên liệu với tiêu hao thực tế (FR-28).
- Dưới 56 ngày dữ liệu (8 tuần) trang ghi rõ kết quả chỉ để kiểm tra phần mềm.

## 5. Tham số (Kiểm soát › Tham số)

| Tham số | Mặc định | Căn cứ |
|---|---|---|
| Độ dài chân trời dự báo | 14 ngày | Khung 4.2 |
| Hệ số chiết khấu mức nền | 95% | **Giả định**, chọn lại qua đánh giá |
| Hệ số chiết khấu hiệu ứng thứ | 99% | **Giả định**, chọn lại qua đánh giá |
| Sức nặng tối đa của nhận định | 7 ngày tương đương | **Giả định**, cần kiểm tra độ nhạy |
| Số ngày dữ liệu bắt đầu đánh giá thử | 56 ngày | Khung 5.3 |
| Số đường mô phỏng | 1.000 | Kỹ thuật |

## 6. Cách dùng

1. Dự báo › Nhận định Chủ quán: nhập cho mỗi món đang bán, ngày thường và cuối tuần, kèm căn cứ.
2. Dự báo › Dự báo nhu cầu: bấm Phát hành lại (tác vụ định kỳ cũng tự phát hành mỗi ngày một lần).
3. Kho: khai báo chu kỳ đặt hàng, quy cách, hạn sử dụng, sức chứa, tồn an toàn, nhà cung cấp chính cho từng nguyên liệu (Quản trị › Nguyên vật liệu).
4. Dự báo › Đặt hàng đề xuất: xem nguyên liệu cần đặt, sửa số lượng nếu cần và ghi lần đặt.
5. Sau đủ dữ liệu: Dự báo › Đánh giá dự báo, chọn cách tính cho từng món.

## 7. Giới hạn đã biết

- Chưa ước lượng nhu cầu bị mất khi hết hàng; ngày thiếu hàng chỉ bị loại khỏi phần học (khung 2.2, 6.3).
- Chưa có hiệu ứng ngày lễ, khuyến mãi, mùa vụ năm; cần dữ liệu nhất quán và qua các chu kỳ năm (khung 3.1, 5.3).
- Kết quả hiện mới kiểm trên dữ liệu mô phỏng và bộ dữ liệu mẫu 14 ngày, chỉ xác minh phần mềm, chưa chứng minh độ chính xác tại quán (khung 5.1). Kết quả chạy thử trên dữ liệu giả định 6 tháng của Hai ở `docs/KET_QUA_THU_DU_BAO.md`.
- Chạy bằng thư viện chuẩn Python, không cài thêm gói tính toán.
