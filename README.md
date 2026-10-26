# LAM Coffee System

Hệ thống vận hành quán LAM Coffee (cách từng chức năng hoạt động: [docs/CACH_HOAT_DONG.md](docs/CACH_HOAT_DONG.md)): bán hàng có kiểm soát điều chỉnh đơn, nguyên vật liệu theo định mức, quỹ tiền ca và đối soát, đo tải nhân sự. Bối cảnh sản phẩm ở [PRODUCT.md](PRODUCT.md), chuẩn giao diện ở [DESIGN.md](DESIGN.md), kế hoạch và tiến độ ở [KE_HOACH.md](KE_HOACH.md), đối chiếu với báo cáo yêu cầu và các quyết định chờ Chủ quán ở [docs/DOI_CHIEU_YEU_CAU.md](docs/DOI_CHIEU_YEU_CAU.md).

## Chạy trên máy cá nhân

```powershell
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe manage.py migrate
.venv\Scripts\python.exe manage.py createsuperuser
.venv\Scripts\python.exe manage.py runserver
```

Mở http://127.0.0.1:8000. Trang quản trị dữ liệu nền: http://127.0.0.1:8000/quan-tri/

Chạy kiểm thử: `.venv\Scripts\python.exe manage.py test`

Kiểm tra quá hạn (chuyển cấp duyệt, giao chậm): `.venv\Scripts\python.exe manage.py chay_dinh_ky` chạy một lần, thêm `--lap 60` để lặp mỗi phút. Màn hình luôn tính đúng khi đọc; lệnh này ghi trạng thái và nhật ký.

Đối chiếu chéo sổ kho, đơn, tiền và ca: `.venv\Scripts\python.exe manage.py kiem_tra_toan_ven`

## Cấu trúc

```
config/            cấu hình Django (đọc biến môi trường, xem .env.example)
apps/core/         nền chung: cửa hàng (mã cửa hàng NFR-18), lớp model nền, trang chủ, PWA, /healthz/, trang quản trị chỉ Chủ quán
apps/accounts/     tài khoản 4 vai trò (đã bỏ Quản lý ca theo GD-27), tạm khóa khi sai mật khẩu, ma trận phân quyền Bảng 5.3 (permissions.py)
apps/audit/        nhật ký thao tác chỉ thêm mới (model, QuerySet và trigger CSDL chặn sửa xóa)
apps/staff/        hồ sơ nhân viên, nghỉ việc thì khóa tài khoản; chấm công theo vai trò (timekeeping.py)
apps/catalog/      bàn, nhóm món, món, kích cỡ và giá, nhóm tùy chọn và tùy chọn
apps/inventory/    nhà cung cấp, nguyên vật liệu, định mức có phiên bản, sổ biến động kho và tồn (stock.py)
apps/shifts/       ca làm việc, quỹ tiền ca, hoàn tiền, kết ca, báo cáo cuối ca, đối soát (services.py)
apps/orders/       tạo đơn, giữ nguyên liệu, quầy pha chế (services.py), điều chỉnh và chuyển cấp (adjustments.py), thanh toán (payments.py), phiếu dự phòng và nhập bù (backup.py), tải theo khung giờ (workload.py)
apps/control/      ngoại lệ, xem xét, vụ việc tổn thất, báo cáo điều chỉnh, trang tham số, trung tâm cảnh báo (alerts.py)
apps/reports/      bảng điều khiển, báo cáo doanh thu (xuất Excel), kiểm soát doanh thu, nguyên vật liệu theo kỳ
apps/core/         thêm: tham số có lịch sử (params.py), mã nghiệp vụ chống ghi trùng (idempotency.py), tác vụ định kỳ (periodic.py), kiểm tra toàn vẹn (integrity.py)
templates/, static/ giao diện theo DESIGN.md
```

## Tài khoản và dữ liệu chạy thử trên máy cá nhân

Trên cơ sở dữ liệu trống, `.venv\Scripts\python.exe manage.py tao_du_lieu_mau` tạo bàn, món, định mức, tồn đầu kỳ và 4 tài khoản `demo_*` (mỗi vai trò một tài khoản). Lệnh cũng tạo một ca mẫu từ 6 giờ đến 24 giờ hôm nay. Đây là dữ liệu mẫu, không phải thực đơn hay giá thật.

Cấp duyệt của yêu cầu điều chỉnh được tính đúng mỗi khi đọc, không phụ thuộc ai mở màn hình. Khi triển khai thật, lên lịch `chay_dinh_ky` mỗi phút để nhật ký chuyển cấp ghi đúng thời điểm.

CSDL chạy thử (`db.sqlite3`) có hai tài khoản mẫu, chỉ để xem giao diện: `demo_chuquan` (Chủ quán) và `demo_phucvu` (Phục vụ), mật khẩu `demo-lam-2026`. Không tạo các tài khoản này trên máy chủ thật.


## Quy ước

- Bảng dữ liệu chính kế thừa `apps.core.models.StoreScopedModel` để có mã cửa hàng.
- Mọi màn hình khai báo quyền bằng `capability_required(Cap.X)` hoặc `CapabilityRequiredMixin`; không chỉ ẩn nút trên giao diện.
- Mọi thay đổi dữ liệu gọi `apps.audit.services.record(...)`; trang quản trị dùng `AuditedAdminMixin`.
- Thay đổi tồn kho chỉ qua `apps.inventory.stock`; thao tác tạo dữ liệu bọc trong `run_once` với mã nghiệp vụ.
- Đọc tham số bằng `params.get(key, at=...)` theo thời điểm nghiệp vụ; lưu giá trị đã áp dụng khi kết quả cần giữ nguyên về sau.
- Giao diện thiết kế bằng Impeccable; phong cách tạm thời sẽ ghi trong DESIGN.md.
