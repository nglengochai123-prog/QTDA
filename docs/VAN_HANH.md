# Vận hành, nghiệm thu và kiểm tra kỹ thuật

Cập nhật 12/10/2026. Mọi lệnh chạy trong PowerShell, tại thư mục `D:\QTDA`.

## 0. Trạng thái kiểm chứng

| Hạng mục | Kết quả | Kiểm chứng bằng |
|---|---|---|
| Kiểm thử tự động trên SQLite | Xem dòng cập nhật ở cuối tài liệu | `manage.py test` |
| Kiểm thử tự động trên PostgreSQL 16.10 | 176 bài đạt (sau khi sửa 2 lỗi chỉ lộ ra trên PostgreSQL) | `manage.py test` với cấu hình PostgreSQL |
| Đồng thời trên PostgreSQL: hai đơn tranh phần tồn cuối, gửi lại cùng mã, hoàn thành một món nhiều lần, thanh toán cùng lúc, hai người duyệt một yêu cầu | Đạt: không âm kho, không ghi trùng tiền, không hiệu lực hai lần, `kiem_tra_toan_ven` sạch | `apps/core/tests/test_concurrency.py`, 6 luồng chạy cùng lúc |
| Bộ dữ liệu 14 ngày trên PostgreSQL | Tạo được, `kiem_tra_toan_ven` không báo sai lệch | Lệnh mục 4 |
| Đính chính báo cáo cuối ca | Đạt trên trình duyệt: Quản lý ca gửi, Chủ quán duyệt, chênh lệch 20.000 đ hết hiệu lực, giá trị kiểm soát giảm từ 40.000 xuống 20.000 đ, không cộng trùng | Trình duyệt, bộ dữ liệu mẫu |
| Chấm công | Đạt trên trình duyệt: ra ca, vào ca, lượt quên ra ca được nhắc rồi bổ sung có lý do | Trình duyệt |
| Cảnh báo | Đạt trên trình duyệt: báo Đã hết tạo cảnh báo Khẩn giao Quản lý ca, nhận xử lý, đóng không ghi kết quả bị từ chối, đóng có kết quả được | Trình duyệt |
| Xuất Excel | Đạt: Microsoft Excel mở được tệp, 7 trang, hàm SUM của Excel trên mỗi trang bằng 8.485.000 đ, khớp hệ thống; hoàn 64.000 đ; thuần 8.421.000 đ | Excel mở qua tự động hóa, đối chiếu với báo cáo |
| Thông báo đẩy: máy chủ | Sẵn sàng: đã cài pywebpush, có khóa VAPID, trang Cảnh báo báo "sẵn sàng" | Trình duyệt trên máy tính |
| Thông báo đẩy: điện thoại thật nhận được | **Tạm hoãn, chờ Hai nghiệm thu** theo mục 3; đường hầm đã tắt | |
| Sao lưu và phục hồi SQLite | Đạt: `sao_luu` tạo bản sao nhất quán, giữ đúng số bản; `phuc_hoi` vào tệp riêng, `PRAGMA integrity_check` ok, `kiem_tra_toan_ven` sạch; từ chối phục hồi đè CSDL đang chạy; mã băm `db.sqlite3` trước và sau phục hồi giống nhau | Mục 6, `apps/core/tests/test_backup.py` |
| Sao lưu và phục hồi PostgreSQL | Đạt: `pg_dump` 449 KB, phục hồi vào CSDL riêng `lamcoffee_phuc_hoi_thu`, kiểm tra cấu trúc và toàn vẹn đạt; số đơn, thanh toán, biến động kho, nhật ký khớp bản gốc (237, 123, 543, 1023) | Mục 6 |

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
schtasks /Create /TN "LAM Coffee - kiem tra dinh ky" /SC MINUTE /MO 1 /TR "D:\QTDA\scripts\chay_dinh_ky.cmd" /RU SYSTEM
```

`scripts\chay_dinh_ky.cmd` tự chuyển về thư mục dự án và ghi kết quả từng lần chạy vào `logs\dinh_ky.log` (đã thử chạy tay: thoát mã 0, nhật ký có dòng "Chuyển cấp 0 yêu cầu; ...").

Dừng hoặc xóa lịch:

```powershell
schtasks /End /TN "LAM Coffee - kiem tra dinh ky"
schtasks /Delete /TN "LAM Coffee - kiem tra dinh ky" /F
```

Với bộ dữ liệu mẫu, đặt `$env:SQLITE_NAME = "nghiem_thu.sqlite3"` trước khi chạy lệnh.

## 3. Thử thông báo đẩy trên điện thoại thật

**Trạng thái 12/10/2026: tạm hoãn theo yêu cầu của Hai, chờ người dùng nghiệm thu.** Đường hầm đã tắt; không có tiến trình `ssh` hay máy chủ cổng 8767 nào còn chạy. Mục này không chặn các phần khác. Khi muốn thử, làm theo các bước dưới.

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

## 5. Khởi động và dừng

**Chạy thử trên máy này (SQLite, chế độ phát triển):**

```powershell
.venv\Scripts\python.exe manage.py migrate
.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8765
```

Dừng: bấm `Ctrl+C` trong cửa sổ đó. Nếu đã đóng cửa sổ mà máy chủ còn chạy, chỉ dừng đúng tiến trình đang nghe cổng của mình (không tắt mọi `python.exe`):

```powershell
Get-NetTCPConnection -LocalPort 8765 -State Listen | ForEach-Object { Stop-Process -Id $_.OwningProcess }
```

**Máy chủ thật theo báo cáo (máy chủ ảo Linux, Nginx, Gunicorn, PostgreSQL, HTTPS Let's Encrypt).** Chưa triển khai; các bước dưới là kịch bản, chưa chạy thử trên máy chủ thật.

1. Sao chép `.env.production.example` thành `.env`, điền khóa bí mật, tên miền, mật khẩu CSDL, thư mục sao lưu, khóa VAPID mới. `.env` thật không đưa lên Git.
2. `python manage.py migrate`, `python manage.py collectstatic --noinput`, `python manage.py check --deploy`.
3. Chạy `gunicorn config.wsgi --bind 127.0.0.1:8000 --workers 3` dưới systemd; Nginx chuyển tiếp HTTPS vào cổng 8000 và đặt `X-Forwarded-Proto`.
4. Tác vụ định kỳ bằng cron: `* * * * * cd /srv/lamcoffee && .venv/bin/python manage.py chay_dinh_ky >> logs/dinh_ky.log 2>&1` và `30 23 * * * cd /srv/lamcoffee && .venv/bin/python manage.py sao_luu >> logs/sao_luu.log 2>&1`.
5. Dừng: `systemctl stop` dịch vụ Gunicorn; khởi động lại sau cập nhật mã: `migrate`, `collectstatic`, `systemctl restart`.

## 6. Sao lưu và phục hồi (NFR-09)

Yêu cầu: tự động hằng ngày ra nơi lưu trữ ngoài máy chủ, giữ tối thiểu 30 bản, mất dữ liệu tối đa 24 giờ, phục hồi không quá 4 giờ.

**Cấu hình** trong `.env`: `LAM_BACKUP_DIR` (thư mục đích, nên là ổ ngoài hoặc thư mục được đồng bộ lên dịch vụ lưu trữ; để trống thì dùng `D:\QTDAackups`), `LAM_BACKUP_KEEP` (mặc định 30), `LAM_PG_BIN` (thư mục chứa `pg_dump` khi dùng PostgreSQL).

**Sao lưu tay:**

```powershell
.venv\Scripts\python.exe manage.py sao_luu
```

SQLite được chép bằng cơ chế sao lưu trực tuyến của SQLite (nhất quán cả khi máy chủ đang chạy) rồi kiểm tra toàn vẹn bản chép; PostgreSQL dùng `pg_dump` định dạng nén. Nếu có ảnh chứng từ chi tiền thì nén kèm thành tệp `-media.zip`. Bản cũ vượt số bản giữ lại tự xóa.

**Lên lịch hằng ngày 23:30** (PowerShell "Run as administrator"):

```powershell
schtasks /Create /TN "LAM Coffee - sao luu" /SC DAILY /ST 23:30 /TR "D:\QTDA\scripts\sao_luu.cmd" /RU SYSTEM
```

Kết quả từng lần ghi ở `logs\sao_luu.log`. Chưa tạo lịch này trên máy của Hai; tạo lịch là thay đổi cấu hình máy nên để Hai tự chạy lệnh.

**Diễn tập phục hồi** (không đụng CSDL đang chạy; nên làm mỗi tháng):

```powershell
.venv\Scripts\python.exe manage.py phuc_hoi --danh-sach
.venv\Scripts\python.exe manage.py phuc_hoi --vao backups	hu-phuc-hoi.sqlite3
```

Bỏ tên tệp thì lấy bản mới nhất. Lệnh chép bản sao lưu vào đích riêng, kiểm tra toàn vẹn, kiểm tra cấu trúc khớp mã nguồn (`migrate --check`) và chạy `kiem_tra_toan_ven` trên đích đó. Lệnh từ chối nếu đích trùng CSDL đang chạy, hoặc đích đã có mà không thêm `--ghi-de`.

Nếu bản sao lưu được tạo trước một lần cập nhật mã, lệnh báo "Bản sao lưu có cấu trúc cũ hơn mã nguồn, còn thiếu: ..." và gợi ý thêm `--cap-nhat-cau-truc` để áp các bước còn thiếu lên bản phục hồi. Lần diễn tập 12/10/2026 đã gặp đúng trường hợp này (bản sao lưu trước 4 bước cập nhật cấu trúc mới) và xử lý được.

Với PostgreSQL, `--vao` là tên CSDL đích mới, ví dụ `--vao lamcoffee_phuc_hoi_thu`; người dùng CSDL cần quyền tạo CSDL.

**Khi cần dùng bản phục hồi thật:** dừng máy chủ và tác vụ định kỳ, sao lưu tay CSDL hiện tại (dù hỏng) để giữ dấu vết, trỏ `SQLITE_NAME` hoặc `DB_NAME` trong `.env` tới đích đã kiểm tra, khởi động lại, chạy `kiem_tra_toan_ven`. Dữ liệu phát sinh sau giờ sao lưu cần nhập lại từ phiếu dự phòng và sổ tay của ca.
