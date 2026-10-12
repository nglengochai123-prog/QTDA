# Vận hành, nghiệm thu và kiểm tra kỹ thuật

Cập nhật 12/10/2026. Mọi lệnh chạy trong PowerShell, tại thư mục `D:\QTDA`.

## 0. Trạng thái kiểm chứng

| Hạng mục | Kết quả | Kiểm chứng bằng |
|---|---|---|
| Kiểm thử tự động trên SQLite | 176 bài đạt | `manage.py test` |
| Kiểm thử tự động trên PostgreSQL 16.10 | 176 bài đạt (sau khi sửa 2 lỗi chỉ lộ ra trên PostgreSQL) | `manage.py test` với cấu hình PostgreSQL |
| Đồng thời trên PostgreSQL: hai đơn tranh phần tồn cuối, gửi lại cùng mã, hoàn thành một món nhiều lần, thanh toán cùng lúc, hai người duyệt một yêu cầu | Đạt: không âm kho, không ghi trùng tiền, không hiệu lực hai lần, `kiem_tra_toan_ven` sạch | `apps/core/tests/test_concurrency.py`, 6 luồng chạy cùng lúc |
| Bộ dữ liệu 14 ngày trên PostgreSQL | Tạo được, `kiem_tra_toan_ven` không báo sai lệch | Lệnh mục 4 |
| Đính chính báo cáo cuối ca | Đạt trên trình duyệt: Quản lý ca gửi, Chủ quán duyệt, chênh lệch 20.000 đ hết hiệu lực, giá trị kiểm soát giảm từ 40.000 xuống 20.000 đ, không cộng trùng | Trình duyệt, bộ dữ liệu mẫu |
| Chấm công | Đạt trên trình duyệt: ra ca, vào ca, lượt quên ra ca được nhắc rồi bổ sung có lý do | Trình duyệt |
| Cảnh báo | Đạt trên trình duyệt: báo Đã hết tạo cảnh báo Khẩn giao Quản lý ca, nhận xử lý, đóng không ghi kết quả bị từ chối, đóng có kết quả được | Trình duyệt |
| Xuất Excel | Đạt: Microsoft Excel mở được tệp, 7 trang, hàm SUM của Excel trên mỗi trang bằng 8.485.000 đ, khớp hệ thống; hoàn 64.000 đ; thuần 8.421.000 đ | Excel mở qua tự động hóa, đối chiếu với báo cáo |
| Thông báo đẩy: máy chủ | Sẵn sàng: đã cài pywebpush, có khóa VAPID, trang Cảnh báo báo "sẵn sàng" | Trình duyệt trên máy tính |
| Thông báo đẩy: điện thoại thật nhận được | **Chờ Hai thử** theo mục 3 | |

## 1. Bộ dữ liệu mẫu để tự nghiệm thu

Tạo lại từ đầu (xóa tệp mẫu cũ, không đụng `db.sqlite3` đang dùng):

```powershell
Remove-Item nghiem_thu.sqlite3 -ErrorAction SilentlyContinue
$env:SQLITE_NAME = "nghiem_thu.sqlite3"
.venv\Scripts\python.exe manage.py migrate
.venv\Scripts\python.exe manage.py tao_du_lieu_nghiem_thu
```

Chạy máy chủ cho bộ dữ liệu mẫu (cửa sổ PowerShell để mở, `Ctrl+C` để dừng):

```powershell
$env:SQLITE_NAME = "nghiem_thu.sqlite3"
.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8766
```

Mở http://127.0.0.1:8766. Mật khẩu chung `demo-lam-2026`:

| Vai trò | Tài khoản | Nên thử |
|---|---|---|
| Chủ quán | `demo_chuquan` | /bang-dieu-khien/, /bao-cao/doanh-thu/ (Xuất file Excel), /bao-cao/kiem-soat/, /bao-cao/nguyen-lieu/, /ca/tinh-trang/ (duyệt đính chính), /canh-bao/, /du-phong/ (xác nhận giá phiếu chờ), /tham-so/, /quan-tri/ |
| Quản lý ca | `demo_quanlyca` | /ca/ và /ca/<số>/ (đính chính báo cáo), /duyet/, /du-phong/, /cham-cong/ (bổ sung giờ ra), /tai/, /canh-bao/ |
| Thu ngân | `demo_thungan` | /thu-ngan/, /ca/ (xác nhận đã hoàn tiền) |
| Phục vụ | `demo_phucvu` | /don/moi/ trên điện thoại, /don/san-sang/, /don/dang-mo/ |
| Pha chế | `demo_phache` | /quay/, /kho/, /cham-cong/ |

Mở /thu-ngan/ bằng tài khoản phục vụ sẽ gặp trang "Bạn không có quyền"; lần đó được ghi nhật ký.

