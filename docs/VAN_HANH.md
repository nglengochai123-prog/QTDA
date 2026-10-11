# Vận hành, nghiệm thu và kiểm tra kỹ thuật

Cập nhật 12/10/2026.

## 1. Tự nghiệm thu trên localhost

Bộ dữ liệu nghiệm thu có 14 ngày vận hành mẫu: nhập hàng, mở ca, đơn, pha, phục vụ, thu tiền, hủy hóa đơn và hoàn tiền, phiếu dự phòng, kiểm kê, kết ca, báo cáo cuối ca. Nó nằm ở tệp riêng `nghiem_thu.sqlite3`, không đụng `db.sqlite3` đang dùng. Đây là dữ liệu mẫu, không phải số liệu thật.

Tạo lại từ đầu (PowerShell, trong `D:\QTDA`):

```powershell
Remove-Item nghiem_thu.sqlite3 -ErrorAction SilentlyContinue
$env:SQLITE_NAME = "nghiem_thu.sqlite3"
.venv\Scripts\python.exe manage.py migrate
.venv\Scripts\python.exe manage.py tao_du_lieu_nghiem_thu
.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8766
```

Mở http://127.0.0.1:8766. Mật khẩu chung: `demo-lam-2026`.

| Vai trò | Tài khoản | Nên thử |
|---|---|---|
| Chủ quán | `demo_chuquan` | /bang-dieu-khien/ (chỉ tiêu BO-01, BO-02, biểu đồ, lọc tháng), /bao-cao/doanh-thu/ (xuất Excel), /bao-cao/kiem-soat/, /bao-cao/nguyen-lieu/, /canh-bao/, /kiem-soat/ngoai-le/, /tham-so/, /quan-tri/ |
| Quản lý ca | `demo_quanlyca` | /ca/ (quỹ ca, kết ca, báo cáo cuối ca, đính chính), /duyet/, /du-phong/ (phiếu dự phòng), /cham-cong/ (bổ sung giờ ra), /tai/, /bang-dieu-khien/ (phần ca) |
| Thu ngân | `demo_thungan` | /thu-ngan/, /ca/ (xác nhận đã hoàn tiền) |
| Phục vụ | `demo_phucvu` | /don/moi/ trên điện thoại, /don/san-sang/, /don/dang-mo/ (gửi điều chỉnh) |
| Pha chế | `demo_phache` | /quay/, /kho/ (báo nhanh, phiếu nhập, kiểm kê, hao hụt), /cham-cong/ |

Thử quyền: đăng nhập phục vụ rồi mở /thu-ngan/ hoặc /bang-dieu-khien/ sẽ gặp trang "Bạn không có quyền", và lần đó được ghi vào nhật ký (Chủ quán xem ở /quan-tri/ › Nhật ký).

## 2. Tác vụ định kỳ

Lệnh `chay_dinh_ky` ghi chuyển cấp yêu cầu điều chỉnh, giao chậm, nhắc ca thiếu người duyệt dự phòng, nhắc thiếu giờ ra, và tạo, đóng, chuyển cấp cảnh báo kèm thông báo đẩy. Màn hình vẫn tính đúng khi đọc, nhưng cảnh báo và nhật ký chuyển cấp chỉ cập nhật khi lệnh chạy, nên khi vận hành thật lệnh phải chạy mỗi phút.

**Windows (máy chủ đặt ở quán):** tạo một tác vụ chạy mỗi phút bằng Task Scheduler:

```powershell
schtasks /Create /TN "LAM Coffee - kiem tra dinh ky" /SC MINUTE /MO 1 /TR "D:\QTDA\.venv\Scripts\python.exe D:\QTDA\manage.py chay_dinh_ky" /RU SYSTEM
```

Hoặc chạy một tiến trình lặp: `.venv\Scripts\python.exe manage.py chay_dinh_ky --lap 60` (cần tự khởi động lại khi máy khởi động).

**Linux (nếu thuê máy chủ):** dòng cron `* * * * * cd /srv/qtda && .venv/bin/python manage.py chay_dinh_ky`.

