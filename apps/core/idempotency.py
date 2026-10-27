"""Chạy một thao tác thay đổi dữ liệu đúng một lần theo mã nghiệp vụ (NFR-04)."""

import hashlib
import json
import re

from django.core.serializers.json import DjangoJSONEncoder
from django.db import IntegrityError, transaction

from .models import OperationRecord

KEY_PATTERN = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


class OperationKeyError(Exception):
    """Mã nghiệp vụ thiếu, sai dạng, hoặc đã dùng cho nội dung khác."""


def payload_hash(payload):
    raw = json.dumps(payload, sort_keys=True, cls=DjangoJSONEncoder, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def run_once(key, kind, payload, action, actor=None):
    """Chạy action() một lần cho mỗi mã. Trả (kết quả, là_lần_lặp).

    action() chạy trong cùng giao dịch với việc lưu mã; nếu action lỗi thì mã không được lưu,
    nên gửi lại sau lỗi vẫn được xử lý một lần.
    """
    if not key or not KEY_PATTERN.match(key):
        raise OperationKeyError("Trang đã cũ hoặc gửi thiếu dữ liệu. Tải lại trang rồi thử lại.")
    digest = payload_hash(payload)
    with transaction.atomic():
        try:
            # Giữ chỗ mã trước khi làm: yêu cầu cùng mã gửi đồng thời sẽ chờ ở chỉ mục duy nhất cho đến khi
            # yêu cầu đầu hoàn tất, rồi đọc kết quả đã lưu thay vì chạy lại (đã kiểm trên PostgreSQL).
            with transaction.atomic():
                record = OperationRecord.objects.create(key=key, kind=kind, payload_hash=digest, result={},
                                                        actor=actor)
        except IntegrityError:
            existing = OperationRecord.objects.select_for_update().get(key=key)
            if existing.kind != kind or existing.payload_hash != digest:
                raise OperationKeyError("Biểu mẫu này đã được gửi trước đó với nội dung khác (có thể do bấm Quay lại). "
                                        "Tải lại trang rồi nhập lại.")
            return existing.result, True
        result = action()
        record.result = result
        record.save(update_fields=["result"])
        return result, False