Bản sao lưu dữ liệu trước đợt kiểm thử nằm ở `D:\QTDA\backups\` (`db-20261012-101625.sqlite3`, `nghiem_thu-20261012-101625.sqlite3`).

## 2. Tác vụ định kỳ

Lệnh `chay_dinh_ky` ghi chuyển cấp yêu cầu điều chỉnh, giao chậm, nhắc ca thiếu người duyệt dự phòng, nhắc thiếu giờ ra, tạo, đóng, chuyển cấp cảnh báo và gửi thông báo đẩy. Phải chạy mỗi phút khi vận hành.

Chạy tay một lần (để kiểm tra):

```powershell
.venv\Scripts\python.exe manage.py chay_dinh_ky
```

Chạy lặp mỗi 60 giây trong một cửa sổ riêng (`Ctrl+C` để dừng):

```powershell
.venv\Scripts\python.exe manage.py chay_dinh_ky --lap 60
```

Lên lịch bằng Task Scheduler (chạy cả khi chưa đăng nhập; cần PowerShell mở bằng "Run as administrator"):

```powershell
schtasks /Create /TN "LAM Coffee - kiem tra dinh ky" /SC MINUTE /MO 1 /TR "D:\QTDA\.venv\Scripts\python.exe D:\QTDA\manage.py chay_dinh_ky" /RU SYSTEM
```

Dừng hoặc xóa lịch:

```powershell
schtasks /End /TN "LAM Coffee - kiem tra dinh ky"
schtasks /Delete /TN "LAM Coffee - kiem tra dinh ky" /F
```

Với bộ dữ liệu mẫu, đặt `$env:SQLITE_NAME = "nghiem_thu.sqlite3"` trước khi chạy lệnh.

## 3. Thử thông báo đẩy trên điện thoại thật

### Đã chuẩn bị

- Thư viện `pywebpush` đã cài trong `.venv`; cặp khóa VAPID ở `D:\QTDA\.secrets\` (không đưa lên Git).
- Máy chủ thử chạy bộ dữ liệu mẫu ở chế độ vận hành (không hiện lỗi chi tiết), cấu hình ở `.secrets\thu_thong_bao.env`.
- Đường hầm HTTPS tạm thời miễn phí qua localhost.run, không cần tài khoản. Chỉ mở bộ dữ liệu mẫu, vẫn phải đăng nhập. Đường hầm tự tắt sau 4 giờ.
- Mỗi lần gửi ghi ba mốc riêng ở trang Cảnh báo: **Máy chủ gửi lúc**, **Dịch vụ đẩy đã nhận** (Google hoặc Apple trả mã 201, nghĩa là máy chủ gửi thành công, chưa chắc điện thoại đã nhận), **Điện thoại đã hiện** (chính điện thoại báo về khi thông báo xuất hiện), và **Đã chạm mở**.

### Mở lại khi cần (hai cửa sổ PowerShell)

Cửa sổ 1, máy chủ thử:

```powershell
$env:LAM_ENV_FILE = ".secrets/thu_thong_bao.env"
.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8767 --insecure
```

Cửa sổ 2, đường hầm (in ra địa chỉ dạng `https://xxxx.lhr.life`):

```powershell
ssh -o StrictHostKeyChecking=accept-new -R 80:127.0.0.1:8767 nokey@localhost.run
```

Địa chỉ đường hầm đổi mỗi lần mở; cấu hình đã cho phép mọi địa chỉ `*.lhr.life`.

### Các bước trên điện thoại

**Android (Chrome):**
1. Mở địa chỉ `https://xxxx.lhr.life` bằng Chrome, đăng nhập `demo_quanlyca` / `demo-lam-2026`.
2. Vào **Cảnh báo** (thanh dưới). Ở khối "Thông báo đẩy trên điện thoại", bấm **Bật thông báo trên thiết bị này**.
3. Chrome hỏi quyền: chọn **Cho phép**. Nếu lỡ chặn: chạm biểu tượng ổ khóa cạnh địa chỉ › **Quyền** › **Thông báo** › **Cho phép**, rồi tải lại trang.
4. Kiểm tra cài đặt điện thoại: **Cài đặt › Ứng dụng › Chrome › Thông báo** đang bật; tắt chế độ **Không làm phiền**.
5. Bấm **Gửi thử đến thiết bị của tôi**. Rồi **thoát Chrome về màn hình chính** (hoặc khóa máy) để thử khi ứng dụng không mở.
6. Thông báo "Thử thông báo LAM Coffee" phải hiện. Chạm vào nó; Chrome mở trang Cảnh báo.
7. Ở bảng bên dưới nút, cột **Điện thoại đã hiện** và **Đã chạm mở** phải có giờ.

