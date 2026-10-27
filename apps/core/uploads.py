"""Kiểm tra ảnh chứng từ trước khi lưu: chỉ nhận ảnh hoặc PDF thật, không quá 10 MB.

Tệp tải lên được phục vụ lại ở /media/ cùng tên miền với ứng dụng; nếu nhận cả tệp HTML hay SVG thì
người mở "chứng từ" có thể chạy mã lạ trong phiên đăng nhập của mình. Vì vậy xét cả đuôi tệp lẫn
những byte đầu tệp, không tin tên tệp hay loại tệp trình duyệt khai.
"""

import os

from django.core.exceptions import ValidationError

MAX_BYTES = 10 * 1024 * 1024
EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".pdf"}
HEIF_BRANDS = {b"heic", b"heix", b"hevc", b"hevx", b"mif1", b"msf1", b"heim", b"heis", b"avif"}


def _looks_valid(head):
    if head.startswith((b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n", b"%PDF-")):
        return True
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return True
    return head[4:8] == b"ftyp" and head[8:12] in HEIF_BRANDS


def check_photo(upload, label="Ảnh chứng từ"):
    """Trả lại tệp nếu hợp lệ; tệp trống (không tải lên) trả None."""
    if not upload:
        return None
    message = f"{label} phải là ảnh chụp (JPG, PNG, WEBP, HEIC) hoặc tệp PDF, tối đa 10 MB."
    if os.path.splitext(upload.name or "")[1].lower() not in EXTENSIONS or upload.size > MAX_BYTES:
        raise ValidationError(message)
    upload.seek(0)
    head = upload.read(16)
    upload.seek(0)
    if not _looks_valid(head):
        raise ValidationError(message)
    return upload
