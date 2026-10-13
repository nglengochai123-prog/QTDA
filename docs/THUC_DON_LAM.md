# Thực đơn và định mức LAM Coffee

Nguồn: công thức Chủ quán gửi ngày 12/10/2026. Dữ liệu ở `apps/catalog/thuc_don_lam.py`, nhập bằng lệnh `manage.py nhap_thuc_don_lam` (chạy lại không tạo trùng).

## Cần Chủ quán xác nhận

- Trà nhài, oolong, đào, vải, hibiscus đang tính theo ml trà đã pha. Cần tỷ lệ ủ (bao nhiêu gram trà khô ra bao nhiêu ml) để quy ra trà khô như cà phê và nước đường.
- Không có giá bán và kích cỡ: mỗi món tạo một cỡ "Chuẩn" giá 0, trạng thái Đang soạn. Nhập giá rồi mới mở bán.
- Nước lọc và đá không tính vào định mức (phần lớn công thức không ghi đá).
- Quy cách đóng gói, thời gian giao hàng, tồn an toàn của nguyên liệu chưa có: tạm để quy cách 1, giao 1 ngày, tồn an toàn 0 (Tạm thời). Cần sửa ở Quản trị › Nguyên vật liệu trước khi dùng đề xuất đặt hàng.
- **Cà phê sương sáo:** Sương sáo ghi 6-7 viên, tạm tính 6,5 viên.
- **Cà phê dừa:** Công thức không ghi lượng cà phê; chưa tính cà phê cho món này.
- **Sinh tố xoài:** Sữa đặc ghi 30-40 ml tùy xoài, tạm tính 35 ml.
- **Sinh tố trái cây:** Chưa có lượng xoài, bơ, thanh long, đu đủ cho một ly; định mức mới có sữa đặc.
- **Trà xoài:** "70ml nước cốt" tạm hiểu là nước cốt xoài.
- **Trà đào:** "Mứt" và "siro" tạm hiểu là mứt đào, siro đào.
- **Trà mãng cầu:** "50ml cốt" tạm hiểu là cốt mãng cầu.
- **Bơ già:** Bơ tính theo gram (100 g) trong khi sinh tố bơ tính theo trái; cần biết 1 trái bơ được khoảng bao nhiêu gram để gộp thành một nguyên liệu.

## Quy đổi bán thành phẩm

- Cà phê pha: 500 g bột ra 1 lít.
- Nước đường: 1 kg đường + 1 lít nước ra 1,6 lít.
- Foam muối: 100 ml sữa đặc + 200 ml rich + 90 ml sữa tươi + 5 g muối (khoảng 390 ml).
- Foam trứng: như foam muối, thay muối bằng 10 g bột kem trứng.

Kho trừ theo nguyên liệu gốc. Ví dụ 40 ml cà phê = 20 g cà phê bột; 20 ml nước đường = 12,5 g đường.

## Cà phê

| Món | Công thức gốc | Định mức theo nguyên liệu kho (1 ly) |
|---|---|---|
| Cà phê đen | 1 gói đường + 40ml cf | Đường gói 1 gói; Cà phê bột 20 g |
| Cà phê sữa | 20ml sữa đặc + 40ml cf | Sữa đặc 20 ml; Cà phê bột 20 g |
| Cà phê Sài Gòn sữa | 60ml cf + 30ml sữa đặc | Cà phê bột 30 g; Sữa đặc 30 ml |
| Cà phê Sài Gòn đen | 60ml cf + 20ml đường | Cà phê bột 30 g; Đường cát 12,5 g |
| Bạc xỉu | 30ml sữa đặc + 20ml sữa tươi + 10ml rich + 40ml cf | Sữa đặc 30 ml; Sữa tươi 20 ml; Kem béo Rich 10 ml; Cà phê bột 20 g |
| Cà phê kem | 10ml sữa đặc + 40ml cf + 2 viên kem (dừa or socola) | Sữa đặc 10 ml; Cà phê bột 20 g<br>+ Vị kem Dừa: Kem dừa (viên) 2 cái<br>+ Vị kem Socola: Kem socola (viên) 2 cái |
| Cà phê muối / trứng | 40ml cf + 20ml sữa đặc + 40ml Foam muối/trứng | Cà phê bột 20 g; Sữa đặc 20 ml<br>+ Loại foam Muối: Sữa đặc 10,26 ml; Kem béo Rich 20,51 ml; Sữa tươi 9,23 ml; Muối 0,51 g<br>+ Loại foam Trứng: Sữa đặc 10,26 ml; Kem béo Rich 20,51 ml; Sữa tươi 9,23 ml; Bột kem trứng 1,03 g |
| Cà phê sương sáo | 6-7 viên sương sáo đáy ly + 40ml cốt dừa + 20ml sữa đặc + 20ml đường + 20ml sữa tươi + 40ml cf | Sương sáo (viên) 6,5 cái; Nước cốt dừa 40 ml; Sữa đặc 20 ml; Đường cát 12,5 g; Sữa tươi 20 ml; Cà phê bột 20 g |
| Cà phê dừa | 20ml đường + 10ml sữa tươi + 30ml sữa đặc + 10ml rich + 50ml cốt dừa | Đường cát 12,5 g; Sữa tươi 10 ml; Sữa đặc 30 ml; Kem béo Rich 10 ml; Nước cốt dừa 50 ml |

