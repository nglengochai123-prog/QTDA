---
name: LAM Coffee
description: Giao diện quản trị vuông vức, chắc chắn. Nền sáng, chữ đậm, một màu nhấn, góc vuông, phân tách bằng đường kẻ.
source: UI UX Pro Max 2.13.0, kiểu "Minimalism & Swiss Style", bảng màu "B2B Service" (chế độ sáng), mật độ 8/10, chuyển động 2/10
colors:
  bg: "#f8fafc"
  surface: "#ffffff"
  surface-2: "#f1f5f9"
  fg: "#0f172a"
  fg-2: "#334155"
  fg-3: "#5b6678"
  border: "#e2e8f0"
  border-strong: "#cbd5e1"
  border-input: "#64748b"
  primary: "#0f172a"
  primary-press: "#1e293b"
  primary-soft: "#e8ecf1"
  on-primary: "#ffffff"
  on-primary-2: "#cbd5e1"
  accent: "#0369a1"
  accent-press: "#075985"
  accent-soft: "#e0f2fe"
  danger: "#b91c1c"
  danger-soft: "#fef2f2"
  ok: "#15803d"
  ok-soft: "#ecfdf3"
  warn: "#b45309"
  warn-soft: "#fffbeb"
typography:
  family: "\"Segoe UI\", system-ui, -apple-system, \"SF Pro Text\", Roboto, \"Noto Sans\", \"Helvetica Neue\", Arial, sans-serif"
  numbers: "tabular-nums ở mọi nơi"
  scale: { sm: "0.875rem", base: "1rem (1.0625rem trên điện thoại)", md: "1.125rem", lg: "1.3rem", xl: "1.55rem", 2xl: "1.85rem" }
rounded:
  radius: "2px"
spacing:
  tap: "48px"
  header: "56px"
  nav: "232px"
  bottom-nav: "64px"
---

# Design System: LAM Coffee

Áp dụng từ 12/10/2026 theo yêu cầu của Chủ quán: **phong cách quản trị vuông vức, chắc chắn**, thay cho định hướng tạm "vở ô ly, mực tím, lề đỏ". Nguồn sự thật trong mã: biến `:root` ở `static/css/app.css`, `templates/base.html`, `templates/admin/base_site.html`. Khi quán có logo hoặc màu nhận diện chính thức, chỉ thay giá trị token; cấu trúc và quy tắc dưới đây giữ nguyên.

Thư mục `.impeccable/` (kể cả `design.json`) là hồ sơ của định hướng cũ, giữ lại làm lịch sử; không còn là chuẩn.

## Căn cứ chọn

Chạy UI UX Pro Max với truy vấn "operations admin dashboard square enterprise", mật độ 8, độ biến tấu 2, chuyển động 2:

- **Kiểu:** Minimalism & Swiss Style (gợi ý cho ứng dụng doanh nghiệp, bảng điều khiển, công cụ chuyên nghiệp): lưới rõ, tương phản cao, hình học, chữ không chân, chỉ giữ thứ cần thiết.
- **Màu:** công cụ gợi ý bảng tối cho bảng điều khiển; quán dùng ở quầy ban ngày và trên điện thoại nên chọn bảng **B2B Service** (sáng) trong cùng bộ kết quả màu "admin dashboard light professional": chữ `#020617`/`#0f172a`, nền `#f8fafc`, viền `#e2e8f0`, nhấn `#0369a1`, đỏ `#dc2626` (dùng bản đậm hơn `#b91c1c` cho tương phản chữ).
- **Chữ:** công cụ gợi ý Fira Sans/Fira Code. Không dùng vì phải tải phông từ mạng (PWA cần chạy khi mạng chập chờn, NFR-16); giữ phông hệ thống có đủ dấu tiếng Việt (Segoe UI trên Windows, Roboto trên Android, SF trên iPhone).
- **Quy tắc UX áp dụng:** tương phản chữ tối thiểu 4.5:1; đích chạm tối thiểu 44px (dự án giữ 48px); bảng rộng cuộn ngang trong khung, không vỡ trang; chữ thân tối thiểu 16px trên điện thoại; tôn trọng giảm chuyển động; không dùng emoji làm biểu tượng.

## Nguyên tắc

1. **Vuông vức.** Mọi góc bo 2px (gần như vuông). Không có viên thuốc, không bo tròn lớn.
2. **Chắc chắn.** Phẳng, không bóng. Khối được phân tách bằng đường kẻ 1px và nền xám rất nhạt cho phần đầu khối, không dùng bóng đổ.
3. **Một màu hành động, một màu nhấn.** Màu chính (`--primary`, xanh đen) cho thanh đầu trang, nút chính, lựa chọn đang chọn, mục điều hướng đang mở. Màu nhấn (`--accent`, xanh dương đậm) chỉ cho liên kết, viền tiêu điểm và quầng ô nhập.
4. **Trạng thái không chỉ bằng màu.** Đỏ (`--danger`) chỉ cho lỗi, mất kết nối, nguyên liệu hết; hổ phách (`--warn`) cho chờ xử lý, quá hạn, dưới tồn an toàn; xanh lá (`--ok`) cho thành công. Mỗi trạng thái luôn có chữ, và cờ trạng thái là ô viền vuông có chữ (`.flag-low`).
5. **Dày đặc nhưng đọc được.** Bảng số liệu có hàng đầu nền xám, số căn phải, số dạng bảng. Nhãn trường luôn hiển thị, không chỉ dùng chữ gợi ý.
6. **Thao tác một tay.** Đích chạm 48px, nút chính rộng hết khung trên điện thoại, thanh điều hướng dưới tối đa 5 mục.

