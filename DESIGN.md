---
name: LAM Coffee
description: Vở ô ly của quán. Mực tím trên giấy trắng, lề đỏ, sửa sai bằng bút đỏ. Định hướng TẠM THỜI.
colors:
  paper: "#fcfcfe"
  paper-2: "#f4f2fa"
  ink: "#1e1a33"
  ink-2: "#4a4566"
  ink-3: "#6a6587"
  line: "#dcd8ea"
  line-strong: "#b9b2d6"
  violet: "#3f2a9e"
  violet-press: "#2f1f7a"
  violet-soft: "#ece8fb"
  on-violet: "#ffffff"
  on-violet-2: "#d9d2fb"
  margin: "#c62a26"
  margin-soft: "#fdecec"
  ok: "#1d7a3a"
  ok-soft: "#e6f4ea"
  warn: "#8f5200"
  warn-soft: "#fff3df"
  grid-fine: "rgba(90, 70, 190, 0.09)"
  grid-bold: "rgba(90, 70, 190, 0.17)"
typography:
  display:
    fontFamily: "\"Segoe UI\", system-ui, -apple-system, \"SF Pro Text\", Roboto, \"Noto Sans\", \"Helvetica Neue\", Arial, sans-serif"
    fontSize: "1.95rem"
    fontWeight: 750
    lineHeight: 1.25
    letterSpacing: "-0.01em"
    fontFeature: "tnum"
  headline:
    fontFamily: "\"Segoe UI\", system-ui, -apple-system, \"SF Pro Text\", Roboto, \"Noto Sans\", \"Helvetica Neue\", Arial, sans-serif"
    fontSize: "1.62rem"
    fontWeight: 700
    lineHeight: 1.25
    fontFeature: "tnum"
  title:
    fontFamily: "\"Segoe UI\", system-ui, -apple-system, \"SF Pro Text\", Roboto, \"Noto Sans\", \"Helvetica Neue\", Arial, sans-serif"
    fontSize: "1.35rem"
    fontWeight: 700
    lineHeight: 1.25
    fontFeature: "tnum"
  body:
    fontFamily: "\"Segoe UI\", system-ui, -apple-system, \"SF Pro Text\", Roboto, \"Noto Sans\", \"Helvetica Neue\", Arial, sans-serif"
    fontSize: "1rem"
    fontWeight: 400
    lineHeight: 1.5
    fontFeature: "tnum"
  label:
    fontFamily: "\"Segoe UI\", system-ui, -apple-system, \"SF Pro Text\", Roboto, \"Noto Sans\", \"Helvetica Neue\", Arial, sans-serif"
    fontSize: "1rem"
    fontWeight: 600
    lineHeight: 1.5
    fontFeature: "tnum"
  small:
    fontFamily: "\"Segoe UI\", system-ui, -apple-system, \"SF Pro Text\", Roboto, \"Noto Sans\", \"Helvetica Neue\", Arial, sans-serif"
    fontSize: "0.875rem"
    fontWeight: 400
    lineHeight: 1.5
    fontFeature: "tnum"
rounded:
  radius: "10px"
  radius-lg: "14px"
spacing:
  tap: "48px"
  header-h: "56px"
  nav-w: "232px"
  bottom-nav-h: "64px"