Kiểm tra: chạy tay một lần, lệnh in số yêu cầu chuyển cấp, số lần đặt giao chậm, số cảnh báo tạo, đóng, chuyển cấp.

## 3. Thông báo đẩy (NFR-17)

Đã làm: lưu đăng ký thiết bị, nút "Bật thông báo trên thiết bị này" ở trang Cảnh báo, service worker hiện thông báo và mở đúng màn hình khi chạm, gửi khi cảnh báo được giao hoặc chuyển cấp (Bảng 5.4, không gửi mức Thông tin).

Chưa gửi được vì còn thiếu, cần Chủ quán cho phép:

1. Cài thư viện gửi: `.venv\Scripts\python.exe -m pip install pywebpush` (kéo theo `cryptography`, `py-vapid`).
2. Tạo cặp khóa VAPID một lần: `.venv\Scripts\vapid.exe --gen` rồi `vapid --applicationServerKey`; đặt biến môi trường `WEBPUSH_VAPID_PUBLIC_KEY`, `WEBPUSH_VAPID_PRIVATE_KEY` (đường dẫn tệp private_key.pem hoặc nội dung khóa), `WEBPUSH_CONTACT=mailto:<email của quán>`.

Điều kiện thử trên điện thoại:

- Trình duyệt chỉ cho đăng ký thông báo khi trang mở qua **HTTPS** (riêng `localhost` trên chính máy tính thì được). Điện thoại trong quán vào máy tính qua địa chỉ LAN (http://192.168.x.x) sẽ không bật được; cần tên miền có chứng chỉ, hoặc một đường hầm HTTPS. Việc chọn cách nào là quyết định của quán vì liên quan dịch vụ bên ngoài.
- Android: Chrome bản mới, cho phép thông báo khi được hỏi.
- iPhone: iOS 16.4 trở lên, mở bằng Safari, chọn "Thêm vào màn hình chính", mở ứng dụng từ biểu tượng đó rồi mới bật thông báo.
- Cách thử: đăng nhập Quản lý ca trên điện thoại, vào /canh-bao/, bấm bật; ở máy tính tạo một báo nhanh "Đã hết" trong giờ mở cửa rồi chạy `chay_dinh_ky`; điện thoại phải nhận thông báo kể cả khi đã đóng ứng dụng.

## 4. Kiểm thử đồng thời trên PostgreSQL (chờ cho phép cài)

Hiện mới kiểm trên SQLite. **Chưa được coi là đã xác minh trên PostgreSQL.**

Mã đã sẵn sàng cho PostgreSQL: cấu hình đọc biến môi trường, trigger chỉ-thêm-mới có bản PostgreSQL, kiểm thử đồng thời tự dùng đúng câu lệnh theo loại CSDL.

Các bước khi được phép:

1. Cài PostgreSQL 16 cho Windows (trình cài đặt chính thức), tạo người dùng và CSDL:
   `CREATE USER lamcoffee WITH PASSWORD '<mật khẩu>' CREATEDB; CREATE DATABASE lamcoffee OWNER lamcoffee;`
   (`CREATEDB` để Django tạo CSDL kiểm thử riêng.)
2. Cài trình kết nối: `.venv\Scripts\python.exe -m pip install "psycopg[binary]"`.
3. Đặt biến môi trường: `DB_ENGINE=postgresql`, `DB_NAME=lamcoffee`, `DB_USER=lamcoffee`, `DB_PASSWORD=...`, `DB_HOST=localhost`.
4. Chạy: `manage.py migrate`, rồi `manage.py test apps.orders.tests.test_flow.ConcurrentOrderTests` (hai đơn tranh phần tồn cuối), rồi toàn bộ `manage.py test`.
5. Chạy thêm một lần với nhiều luồng hơn (đề xuất 8 luồng, 20 lượt) bằng biến thể của kiểm thử trên, đối chiếu `kiem_tra_toan_ven` sau khi chạy.

Tiêu chí đạt: đúng một đơn được nhận khi chỉ đủ một ly; không có tồn âm hay giữ chỗ lệch (`kiem_tra_toan_ven` không báo sai lệch); toàn bộ kiểm thử đạt trên PostgreSQL.
