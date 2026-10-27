"""Đường dẫn tệp giao diện (app.css, app.js…) kèm số phiên bản khi chạy trên máy cá nhân."""

import os

from django.contrib.staticfiles import finders
from django.contrib.staticfiles.storage import StaticFilesStorage


class VersionedStaticFilesStorage(StaticFilesStorage):
    """Chạy bằng runserver, máy chủ không ghi hạn lưu cho tệp tĩnh nên trình duyệt tự đoán và có thể dùng app.css, app.js
    cũ thêm nhiều giờ sau khi chép bản mới: nút mới không có kiểu, mã trang cũ chạy với trang mới. Thêm ?v=<giờ sửa tệp>
    để bản mới được tải ngay. Bản chạy thật dùng tên tệp có mã băm (settings.py)."""

    def url(self, name):
        url = super().url(name)
        path = finders.find(name)
        if isinstance(path, str):
            try:
                return f"{url}?v={int(os.path.getmtime(path))}"
            except OSError:
                pass
        return url
