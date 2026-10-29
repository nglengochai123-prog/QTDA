"""Đọc số kiểu Việt Nam ở mọi ô nhập và câu báo lỗi cho người dùng."""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from apps.core import errors, numbers
from apps.core.templatetags.loi_thuong import ngay_iso, ngay_thu, phut
from apps.shifts.services import _money


class NumberParsingTests(SimpleTestCase):
    def test_money(self):
        for raw in ("1.390.000", "1,390,000", "1 390 000 đ", 1390000):
            self.assertEqual(numbers.vnd(raw, "Tiền"), 1390000)
        self.assertEqual(numbers.vnd("31,5", "Đơn giá"), 32)  # phần lẻ được làm tròn
        for bad in ("abc", "1.2.3", ""):
            with self.assertRaises(ValidationError):
                numbers.vnd(bad, "Tiền")

    def test_quantity_reads_dot_as_thousands(self):
        self.assertEqual(numbers.qty("1.000", "Số lượng"), 1000)
        self.assertEqual(numbers.qty("1.500,5", "Số lượng"), Decimal("1500.5"))
        self.assertEqual(numbers.qty("1,5", "Số lượng"), Decimal("1.5"))

    def test_whole_number_refuses_guessing(self):
        self.assertEqual(numbers.whole("50.000"), 50000)
        for bad in ("2.5", "2,5", "-1"):
            with self.assertRaises(ValidationError):
                numbers.whole(bad)

    def test_shift_money_accepts_spaces_and_currency(self):
        # Trước đây "1 390 000 đ" báo lỗi và "2.5" thành 25 đồng.
        self.assertEqual(_money("1 390 000 đ", "Tiền mặt đếm"), 1390000)
        self.assertEqual(_money("0", "Chuyển khoản"), 0)
        with self.assertRaises(ValidationError):
            _money("-5", "Tiền mặt đếm")

    def test_python_errors_are_not_shown_verbatim(self):
        self.assertEqual(errors.messages_of(ValidationError("Số phiếu đã dùng.")), ["Số phiếu đã dùng."])
        shown = errors.messages_of(ValueError("invalid literal for int() with base 10: 'x'"))
        self.assertNotIn("invalid literal", shown[0])
        self.assertEqual(errors.messages_of(ValueError("Tệp trống.")), ["Tệp trống."])

    def test_display_filters(self):
        self.assertEqual(ngay_thu("2026-10-26"), "T2 26/10")
        self.assertEqual(ngay_iso("2026-10-12"), "12/10/2026")
        self.assertEqual((phut(45), phut(546), phut(60), phut(3000)), ("45 phút", "9 giờ 6 phút", "1 giờ", "2 ngày 2 giờ"))

    def test_audit_values_read_like_the_screen(self):
        from apps.audit.display import _plain

        self.assertEqual([_plain(v) for v in ("0.00%", "8.33%", "3925.00", "2026-10-12")],
                         ["0%", "8,33%", "3.925", "12/10/2026"])
        # Số lô người dùng gõ trông giống ngày nhưng không phải ngày thật: giữ nguyên chữ, không làm hỏng trang.
        self.assertEqual([_plain(v) for v in ("2026-13-45", "2026-02-30T10:00")], ["2026-13-45", "2026-02-30T10:00"])


class PhotoUploadTests(SimpleTestCase):
    def test_only_real_images_or_pdf(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        from apps.core import uploads

        ok = [("hd.jpg", b"\xff\xd8\xff\xe0data"), ("hd.PNG", b"\x89PNG\r\n\x1a\nxx"), ("hd.pdf", b"%PDF-1.7"),
              ("hd.webp", b"RIFF\x00\x00\x00\x00WEBPVP8 "), ("hd.heic", b"\x00\x00\x00\x18ftypheic\x00\x00")]
        for name, data in ok:
            self.assertIsNotNone(uploads.check_photo(SimpleUploadedFile(name, data)), name)
        # Tệp HTML hay SVG đổi đuôi thành .jpg, hoặc khai content_type ảnh, vẫn bị chặn.
        bad = [("hd.html", b"<script>alert(1)</script>"), ("hd.jpg", b"<script>alert(1)</script>"),
               ("hd.svg", b"<svg onload=alert(1)>"), ("hd", b"\xff\xd8\xff")]
        for name, data in bad:
            with self.assertRaises(ValidationError):
                uploads.check_photo(SimpleUploadedFile(name, data, content_type="image/jpeg"))
        self.assertIsNone(uploads.check_photo(None))
