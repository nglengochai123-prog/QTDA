---
name: LAM Coffee
description: Bảng quản trị theo cách của Apple Business Manager (từ 26/10/2026, bản hai). Nền trắng, thanh trên có các phân hệ, thanh trái chữ thường liệt kê mục của phân hệ đang mở, thẻ trắng viền mảnh bo 16px, trang chủ là lưới thẻ chức năng có ô biểu tượng màu. Không dùng khối nền màu.
colors:
  bg: "#ffffff"
  surface: "#ffffff"
  surface-2: "#f5f5f7"
  surface-3: "#ededf0"
  sidebar: "#ffffff"
  fg: "#1d1d1f"
  fg-2: "#515154"
  fg-3: "#6e6e73"
  border: "#e5e5ea"
  border-row: "#ededf0"
  border-strong: "#d2d2d7"
  border-input: "#c7c7cc"
  primary: "#0066cc"
  primary-press: "#0058b0"
  danger: "#c4211a"
  ok: "#1b7f3b"
  warn: "#a05a00"
  series: ["#2a78d6", "#eb6834", "#1baf7a"]
  series-muted: "#c9c9ce"
  app-tones: { blue: "#3d9bff→#0a6cf0", orange: "#ffa733→#f27a00", green: "#3ed46a→#20a548", teal: "#3cc4dc→#1597b8", indigo: "#7b79f0→#5150d6", red: "#ff6259→#e3352b", pink: "#ff5c86→#e23463", gray: "#a1a1a8→#75757c" }
typography:
  family: "-apple-system, BlinkMacSystemFont, SF Pro Text, Segoe UI, system-ui, Roboto (chữ hệ thống, không tải phông)"
  numbers: "tabular-nums ở mọi nơi"
  scale_desktop: { xs: "12px", sm: "13px", base: "14px", md: "15px", lg: "17px", xl: "24px", 2xl: "28px" }
  scale_phone: { sm: "13.5px", base: "15px", md: "16px", lg: "18px", xl: "22px", 2xl: "26px" }
rounded:
  radius: "8px (nút, ô nhập, mục thanh trái, thẻ phân hệ), 10px (ô tìm kiếm), 11px (ô biểu tượng), 12px (thông báo), 16px (thẻ, ô số liệu)"
spacing:
  tap: "32px máy tính, 44px điện thoại"
  header: "56px máy tính, 54px điện thoại"
  sidebar: "256px (224px dưới 1200px)"
  bottom-nav: "60px"
---

# Design System: LAM Coffee

> **Cập nhật 26/10/2026, bản hai (bản hiện hành).** Hai gửi ảnh Apple Business Manager và nhận xét bản trước vẫn "giống AI": các khung chức năng có nền màu nhạt (xanh, vàng, đỏ, lục). Bản này học theo Apple: nền trắng, thanh trên chứa các phân hệ, thanh trái chỉ có chữ, thông báo và cờ trạng thái nền trắng hoặc xám, màu chỉ còn ở chấm trạng thái, biểu tượng và ô biểu tượng của thẻ chức năng. Bản thanh bên mở gập (bản một cùng ngày) và bản giấy ấm (commit `3c1b32a`) còn trong lịch sử Git.

Nguồn sự thật trong mã: biến `:root` ở đầu `static/css/app.css`, khung trang `templates/base.html`, danh sách phân hệ, mô tả và màu ô biểu tượng `apps/core/context_processors.py`, biểu tượng `templates/partials/icons.html`, biểu đồ `apps/reports/charts.py` cùng `templates/reports/charts/` và `static/js/charts.js`.

## Ý tưởng

Giao diện lùi lại sau số liệu. Apple Business Manager trông chuyên nghiệp nhờ ba điều: mọi khung đều trắng, khoảng trắng rộng và đều, chữ có thứ bậc rõ (tiêu đề đậm lớn, mô tả xám nhỏ). Màu không dùng để tô khung; màu chỉ xuất hiện ở chỗ nhỏ có ý nghĩa: ô biểu tượng của từng chức năng, chấm trạng thái, nút chính xanh.

Giao diện chỉ hiện kết quả, không hiện cách tính: không công thức, không ký hiệu mô hình (s, S, σ, CSL), không tên phương pháp dự báo. Tham số của mô hình sửa trong `apps/core/params.py`, không có trên giao diện.