components:
  input:
    backgroundColor: "#ffffff"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.radius}"
    padding: "0.75rem 0.875rem"
    height: "52px"
  input-action:
    backgroundColor: "transparent"
    textColor: "{colors.violet}"
    height: "{spacing.tap}"
    width: "72px"
  button-primary:
    backgroundColor: "{colors.violet}"
    textColor: "{colors.on-violet}"
    rounded: "{rounded.radius}"
    padding: "0 1.25rem"
    height: "{spacing.tap}"
  button-primary-hover:
    backgroundColor: "{colors.violet-press}"
    textColor: "{colors.on-violet}"
  button-block:
    backgroundColor: "{colors.violet}"
    textColor: "{colors.on-violet}"
    rounded: "{rounded.radius}"
    height: "54px"
    width: "100%"
  button-quiet:
    backgroundColor: "transparent"
    rounded: "{rounded.radius}"
    padding: "0 1.25rem"
    height: "{spacing.tap}"
  notice-error:
    backgroundColor: "{colors.margin-soft}"
    textColor: "#8a1714"
    rounded: "{rounded.radius}"
    padding: "0.75rem 0.875rem"
  notice-ok:
    backgroundColor: "{colors.ok-soft}"
    textColor: "#14532a"
    rounded: "{rounded.radius}"
    padding: "0.75rem 0.875rem"
  notice-warn:
    backgroundColor: "{colors.warn-soft}"
    textColor: "#6b3d00"
    rounded: "{rounded.radius}"
    padding: "0.75rem 0.875rem"
  notice-info:
    backgroundColor: "{colors.violet-soft}"
    textColor: "{colors.violet-press}"
    rounded: "{rounded.radius}"
    padding: "0.75rem 0.875rem"
  chip:
    backgroundColor: "{colors.violet-soft}"
    textColor: "{colors.violet-press}"
    typography: "{typography.small}"
    rounded: "999px"
    padding: "0 0.625rem"
    height: "28px"
  label-card:
    backgroundColor: "#ffffff"
    textColor: "{colors.ink}"
    rounded: "{rounded.radius-lg}"
    padding: "1.75rem 1.5rem 1.5rem"
    width: "min(100%, 420px)"
  app-header:
    backgroundColor: "{colors.violet}"
    textColor: "{colors.on-violet}"
    height: "{spacing.header-h}"
  app-nav-item:
    textColor: "{colors.ink-2}"
    rounded: "{rounded.radius}"
    padding: "0 0.875rem"
    height: "{spacing.tap}"
  app-nav-item-active:
    backgroundColor: "{colors.violet-soft}"
    textColor: "{colors.violet-press}"
  bottom-nav-item-active:
    backgroundColor: "transparent"
    textColor: "{colors.violet}"
    height: "{spacing.bottom-nav-h}"
  offline-banner:
    backgroundColor: "{colors.margin}"
    textColor: "#ffffff"
    padding: "0.625rem 1rem"
  ruled-list-row:
    textColor: "{colors.ink}"
    padding: "0.5rem 0.25rem"
    height: "56px"
  empty-state:
    textColor: "{colors.ink-2}"
    rounded: "{rounded.radius-lg}"
    padding: "1.25rem"
---

# Design System: LAM Coffee

> **ĐỊNH HƯỚNG TẠM THỜI.** Toàn bộ hệ hình ảnh dưới đây (màu, chữ, thế giới "vở ô ly") là đề xuất tạm thời, dùng cho đến khi quán cung cấp logo, màu sắc hoặc font chính thức. Khi có nhận diện chính thức, nhận diện đó thay thế các token ở đây; cấu trúc (vai trò màu, kích thước chạm 48px, quy tắc trạng thái không chỉ bằng màu) nên được giữ lại.

Nguồn sự thật: `static/css/app.css` (biến `:root`), `templates/base.html`, `templates/admin/base_site.html`. Tên token và định danh CSS giữ nguyên như trong mã.

## Overview

**Creative North Star: "Vở ô ly của quán"**

Ứng dụng là cuốn vở học trò của quán: mực tím đậm trên giấy trắng lạnh, một đường lề đỏ ngăn phần điều hướng với phần nội dung, và khi có sai thì sửa bằng bút đỏ ngay bên cạnh chứ không tẩy xóa. Thế giới này được chọn để từ chối kiểu màn hình POS xám một màu nhấn; nhân viên mở ra phải nhận ngay "đây là vở của quán".

Mật độ vừa phải, thiên về thao tác nhanh bằng một tay: mọi đích chạm tối thiểu 48px, nút chính nằm trong vùng ngón cái trên điện thoại. Bề mặt phẳng, ranh giới bằng đường kẻ mảnh như dòng kẻ vở; chỉ có "nhãn vở" (thẻ đăng nhập) được nâng lên bằng bóng mờ. Lưới ô ly chỉ xuất hiện ở nền trống, không bao giờ nằm sau nội dung đang làm việc.

Mọi trạng thái quan trọng đi kèm chữ và biểu tượng, không chỉ bằng màu. Chuyển động ngắn (120 đến 160ms) và tắt hẳn khi người dùng chọn giảm chuyển động.