**iPhone (cần iOS 16.4 trở lên):**
1. Mở địa chỉ bằng **Safari** (không dùng Chrome trên iPhone), đăng nhập.
2. Chạm nút **Chia sẻ** › **Thêm vào Màn hình chính** › **Thêm**.
3. **Đóng Safari**, mở ứng dụng LAM Coffee từ biểu tượng vừa thêm (bắt buộc; iPhone chỉ cho thông báo khi mở theo cách này). Đăng nhập lại nếu được hỏi.
4. Vào **Cảnh báo** › **Bật thông báo trên thiết bị này** › chọn **Cho phép**.
5. Nếu lỡ chặn: **Cài đặt › Thông báo › LAM Coffee › Cho phép thông báo**.
6. Bấm **Gửi thử**, về màn hình chính, chờ thông báo, chạm mở, rồi xem bảng như bước 7 của Android.

**Thử với cảnh báo thật:** trên máy tính đăng nhập Pha chế, ở /kho/bao-nhanh/ bấm **Đã hết** một nguyên liệu (trong giờ 6–22), rồi chạy `chay_dinh_ky` với bộ dữ liệu mẫu; điện thoại của Quản lý ca phải nhận thông báo "Khẩn: ... đã hết".

**Đọc kết quả:** "Dịch vụ đẩy đã nhận: Có (mã 201)" mà "Điện thoại đã hiện: Chưa" nghĩa là máy chủ đã gửi đúng nhưng điện thoại chưa hiện (thường do quyền thông báo, Không làm phiền, tiết kiệm pin hoặc điện thoại mất mạng). Cả hai có giờ là đạt.

### Tắt sau khi thử

Trong cửa sổ đường hầm và cửa sổ máy chủ, bấm `Ctrl+C`. Nếu đã đóng cửa sổ mà tiến trình còn chạy:

```powershell
Get-NetTCPConnection -LocalPort 8767 -State Listen | ForEach-Object { Stop-Process -Id $_.OwningProcess }
Get-CimInstance Win32_Process -Filter "Name='ssh.exe'" | Where-Object { $_.CommandLine -like "*localhost.run*" } | ForEach-Object { Stop-Process -Id $_.ProcessId }
```

Sau khi tắt, địa chỉ `*.lhr.life` không còn truy cập được.

## 4. PostgreSQL để kiểm thử

Cài dạng gói rời (không dịch vụ Windows, không cần quyền quản trị) tại `C:\Users\HP\lam-postgres\`: PostgreSQL 16.10, cổng **5433**, chỉ nghe trên máy này. CSDL kiểm thử `lamcoffee_test`, người dùng `lamcoffee_test`; mật khẩu nằm trong `C:\Users\HP\lam-postgres\lam-test.env` (ngoài kho mã). Dữ liệu SQLite không bị đụng tới.

Bật và tắt PostgreSQL:

```powershell
C:\Users\HP\lam-postgres\pgsql\bin\pg_ctl.exe -D C:\Users\HP\lam-postgres\data -o "-p 5433 -c listen_addresses=localhost" -l C:\Users\HP\lam-postgres\pg.log start
C:\Users\HP\lam-postgres\pgsql\bin\pg_ctl.exe -D C:\Users\HP\lam-postgres\data stop
```

Chạy kiểm thử trên PostgreSQL (trong cùng cửa sổ, sau khi bật):

```powershell
Get-Content C:\Users\HP\lam-postgres\lam-test.env | ForEach-Object { $k, $v = $_ -split "=", 2; Set-Item "env:$k" $v }
.venv\Scripts\python.exe manage.py test apps.core.tests.test_concurrency --noinput
.venv\Scripts\python.exe manage.py test --noinput
```

Đóng cửa sổ để bỏ các biến môi trường (các cửa sổ khác vẫn dùng SQLite).

Gỡ hẳn khi không cần: tắt PostgreSQL rồi xóa thư mục `C:\Users\HP\lam-postgres\`.

### Lỗi đã tìm và sửa nhờ PostgreSQL

- Gửi lại cùng mã nghiệp vụ đúng lúc yêu cầu đầu còn đang xử lý: trên PostgreSQL yêu cầu sau chạy lại nghiệp vụ và báo lỗi sai (ví dụ "thiếu nguyên liệu") dù không ghi trùng. Đã sửa: giữ chỗ mã trước khi làm, yêu cầu sau chờ rồi nhận đúng kết quả của yêu cầu đầu.
- Chuyển cấp yêu cầu điều chỉnh khóa cả dòng của bảng liên kết có thể rỗng, PostgreSQL từ chối. Đã sửa để chỉ khóa dòng của yêu cầu.