## Nguyên tắc

1. **Không khối nền màu.** Thông báo, dải báo đầu trang, cờ trạng thái, ô số liệu cần chú ý đều nền trắng hoặc xám `--surface-2`; trạng thái thể hiện bằng chấm tròn 6–8px và chữ. Ngoại lệ duy nhất: dải "Mất kết nối" nền đỏ vì phải thấy ngay.
2. **Một màu hành động.** Xanh `--primary` cho nút chính, liên kết, tiêu điểm. Không thêm màu nhấn thứ hai.
3. **Trạng thái có chữ đi kèm.** Đỏ cho quá hạn, lỗi, hết hàng; hổ phách cho sắp hết hạn, chờ xử lý; xanh lá cho đạt. Không bao giờ chỉ là màu.
4. **Phẳng.** Thẻ không bóng, chỉ viền 1px; thẻ chức năng có bóng nhẹ khi rê chuột; lớp nổi (menu tài khoản, chú thích biểu đồ) mới có bóng rõ.
5. **Chữ hệ thống.** SF trên iPhone và Mac, Segoe UI trên Windows, Roboto trên Android. Không tải phông.
6. **Mọi con số dẫn tới danh sách gốc** (NFR-19).
7. **Thao tác một tay trên điện thoại.** Đích chạm 44px, nút chính rộng hết khung, thanh điều hướng dưới tối đa 5 mục.

## Màu

| Token | Giá trị | Dùng cho |
|---|---|---|
| `--bg`, `--surface`, `--sidebar` | `#ffffff` | Nền trang, thẻ, bảng, thanh trên, thanh trái |
| `--surface-2` | `#f5f5f7` | Rê chuột, nền cờ trạng thái, nhãn phân hệ, ô số trong thẻ |
| `--surface-3` | `#ededf0` | Mục đang chọn: thẻ phân hệ trên thanh trên, mục thanh trái, ảnh đại diện |
| `--fg`, `--fg-2`, `--fg-3` | `#1d1d1f`, `#515154`, `#6e6e73` | Chữ chính, phụ, mờ |
| `--border`, `--border-row`, `--border-strong`, `--border-input` | `#e5e5ea`, `#ededf0`, `#d2d2d7`, `#c7c7cc` | Viền thẻ, kẻ dòng, viền nút phụ và nút tên, viền ô nhập |
| `--primary` | `#0066cc` | Nút chính, liên kết, tiêu điểm |
| `--danger`, `--warn`, `--ok` | | Chấm và chữ trạng thái |
| `.tone-*` | 8 cặp chuyển màu dọc | Chỉ cho ô biểu tượng 44px của thẻ chức năng, mỗi phân hệ một màu: Tổng quan xanh dương, Bán hàng cam, Ca và nhân sự lục, Kho xanh ngọc, Dự báo chàm, Kiểm soát đỏ, Báo cáo hồng, Quản trị xám |

`theme-color` của PWA là `#ffffff`.

## Chữ

- Tiêu đề trang 28px, đậm 700, giãn chữ −0,025em. Tiêu đề thanh trái 21px đậm 700. Tiêu đề mục trang chủ 19px đậm 700.
- Tiêu đề thẻ 15px, đậm 600; dòng mô tả dưới tiêu đề 13px màu `--fg-3`.
- Thân chữ 14px, dòng 1,47. Trên điện thoại 15px.
- Đầu cột bảng 12px, đậm 600, màu `--fg-3`, nền trắng, không viết hoa.
- Số lớn trong ô số liệu 26px, đậm 600 (21px trên điện thoại), dạng bảng (`tabular-nums`).

## Bố cục

- **Máy tính (từ 900px):**
  - **Thanh trên** 56px dính đầu trang, nền trắng mờ, viền dưới mảnh. Trái: biểu tượng ly cà phê nét mảnh và chữ "LAM Coffee" (không có ô vuông đen). Giữa: các phân hệ theo quyền (Trang chủ, Bán hàng, Ca, nhân sự, Kho, Dự báo, Kiểm soát, Báo cáo, Quản trị); phân hệ đang mở là viên xám `--surface-3`. Phải: Cảnh báo, Duyệt, Tham số, nút tên có viền và ảnh đại diện tròn xám.
  - **Thanh trái** 256px nền trắng, viền phải mảnh. Tiêu đề là tên phân hệ đang mở (21px đậm), dưới là các mục chữ thường, không biểu tượng; mục đang mở nền `--surface-3`, chữ đậm.
  - **Nội dung** đệm 28–36px, rộng tối đa 1440px.
  - Dưới 1200px: thanh trái 224px, nút tên ẩn chỉ còn ảnh đại diện, thanh phân hệ cuộn ngang nếu thiếu chỗ.