**Key Characteristics:**
- Mực tím (`--violet`) là màu hành động duy nhất: thanh tiêu đề, nút chính, liên kết, viền focus.
- Đỏ lề (`--margin`) dành cho lề, lỗi, mất kết nối và lời đính chính; không bao giờ là nút hành động.
- Một họ chữ hệ thống, số dạng bảng ở mọi nơi.
- Phẳng, phân tách bằng đường kẻ 1px; bóng chỉ cho nhãn vở.
- Đích chạm 48px, nút đăng nhập full-width 54px.

## Colors

Bảng màu học trò: giấy trắng hơi lạnh, mực tím đậm, lề đỏ, cộng hai màu trạng thái xanh lá và hổ phách.

### Primary
- **Mực tím** (`--violet`): thanh tiêu đề ứng dụng, nút chính, liên kết, viền focus 3px, màu caret, tên quán trên nhãn vở, mục điều hướng đang chọn ở điện thoại. Cũng là `theme-color` của PWA.
- **Mực tím đè** (`--violet-press`): hover của nút chính và liên kết; chữ trong chip, thông báo info và mục điều hướng đang chọn ở máy tính.
- **Tím nhạt** (`--violet-soft`): nền mục điều hướng đang chọn, nền chip, nền thông báo info, quầng focus của ô nhập, màu bôi chọn chữ.
- **Chữ trên tím** (`--on-violet`, `--on-violet-2`): chữ chính trên thanh tím; `--on-violet-2` cho chữ phụ (vai trò người dùng) trên thanh tím.

### Secondary
- **Đỏ lề** (`--margin`): đường lề 1px (cạnh phải cột điều hướng trên máy tính, cạnh trên thanh điều hướng dưới trên điện thoại, đường dọc trên nền ô ly), lỗi trường nhập, viền ô nhập không hợp lệ, dải "Mất kết nối", bút đỏ đính chính.
- **Hồng lề** (`--margin-soft`): nền thông báo lỗi.

### Tertiary (trạng thái)
- **Xanh đạt** (`--ok`, `--ok-soft`): trạng thái "Đạt"/thành công; `--ok-soft` là nền thông báo ok.
- **Hổ phách** (`--warn`, `--warn-soft`): cảnh báo; `--warn` cho số đếm cần chú ý trong danh sách kẻ dòng, `--warn-soft` là nền thông báo cảnh báo.

### Neutral
- **Giấy** (`--paper`): nền trang. **Giấy lót** (`--paper-2`): hover hàng/mục điều hướng, nền ô nhập bị vô hiệu.
- **Mực đen tím** (`--ink`): chữ chính. `--ink-2`: chữ phụ, mục điều hướng chưa chọn, số đếm. `--ink-3`: gợi ý, placeholder, viền ô nhập khi hover.
- **Dòng kẻ** (`--line`): đường kẻ giữa các hàng. `--line-strong`: viền ô nhập, viền nét đứt của trạng thái trống, thanh cuộn.
- **Lưới ô ly** (`--grid-fine`, `--grid-bold`): ô nhỏ 8px và ô lớn 32px trên nền trống.
- Trắng thuần `#fff` (giá trị trực tiếp, không phải token) dùng cho nền ô nhập, nhãn vở và thanh điều hướng dưới trên điện thoại, để nổi khỏi giấy `--paper`.

### Named Rules
**The Một Màu Mực Rule.** Chỉ mực tím được làm màu hành động. Đỏ, xanh, hổ phách là màu trạng thái, không bao giờ là nền nút.

**The Lề Đỏ Rule.** Đỏ lề chỉ mang năm nghĩa: đường lề, lỗi, mất kết nối, đính chính, và ghi chú viết tay cho pha chế (ví dụ "ít ngọt", "mang về"). Không dùng đỏ để trang trí hay nhấn mạnh; đơn trễ là cảnh báo nên dùng `--warn` kèm chữ "trễ".

**The Không Chỉ Bằng Màu Rule.** Mọi trạng thái quan trọng (lỗi, mất kết nối, cảnh báo) có chữ, và có biểu tượng khi là thông báo hoặc dải cảnh báo.

## Typography

**Display Font:** cùng họ chữ thân (`--font`: "Segoe UI", system-ui, -apple-system, "SF Pro Text", Roboto, "Noto Sans", "Helvetica Neue", Arial, sans-serif)
**Body Font:** `--font`
**Label/Mono Font:** không có họ riêng; số dùng `font-variant-numeric: tabular-nums` trên `body`.