## Màu

| Token | Giá trị | Dùng cho |
|---|---|---|
| `--bg` | `#f8fafc` | Nền trang |
| `--surface` | `#ffffff` | Khối, bảng, ô nhập, phiếu |
| `--surface-2` | `#f1f5f9` | Đầu khối, hàng đầu bảng, hover |
| `--fg`, `--fg-2`, `--fg-3` | `#0f172a`, `#334155`, `#5b6678` | Chữ chính, chữ phụ, chữ mờ (đều ≥ 4.5:1 trên nền trắng) |
| `--border`, `--border-strong` | `#e2e8f0`, `#cbd5e1` | Kẻ phân tách, viền khối |
| `--border-input` | `#64748b` | Viền ô nhập, nút phụ, ô chọn (≥ 3:1 cho thành phần điều khiển) |
| `--primary`, `--primary-press`, `--primary-soft` | `#0f172a`, `#1e293b`, `#e8ecf1` | Thanh đầu trang, nút chính, lựa chọn đang chọn, mục điều hướng đang mở |
| `--accent`, `--accent-press`, `--accent-soft` | `#0369a1`, `#075985`, `#e0f2fe` | Liên kết, viền tiêu điểm, quầng ô nhập, số nổi bật |
| `--danger`, `--warn`, `--ok` và bản `-soft` | | Trạng thái, luôn kèm chữ |

`theme-color` của PWA và màu trang dữ liệu nền (Django admin) dùng cùng bảng màu này.

## Chữ

Một họ chữ hệ thống, số dạng bảng (`tabular-nums`) toàn ứng dụng để cột tiền thẳng hàng. Tiêu đề trang 1.55rem đậm 700; tiêu đề khối 1.125rem trong dải đầu khối; chữ thân 16px (17px trên điện thoại); chữ phụ 14px, không nhỏ hơn.

## Bố cục

- **Máy tính:** thanh đầu trang xanh đen 56px; cột điều hướng trái 232px, mục đang mở có vạch 3px màu chính bên trái; nội dung tối đa 1100px (quầy pha chế và báo cáo rộng hơn khi cần).
- **Điện thoại:** thanh điều hướng dưới 64px, tối đa 5 mục theo vai trò, mục đang mở có vạch 3px phía trên.
- **Khối (`.panel`):** nền trắng, viền 1px, dải đầu khối nền `--surface-2` có đường kẻ dưới. Khối cần chú ý (`.panel-warn`) có viền trái 4px màu hổ phách.
- **Ô số liệu (`.figure-grid`):** ô vuông viền 1px; chỉ số chính (`.figure-key`) có viền trái 4px màu chính.
- **Bảng (`.data-table`):** viền ngoài 1px, hàng đầu nền xám, chữ 14px đậm vừa, số căn phải; bảng rộng nằm trong `.table-wrap` cuộn ngang.
- **Biểu mẫu:** nhãn trên ô; ô cao 52px (ô nhỏ trong dòng 48px); lưới biểu mẫu tự chia cột từ 260px.

## Thành phần

- **Nút chính (`.btn-primary`):** nền xanh đen, chữ trắng, góc 2px; nhấn giữ hơi tối lại, không nhảy vị trí.
- **Nút phụ (`.btn-quiet`):** nền trắng, viền `--border-input`, hover nền `--surface-2`.
- **Ô nhập (`.input`):** viền 1px `--border-input`; tiêu điểm đổi viền sang màu nhấn kèm quầng 2px.
- **Thông báo (`.notice`):** viền 1px cùng màu chữ, viền trái 4px, nền nhạt theo trạng thái, có biểu tượng.
- **Chip, cờ trạng thái:** ô vuông viền 1px, chữ 14px; không dùng viên thuốc.
- **Lựa chọn dạng nút (`.pick`):** ô vuông viền `--border-input`; đang chọn thì nền màu chính, chữ trắng.
- **Phiếu order, phiếu ở quầy:** khối trắng viền 1px, không còn đường lề đỏ; mã đơn lớn, đậm.
- **Thanh so sánh (`.bar-track`):** vạch vuông, phần đầy màu chính.
- **Dải mất kết nối:** nền đỏ đậm, chữ trắng, có biểu tượng và chữ.
- **Trang đăng nhập:** thẻ trắng viền 1px, dải trên 4px màu chính, nền trang trơn.

## Chuyển động

150ms cho đổi màu nền và viền. Không trượt, không phóng to. Tắt hẳn khi người dùng chọn giảm chuyển động.

## Nên và không nên

**Nên:** dùng token thay vì mã màu trực tiếp; mọi trạng thái có chữ; giữ đích chạm 48px; đặt bảng rộng trong `.table-wrap`; kiểm tra ở 375px, 768px, 1024px, 1440px.

**Không nên:** bo góc lớn, bóng đổ, nền họa tiết, nhiều màu nhấn, chữ dưới 14px, nhãn chỉ bằng chữ gợi ý trong ô, emoji làm biểu tượng, chỉ dùng màu để báo trạng thái.