## Cacao và Matcha

| Món | Công thức gốc | Định mức theo nguyên liệu kho (1 ly) |
|---|---|---|
| Cacao | 5g bột cacao + 40ml sữa đặc + 30ml sữa tươi +10ml rich | Bột cacao 5 g; Sữa đặc 40 ml; Sữa tươi 30 ml; Kem béo Rich 10 ml |
| Cacao muối / trứng | 5g bột cacao + 40ml sữa đặc + 30ml sữa tươi +10ml rich + 20ml foam muối/trứng | Bột cacao 5 g; Sữa đặc 40 ml; Sữa tươi 30 ml; Kem béo Rich 10 ml<br>+ Loại foam Muối: Sữa đặc 5,13 ml; Kem béo Rich 10,26 ml; Sữa tươi 4,62 ml; Muối 0,26 g<br>+ Loại foam Trứng: Sữa đặc 5,13 ml; Kem béo Rich 10,26 ml; Sữa tươi 4,62 ml; Bột kem trứng 0,51 g |
| Matcha | 30ml sữa đặc + 50ml sữa tươi + 20ml rich + 5g bột matcha | Sữa đặc 30 ml; Sữa tươi 50 ml; Kem béo Rich 20 ml; Bột matcha 5 g |
| Matcha muối / trứng | 30ml sữa đặc + 50ml sữa tươi + 20ml rich + 5g bột matcha + 20ml foam muối/trứng | Sữa đặc 30 ml; Sữa tươi 50 ml; Kem béo Rich 20 ml; Bột matcha 5 g<br>+ Loại foam Muối: Sữa đặc 5,13 ml; Kem béo Rich 10,26 ml; Sữa tươi 4,62 ml; Muối 0,26 g<br>+ Loại foam Trứng: Sữa đặc 5,13 ml; Kem béo Rich 10,26 ml; Sữa tươi 4,62 ml; Bột kem trứng 0,51 g |

## Nước ép

| Món | Công thức gốc | Định mức theo nguyên liệu kho (1 ly) |
|---|---|---|
| Nước chanh | 1,5 trái chanh + 1 tắc + 100ml nước + 40ml đường + 10ml tắc xí muội + 1 cục xí muội | Chanh 1,5 quả; Tắc 1 quả; Đường cát 25 g; Tắc xí muội 10 ml; Xí muội (cục) 1 cái |
| Nước cam | 3 trái cam + 10ml đường | Cam 3 quả; Đường cát 6,25 g |

## Sinh tố

| Món | Công thức gốc | Định mức theo nguyên liệu kho (1 ly) |
|---|---|---|
| Sinh tố xoài | ½ xoài + 30ml mứt xoài + 30-40ml sữa đặc tuỳ xoài + 50g đá | Xoài 0,5 quả; Mứt xoài 30 ml; Sữa đặc 35 ml |
| Sinh tố bơ | 1,5 trái bơ + 10ml sữa đặc + 10ml đường + 10ml sữa tươi + 50g đá | Bơ 1,5 quả; Sữa đặc 10 ml; Đường cát 6,25 g; Sữa tươi 10 ml |
| Sinh tố trái cây | 30ml sữa đặc + Xoài - bơ - thanh long - Đu đủ | Sữa đặc 30 ml |

## Trà