**Character:** Chữ hệ thống quen mắt, hiển thị tốt tiếng Việt có dấu trên Windows, Android và iOS; phân cấp bằng cỡ và độ đậm (600, 650, 750), không bằng họ chữ thứ hai.

### Hierarchy
Thang cỡ (`--text-sm` 0.875rem, `--text-base` 1rem, `--text-md` 1.125rem, `--text-lg` 1.35rem, `--text-xl` 1.62rem, `--text-2xl` 1.95rem), tỉ lệ xấp xỉ 1.2.
- **Display** (750, `--text-2xl`): tên quán trên nhãn vở; lời chào trang chủ dùng cùng cỡ ở độ đậm mặc định của h1.
- **Headline** (`--text-xl`, line-height 1.25, `text-wrap: balance`): h1 trang.
- **Title** (`--text-lg`, cách trên 2rem): h2 chia phần.
- **Body** (400, `--text-base`, line-height 1.5): chữ thường. Dưới 900px, cỡ thân tăng lên 1.0625rem cho điện thoại. Khối chữ dài tối đa 65ch.
- **Label** (600, `--text-base`): nhãn trường nhập, mục điều hướng; nút dùng 650.
- **Small** (`--text-sm`): gợi ý, lỗi trường (600, đỏ lề), chip, vai trò người dùng, nút trong ô nhập. Ô nhập dùng `--text-md` để dễ đọc khi gõ.

### Named Rules
**The Một Họ Chữ Rule.** Toàn ứng dụng dùng một chồng chữ hệ thống `--font`. Không thêm font web cho đến khi quán có font chính thức.

**The Số Dạng Bảng Rule.** Số luôn dạng bảng (`tabular-nums`) để cột tiền, số lượng, mã đơn thẳng hàng.

## Layout

- **Điểm gãy duy nhất: 900px.** Từ 900px trở lên là bố cục máy quầy; dưới 900px (`max-width: 899px`) là bố cục điện thoại. Mục tiêu tối thiểu 1366×768 trên máy quầy và 375px trên điện thoại, không cuộn ngang.
- **Khung máy tính:** thanh tiêu đề tím dính trên cùng (`--header-h`), dưới là lưới hai cột: cột điều hướng rộng `--nav-w`, nội dung `minmax(0, 1fr)`. Nội dung tối đa 1100px, đệm `1.5rem clamp(1rem, 3vw, 2.5rem) 3rem`.
- **Khung điện thoại:** cột điều hướng thành thanh điều hướng dưới cố định cao `--bottom-nav-h`, chia đều cột, tôn trọng `safe-area-inset-bottom`; thân trang chừa đệm dưới tương ứng. Nội dung đệm `1.25rem 1rem 2rem`.
- **Trang nền trống (đăng nhập, ngoại tuyến):** nhãn vở ở giữa nền ô ly. Trên điện thoại thấp hơn 720px, nhãn vở dồn xuống đáy để nút nằm trong vùng ngón cái; từ 720px trở lên thì căn giữa.
- **Nhịp khoảng cách:** không có thang token; các giá trị lặp lại là 0.25, 0.5, 0.75, 1, 1.25, 1.5rem. Trường nhập cách nhau 1.125rem.
- **Đích chạm:** `--tap` 48px là tối thiểu cho mọi nút, nút trong ô nhập, mục điều hướng; hàng danh sách 56px; nút full-width 54px; ô nhập 52px.

### Named Rules
**The Ô Ly Nền Trống Rule.** Lưới ô ly (`--grid-fine` 8px, `--grid-bold` 32px, cùng đường lề đỏ dọc mờ 55%) chỉ phủ trang không có nội dung làm việc: đăng nhập và ngoại tuyến (`.page-login`). Không đặt lưới sau bảng, danh sách hay biểu mẫu trong khung ứng dụng.

**The 48px Rule.** Không đích chạm nào nhỏ hơn `--tap`.

## Elevation & Depth

Hệ phẳng. Độ sâu đến từ màu nền (giấy, giấy lót, trắng) và đường kẻ 1px, không từ bóng. Thanh tiêu đề dính và dải mất kết nối đều không có bóng.