- **Điện thoại (dưới 900px):** ẩn thanh phân hệ và thanh trái. Thanh trên 54px còn biểu tượng, tên quán và công cụ; các mục của phân hệ đang mở là thẻ gạch chân cuộn ngang; thanh điều hướng dưới 60px với 4 mục ưu tiên và "Tất cả".
- **Trang chủ:** lời chào và ngày; "Việc chờ tôi xử lý" là lưới ô trắng (số lớn, chấm đỏ khi gấp); "Chức năng" là lưới thẻ như danh sách ứng dụng của Apple Business Manager: ô biểu tượng màu bo 11px, tên đậm, một dòng mô tả xám, nhãn phân hệ. Phía trên lưới có thẻ gạch chân lọc theo phân hệ và ô tìm kiếm bo tròn; lọc chạy ngay trên trình duyệt. Trên điện thoại thẻ thành danh sách gọn một cột, ẩn nhãn phân hệ.
- **Lưới:** `.grid-2`, `.grid-3` như cũ; dưới 1000px thành một cột với `minmax(0, 1fr)`.
- **Thẻ (`.card`, `.panel`):** nền trắng, viền 1px `--border`, bo 16px, không bóng.
- **Ô số liệu (`.stat`, `.mini-stat`):** ô cần chú ý có chấm màu trước nhãn, không vạch màu bên trái.
- **Bảng (`.data-table`):** đầu cột nền trắng, dòng 46px, kẻ dòng mảnh, số căn phải, luôn trong `.table-wrap`.

## Thành phần

- **Nút chính:** nền xanh, chữ trắng, cao 34px (44px trên điện thoại), bo 8px. **Nút phụ** (`.btn-quiet`): nền trắng viền `--border-strong`.
- **Ô nhập:** viền `--border-input`, bo 8px; tiêu điểm viền xanh và vòng sáng xanh nhạt. **Ô tìm kiếm** (`.search-field`): bo 10px, kính lúp xám bên trái.
- **Thẻ gạch chân (`.seg`, `.sub-tabs`):** chữ xám, mục đang chọn chữ đen đậm có gạch dưới 2px. Dùng cho chọn kỳ, chọn chiều xem báo cáo, lọc trạng thái, lọc phân hệ.
- **Cờ trạng thái (`.pill`, `.badge`, `.chip-*`, `.flag-low`):** nền xám, chấm tròn 6px màu trạng thái, chữ màu trạng thái đậm.
- **Thông báo (`.notice`):** nền trắng, viền mảnh, bo 12px; chấm hoặc biểu tượng màu trạng thái ở đầu, chữ màu thường.
- **Dải báo đầu trang** (món sẵn sàng, chờ duyệt, báo nhanh nguyên liệu, dữ liệu chạy thử): nền trắng, kẻ dưới, biểu tượng màu trạng thái.
- **Biểu tượng:** nét 1,7–1,8px, đầu tròn, SVG trong `icons.html`. Mục điều hướng không có biểu tượng cùng tên lấy biểu tượng ở `ICONS` trong `context_processors.py`. Không dùng emoji.

## Biểu đồ

Biểu đồ vẽ sẵn thành SVG ở máy chủ (`apps/reports/charts.py`), không dùng thư viện JavaScript; trang vẫn đọc được khi mạng chậm và in ra được.

**Chọn loại theo câu hỏi:**

