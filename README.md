# LAM Coffee System

Hệ thống vận hành quán LAM Coffee: bán hàng có kiểm soát điều chỉnh đơn, nguyên vật liệu theo định mức, quỹ tiền ca và đối soát, đo tải nhân sự. Bối cảnh sản phẩm ở [PRODUCT.md](PRODUCT.md), kế hoạch và tiến độ ở [KE_HOACH.md](KE_HOACH.md).

## Chạy trên máy cá nhân

```powershell
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe manage.py migrate
.venv\Scripts\python.exe manage.py createsuperuser
.venv\Scripts\python.exe manage.py runserver
```

Mở http://127.0.0.1:8000. Trang quản trị dữ liệu nền: http://127.0.0.1:8000/quan-tri/

Chạy kiểm thử: `.venv\Scripts\python.exe manage.py test`

## Cấu trúc

```
config/            cấu hình Django (đọc biến môi trường, xem .env.example)
apps/core/         nền chung: cửa hàng (mã cửa hàng NFR-18), lớp model nền, trang chủ, PWA, /healthz/, trang quản trị chỉ Chủ quán
apps/accounts/     tài khoản 5 vai trò, tạm khóa khi sai mật khẩu, ma trận phân quyền Bảng 5.3 (permissions.py)
apps/audit/        nhật ký thao tác chỉ thêm mới (model, QuerySet và trigger CSDL chặn sửa xóa)
apps/staff/        hồ sơ nhân viên, nghỉ việc thì khóa tài khoản
apps/catalog/      bàn, nhóm món, món, kích cỡ và giá, nhóm tùy chọn và tùy chọn
apps/inventory/    nhà cung cấp, nguyên vật liệu, định mức có phiên bản, sổ biến động kho và tồn (stock.py)
apps/shifts/       ca làm việc: người duyệt, dự phòng, người ủy quyền thanh toán
apps/orders/       tạo đơn, giữ nguyên liệu, quầy pha chế (services.py), điều chỉnh và chuyển cấp (adjustments.py), thanh toán (payments.py)
templates/, static/ giao diện theo DESIGN.md
```

## Tài khoản và dữ liệu chạy thử trên máy cá nhân

Trên cơ sở dữ liệu trống, `.venv\Scripts\python.exe manage.py tao_du_lieu_mau` tạo bàn, món, định mức, tồn đầu kỳ và 5 tài khoản `demo_*` (mỗi vai trò một tài khoản). Lệnh cũng tạo một ca mẫu từ 6 giờ đến 24 giờ hôm nay. Đây là dữ liệu mẫu, không phải thực đơn hay giá thật.

Chuyển cấp yêu cầu điều chỉnh chạy mỗi khi có người mở màn hình duyệt (mỗi 5 giây). Khi triển khai thật nên chạy thêm định kỳ mỗi phút qua bộ lập lịch.


CSDL chạy thử (`db.sqlite3`) có hai tài khoản mẫu, chỉ để xem giao diện: `demo_chuquan` (Chủ quán) và `demo_phucvu` (Phục vụ), mật khẩu `demo-lam-2026`. Không tạo các tài khoản này trên máy chủ thật.

Các phần nghiệp vụ (đơn hàng, pha chế, nguyên vật liệu, ca và tiền, cảnh báo, báo cáo) sẽ thêm thành ứng dụng riêng trong `apps/` theo thứ tự ở KE_HOACH.md.

## Quy ước

- Bảng dữ liệu chính kế thừa `apps.core.models.StoreScopedModel` để có mã cửa hàng.
- Mọi màn hình khai báo quyền bằng `capability_required(Cap.X)` hoặc `CapabilityRequiredMixin`; không chỉ ẩn nút trên giao diện.
- Mọi thay đổi dữ liệu gọi `apps.audit.services.record(...)`; trang quản trị dùng `AuditedAdminMixin`.
- Giao diện thiết kế bằng Impeccable; phong cách tạm thời sẽ ghi trong DESIGN.md.