### Shadow Vocabulary
- **Nhãn vở** (`--shadow`: `0 1px 2px rgba(30, 26, 51, 0.06), 0 6px 18px rgba(30, 26, 51, 0.08)`): chỉ dùng cho nhãn vở nằm trên nền ô ly.

### Named Rules
**The Giấy Phẳng Rule.** Trong khung ứng dụng, bề mặt nằm phẳng trên giấy. Bóng mờ chỉ thuộc về nhãn vở.

## Shapes

Góc bo vừa, thân thiện: `--radius` (10px) cho ô nhập, nút, thông báo, mục điều hướng; `--radius-lg` (14px) cho nhãn vở và khung trạng thái trống. Chip bo tròn hẳn (999px). Nút trong ô nhập và mục điều hướng dưới dùng 8px. Viền ô nhập và nút dày 1.5px. Viền đôi tím 4px (`double`) là chữ ký riêng của nhãn vở. Trạng thái trống dùng viền nét đứt 1.5px `--line-strong`, như ô chưa viết. Biểu tượng là SVG nét 2px, đầu tròn, cỡ 1.25em, theo màu chữ.

## Components

### Buttons
Chắc tay, một màu mực.
- **Shape:** bo `--radius`, viền 1.5px, cao tối thiểu `--tap`, chữ 650.
- **Primary** (`.btn-primary`): nền `--violet`, chữ `--on-violet`; hover `--violet-press`. Nhấn: dịch xuống 1px.
- **Block** (`.btn-block`): full-width, cao 54px, chữ `--text-md`; dùng cho hành động chính duy nhất của nhãn vở (Đăng nhập, Thử lại).
- **Quiet** (`.btn-quiet`): nền trong, viền theo màu chữ; trên thanh tím là nút Đăng xuất với viền trắng 45%, hover nền trắng 12%.
- **Bận / vô hiệu:** `aria-busy="true"` hoặc `disabled` làm mờ 60%; biểu mẫu `data-once` đổi chữ nút sang `data-busy-text` để chống bấm hai lần.

### Inputs / Fields
- **Style:** nền trắng, viền 1.5px `--line-strong`, bo `--radius`, cao tối thiểu 52px, chữ `--text-md`. Nhãn 600 ở trên, gợi ý `--ink-3` cỡ nhỏ ở dưới.
- **Hover / Focus:** hover viền `--ink-3`; focus viền `--violet` cộng quầng 3px `--violet-soft`.
- **Error / Disabled:** `aria-invalid="true"` viền `--margin`, chữ lỗi đỏ lề 600; vô hiệu nền `--paper-2`, chữ `--ink-3`.
- **Input-with-action:** nút chữ nằm trong ô nhập bên phải (Hiện/Ẩn mật khẩu), nền trong, chữ `--violet` 600, cao `--tap`, rộng tối thiểu 72px, hover `--violet-soft`; ô nhập chừa đệm phải 5.5rem. Nút chỉ hiện khi có JavaScript và có `aria-pressed`.

### Notices
- **Style:** hộp phẳng bo `--radius`, đệm `0.75rem 0.875rem`, chữ 500, có biểu tượng bên trái.
- **Biến thể:** `notice-error` (nền `--margin-soft`), `notice-ok` (`--ok-soft`), `notice-warn` (`--warn-soft`), `notice-info` (`--violet-soft`, chữ `--violet-press`). Chữ của error/ok/warn là màu đậm viết trực tiếp trong CSS, chưa thành token.

### Chips
- **Style:** viên thuốc cao 28px, nền `--violet-soft`, chữ `--violet-press` 600 cỡ nhỏ. Hiện dùng để liệt kê vai trò trên trang chủ máy tính (ẩn trên điện thoại vì thanh tiêu đề đã hiện vai trò). Chip không có trạng thái chọn; lựa chọn dùng nút chọn (xem Pick).

### Pick (nút chọn bàn, kích cỡ, tùy chọn)
- **Style:** ô cao tối thiểu 48px, nền trắng, viền 1.5px `--line-strong`, bo `--radius`, chữ 600. Đang chọn: nền `--violet`, chữ trắng, dòng phụ `--on-violet-2`. Hết nguyên liệu: nền `--paper-2`, viền nét đứt, chữ gạch ngang, không bấm được.
- Input radio hoặc checkbox thật nằm dưới, nên bàn phím và trình đọc màn hình dùng được như điều khiển chuẩn.

