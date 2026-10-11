"""Chạy một thao tác thay đổi dữ liệu đúng một lần theo mã nghiệp vụ (NFR-04)."""

import hashlib
import json
import re

from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction

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
        raise OperationKeyError("Thiếu mã nghiệp vụ hoặc mã không hợp lệ.")
    digest = payload_hash(payload)
    with transaction.atomic():
        existing = OperationRecord.objects.select_for_update().filter(key=key).first()
        if existing is not None:
            if existing.kind != kind or existing.payload_hash != digest:
                raise OperationKeyError("Mã nghiệp vụ này đã được dùng cho một yêu cầu khác.")
            return existing.result, True
        result = action()
        OperationRecord.objects.create(key=key, kind=kind, payload_hash=digest, result=result, actor=actor)
        return result, False