| Món | Công thức gốc | Định mức theo nguyên liệu kho (1 ly) |
|---|---|---|
| Trà chanh | 100ml nước + 1 gói trà chanh + 1 tắc + ½ trái chanh + 30ml đường + 20ml siro chanh | Gói trà chanh 1 gói; Tắc 1 quả; Chanh 0,5 quả; Đường cát 18,75 g; Siro chanh 20 ml |
| Trà sen | 150ml trà olong + 30ml đường + 20ml foam muối + 30g hạt sen | Trà oolong (đã pha) 150 ml; Đường cát 18,75 g; Sữa đặc 5,13 ml; Kem béo Rich 10,26 ml; Sữa tươi 4,62 ml; Muối 0,26 g; Hạt sen 30 g |
| Trà xoài | 100ml trà nhài + 70ml nước cốt + 1 tắc + 10ml đường + 15g cốt xoài chanh dây | Trà nhài (đã pha) 100 ml; Nước cốt xoài 70 ml; Tắc 1 quả; Đường cát 6,25 g; Cốt xoài chanh dây 15 g |
| Trà vải | 100ml trà vải + 20ml đường + 10ml siro vải + 20ml mứt vải + 2 trái vải | Trà vải (đã pha) 100 ml; Đường cát 12,5 g; Siro vải 10 ml; Mứt vải 20 ml; Vải ngâm 2 quả |
| Trà đào | 100ml trà đào + 1 tắc + 20ml đường + 20ml mứt + 10ml siro + 3 lát đào | Trà đào (đã pha) 100 ml; Tắc 1 quả; Đường cát 12,5 g; Mứt đào 20 ml; Siro đào 10 ml; Đào ngâm (lát) 3 cái |
| Trà dâu chanh dây | 1 gói trà dâu + 100ml nước + 30ml mứt dâu + ½ trái chanh dây + 1 tắc | Gói trà dâu 1 gói; Mứt dâu 30 ml; Chanh dây 0,5 quả; Tắc 1 quả |
| Trà mãng cầu | 100ml trà nhài + 50ml cốt + 30ml mứt mãng cầu + 20ml đường + 2 tắc | Trà nhài (đã pha) 100 ml; Cốt mãng cầu 50 ml; Mứt mãng cầu 30 ml; Đường cát 12,5 g; Tắc 2 quả |
| Trà lài đác thơm | 120ml trà nhài + 30ml đường + 50ml cốt đác thơm + 20ml siro thơm + 1 tắc + 30g đác thơm | Trà nhài (đã pha) 120 ml; Đường cát 18,75 g; Cốt đác thơm 50 ml; Siro thơm 20 ml; Tắc 1 quả; Đác thơm 30 g |
| Trà hibiscus | 100ml trà hibicus + 20ml đường + 20ml siro + 20ml mứt (đào / vải / chanh dây) | Trà hibiscus (đã pha) 100 ml; Đường cát 12,5 g<br>+ Vị hibiscus Đào: Siro đào 20 ml; Mứt đào 20 ml<br>+ Vị hibiscus Vải: Siro vải 20 ml; Mứt vải 20 ml<br>+ Vị hibiscus Chanh dây: Siro chanh dây 20 ml; Mứt chanh dây 20 ml |
| Trà đác dâu tằm | 100ml trà nhài + 30ml cốt đác dâu + 20ml đường + 1 Tắc | Trà nhài (đã pha) 100 ml; Cốt đác dâu 30 ml; Đường cát 12,5 g; Tắc 1 quả |
| Trà tắc xí muội | 120ml trà nhài + 3 tắc + 1 chanh + 60ml đường + 10ml tắc xí muội | Trà nhài (đã pha) 120 ml; Tắc 3 quả; Chanh 1 quả; Đường cát 37,5 g; Tắc xí muội 10 ml |
| Trà dưỡng nhan | 1 Gói sẵn + 1 trà Oolong túi lọc | Gói trà dưỡng nhan 1 gói; Trà oolong túi lọc 1 cái |
| Trà đông trùng hạt sen | 1 Gói sẵn + 5g đường phèn + 10g đông trùng + 20g hạt sen | Gói trà đông trùng hạt sen 1 gói; Đường phèn 5 g; Đông trùng hạ thảo 10 g; Hạt sen 20 g |
| Trà cam quế mật ong | 1 Gói sẵn + ¼ trái cam + 30ml mật ong | Gói trà cam quế mật ong 1 gói; Cam 0,25 quả; Mật ong 30 ml |

## Món dừa

| Món | Công thức gốc | Định mức theo nguyên liệu kho (1 ly) |
|---|---|---|
| Bơ già | 50ml cốt dừa + 20ml sữa tươi + 30ml sữa đặc + 10ml rich + 100g bơ | Nước cốt dừa 50 ml; Sữa tươi 20 ml; Sữa đặc 30 ml; Kem béo Rich 10 ml; Thịt bơ 100 g |
| Khoai môn sữa dừa | 50ml cốt dừa + 20ml sữa tươi + 30ml sữa đặc + 10ml rich + 5g bột khoai môn | Nước cốt dừa 50 ml; Sữa tươi 20 ml; Sữa đặc 30 ml; Kem béo Rich 10 ml; Bột khoai môn 5 g |