### Order ticket (phiếu order) và bar ticket (phiếu ở quầy)
- Cùng một tờ phiếu: nền trắng phẳng trên `--paper`, viền 1px `--line-strong`, bo `--radius-lg`, đường lề đỏ 1px bên trái, không đổ bóng (Giấy Phẳng Rule).
- Phiếu order (điện thoại): tiêu đề, bàn đang chọn, các dòng `N×` mực tím, tên món và cỡ, tùy chọn và ghi chú dòng phụ, giá, nút bỏ 48px. Thanh nút cố định ở vùng ngón cái: khi đang mở một món nó là nút "Thêm N ly · tiền" (biểu tượng cộng), khi không mở món nó là "Gửi pha chế · N ly · tổng" (biểu tượng gửi).
- Phiếu ở quầy (máy tính): mã đơn `--text-2xl` mực tím là danh tính chính, bàn, thời gian chờ; số lớn bên trái luôn là số ly còn phải pha; tiến độ viết bằng chữ "Đã xong d/q ly · còn p". Phiếu mới: nền `--violet-soft`, viền tím, chữ "Mới", một chuyển động 160ms chỉ lần đầu xuất hiện. Phiếu chờ từ 10 phút: thời gian bằng `--warn` kèm chữ "trễ".


### Ruled list (danh sách kẻ dòng)
- Như dòng kẻ vở: không viền hộp, chỉ đường `--line` 1px trên và dưới mỗi hàng. Hàng cao 56px, nhãn trái, số đếm phải (`--ink-2` 600, kèm mũi tên), số cần chú ý chuyển `--warn`. Hover nền `--paper-2`.

### Empty state
- Khung nét đứt 1.5px `--line-strong`, bo `--radius-lg`, đệm 1.25rem, chữ `--ink-2`, ý chính in đậm `--ink`, rộng tối đa 65ch. Nói rõ việc gì sẽ xuất hiện và người dùng cần làm gì lúc này.

### Correction (bút đỏ đính chính)
- `.correction del`: giá trị cũ màu `--margin`, gạch ngang 2px đỏ, vẫn đọc được. `.correction ins`: giá trị mới màu `--margin`, đậm 650, không gạch chân, viết ngay bên cạnh (cách 0.35em). Không tẩy, không ẩn giá trị cũ.

### Offline banner (dải mất kết nối)
- Dải đỏ `--margin` chữ trắng 600, có biểu tượng mất sóng và câu hướng dẫn dùng phiếu dự phòng. Trong khung ứng dụng dính ngay dưới thanh tiêu đề; trên trang đăng nhập cố định ở đỉnh. Hiện trong vòng 10 giây khi mất mạng (kiểm tra `healthz` mỗi 5 giây) và đặt lớp `is-offline` lên `<html>`. Trang `pwa/offline.html` là nhãn vở với thông báo lỗi và nút Thử lại.

### Navigation
- **App header:** thanh `--violet` cao `--header-h`, dính trên cùng. Trái: tên quán (750, `--text-md`, trắng). Phải: tên người dùng (600) và vai trò (`--on-violet-2`, cỡ nhỏ), rồi nút Đăng xuất quiet. Focus trên thanh dùng viền trắng. Trên điện thoại: chỉ hiện tên gọi ngắn, xếp chồng trên vai trò, căn phải.
- **Máy tính, cột trái:** nền `--paper`, ngăn với nội dung bằng lề đỏ 1px. Mục cao `--tap`, chữ `--ink-2` 600 kèm biểu tượng; hover `--paper-2`; đang chọn nền `--violet-soft`, chữ `--violet-press`.
- **Điện thoại, thanh dưới:** nền trắng, viền trên đỏ lề 1px, các mục chia đều, biểu tượng trên chữ 0.8125rem, cao `--bottom-nav-h`. Đang chọn không có nền: chữ `--violet` và biểu tượng nét 2.5px.

### Label card (nhãn vở)
- Thẻ trắng rộng tối đa 420px, viền đôi tím 4px, bo `--radius-lg`, bóng `--shadow`. Tên quán ở đầu (display), dòng dẫn `--ink-2`, biểu mẫu, rồi dòng trợ giúp căn giữa cỡ nhỏ. Chỉ dùng trên trang nền trống.