| Câu hỏi | Loại | Ví dụ |
|---|---|---|
| Thay đổi theo thời gian | Đường, có đường xám cho kỳ trước | Doanh thu theo ngày, giá trị tồn, thời gian chờ |
| So sánh các mốc rời | Cột | Doanh thu theo khung giờ, số ly theo giờ, lịch hết hạn theo tuần |
| Thành phần trong tổng theo thời gian | Cột chồng | Xuất kho (tiêu hao, hao hụt), người có mặt theo vai trò |
| Xếp hạng | Thanh ngang, sắp giảm dần | Món mang lại doanh thu, hao hụt theo nguyên liệu |
| So với một ngưỡng | Thanh ngang có vạch | Số ngày đủ dùng so với thời gian giao hàng |
| Cơ cấu một tổng | Thanh tỷ lệ | Phương thức thanh toán, nhóm món |
| Hai chiều rời (thứ × giờ) | Bản đồ nhiệt một màu | Giờ đông khách |
| Hai đại lượng của cùng một món | Biểu đồ chấm chia bốn ô | Ma trận thực đơn |
| Khoảng không chắc chắn | Dải khoảng có chấm giữa | Nhu cầu 7 ngày tới (phân vị 10 tới 90) |
| Lịch của từng lô | Thanh theo thời gian có mốc hạn | Lịch dùng dự kiến của các lô |
| Một con số | Ô số liệu, không vẽ biểu đồ | Doanh thu tháng, số đơn |

**Quy tắc:**

- **Màu theo vai trò.** Chuỗi thứ nhất `--series-1` xanh, thứ hai `--series-2` cam, thứ ba `--series-3` xanh lục; kỳ trước, chuẩn, phần còn lại màu xám `--series-muted`. Bộ ba màu đã kiểm tra phân biệt được với người mù màu đỏ lục. Màu trạng thái (`--status-*`) chỉ dùng cho trạng thái như khung quá tải, lô quá hạn, không dùng làm màu chuỗi.
- **Một trục tung.** Không bao giờ hai trục; hai đại lượng khác đơn vị thì hai biểu đồ.
- **Nét mảnh.** Đường 2px, cột bo 4px ở đầu dữ liệu, khe trắng 2px giữa các phần chồng nhau, lưới ngang nhạt `--grid`, trục `--axis`.
- **Nhãn chọn lọc.** Chỉ ghi số ở điểm cuối hoặc điểm đáng chú ý, nhãn trục thưa vừa đủ và luôn có nhãn mốc cuối. Chữ dùng màu chữ, không dùng màu chuỗi.
- **Chú thích.** Từ hai chuỗi trở lên luôn có chú thích; một chuỗi thì tiêu đề thẻ đã nói rõ.
- **Rê chuột, chạm để xem số.** Mỗi điểm, cột, ô có `data-tip`; `static/js/charts.js` hiện khung chú thích. Vùng bắt chuột lớn hơn hình vẽ.
- **Có bảng đi kèm** cho số liệu cần đọc chính xác (bảng ngày, bảng chi tiết theo món).

**Kích thước:** biểu đồ vẽ theo bề rộng thẻ chứa nó: `WIDE` 1080 cho thẻ hết bề ngang, `HALF` 540 cho `.grid-2`, `THIRD` 360 cho `.grid-3`. Mỗi SVG nằm trong `.chart-box`; dưới 600px khung cuộn ngang với bề rộng tối thiểu 520px (360px cho biểu đồ hẹp) thay vì co chữ quá nhỏ. Mọi mẫu biểu đồ kiểm tra `{% if c %}` nên không có dữ liệu thì không vẽ khung rỗng.

## Chuyển động

120–150ms cho đổi màu nền, viền và bóng thẻ chức năng. Không trượt, không phóng to. Tắt hẳn khi người dùng chọn giảm chuyển động.

## Nên và không nên

**Nên:** dùng token thay mã màu; mọi trạng thái có chữ; đặt bảng rộng trong `.table-wrap`; chọn loại biểu đồ theo bảng ở trên; kiểm tra ở 375px và 1366px, không để trang cuộn ngang.

**Không nên:** tô nền màu cho khung, thông báo hay dải báo; thêm màu nhấn mới; dùng màu trạng thái cho chuỗi dữ liệu; biểu đồ hai trục; biểu đồ tròn nhiều lát; chữ số trên mọi điểm; chuyển màu ngoài ô biểu tượng của thẻ chức năng; nền họa tiết; emoji làm biểu tượng; tải phông từ mạng ngoài; đưa công thức, ký hiệu mô hình hay tên phương pháp lên giao diện.