### Django admin (dữ liệu nền)
- `templates/admin/base_site.html` ánh xạ biến của Django admin sang bảng màu: `--primary`/`--button-bg`/`--link-fg` là mực tím, `--secondary`/hover là mực tím đè, `--accent`/`--header-color` là `--on-violet-2`, `--selected-bg` là tím nhạt, `--selected-row` là giấy lót, lỗi và nền thông báo dùng đỏ lề, xanh đạt, hổ phách mềm.
- Chỉ một giao diện sáng: khối dark-mode bị bỏ trống và nút đổi giao diện bị ẩn.
- Đường lề đỏ 1px dưới `#header`. Checkbox/radio `accent-color` tím; focus là viền tím 3px như ứng dụng.
- Nút thu gọn thanh bên thay bằng mũi tên SVG nét 2.5px tím. Biểu tượng `static/admin/img/icon-*.svg` vẽ lại theo cùng ngôn ngữ nét tròn 2.4px: thêm (tím), sửa và xem (`--ink-2`), xóa (đỏ lề).
- Liên kết "Về trang chủ" đứng đầu dòng tiện ích người dùng.

## Do's and Don'ts

### Do:
- **Do** dùng `--violet` cho đúng một loại việc: hành động chính và điều hướng đang chọn.
- **Do** giữ mọi đích chạm ≥ `--tap` (48px); hành động chính trên điện thoại nằm trong vùng ngón cái.
- **Do** đi kèm chữ (và biểu tượng với thông báo, dải cảnh báo) cho mọi trạng thái; không chỉ đổi màu.
- **Do** hiển thị thay đổi sau khi gửi bằng `.correction`: giá trị cũ gạch đỏ vẫn đọc được, giá trị mới viết bên cạnh.
- **Do** phân tách hàng bằng đường kẻ `--line` 1px như dòng kẻ vở thay vì hộp có bóng.
- **Do** lấy màu admin từ cùng bảng token khi thêm trang quản trị.

### Don't:
- **Don't** dùng đỏ lề, xanh đạt hay hổ phách làm nền nút hành động.
- **Don't** đặt lưới ô ly sau nội dung làm việc; chỉ dùng trên trang nền trống.
- **Don't** thêm bóng cho thẻ, bảng hay thanh trong khung ứng dụng; bóng chỉ thuộc nhãn vở.
- **Don't** thêm font web hoặc họ chữ thứ hai khi quán chưa có font chính thức.
- **Don't** bật giao diện tối riêng cho admin hay ứng dụng; hệ hiện chỉ có một giao diện sáng.
- **Don't** xóa hoặc ẩn giá trị cũ khi sửa; đính chính bằng bút đỏ.

## Mục mở (chưa xây)

- Màn hình tạo đơn và quầy pha chế mới chỉ kiểm tra trên máy tính 1366x768 và điện thoại 375x812.

Các điểm trần của thế giới này chưa có trên màn hình nào; ghi lại để không bị coi là đã xong:

1. **Một wordmark thống nhất trên mọi thiết bị.** Hiện tên quán xuất hiện ba kiểu: nhãn vở (`--text-2xl`, 750, tím), thanh tiêu đề (`--text-md`, 750, trắng), và tiêu đề Django admin (kiểu mặc định của admin, nét mảnh). Chữ "LAM Coffee" đặt bằng font hệ thống chỉ là chỗ giữ tạm, chờ logo chính thức.
2. **Bút đỏ đính chính chưa xuất hiện trên màn hình nào.** `.correction del/ins` đã có trong CSS nhưng chưa template nào dùng; lần đầu dùng thật (yêu cầu điều chỉnh đơn, nhật ký) cần được rà lại.
3. **Neo đường lề.** Trên nền ô ly, lề đỏ đặt theo vị trí cố định của khung nhìn (2.5rem trên điện thoại, 12vw từ 900px), không neo vào nhãn vở hay cột nội dung. Trong khung ứng dụng, lề đỏ là ranh giới điều hướng/nội dung (cạnh phải cột trái, cạnh trên thanh dưới), chưa phải đường chạy dọc cột nội dung như định hướng ban đầu mô tả.
