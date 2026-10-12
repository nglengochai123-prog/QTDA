"""Thông báo đẩy Web Push (NFR-17, BRU-36): gửi cảnh báo đến điện thoại người xử lý kể cả khi ứng dụng đóng.

Gửi thật cần thư viện `pywebpush` và cặp khóa VAPID trong biến môi trường:
    WEBPUSH_VAPID_PUBLIC_KEY   khóa công khai dạng base64url (applicationServerKey)
    WEBPUSH_VAPID_PRIVATE_KEY  đường dẫn tệp khóa riêng PEM hoặc nội dung khóa
    WEBPUSH_CONTACT            mailto:... của quán
Mỗi lần gửi tạo một PushMessage ghi ba mốc tách biệt:
    1. dịch vụ đẩy của trình duyệt (Google, Apple, Mozilla) đã nhận yêu cầu từ máy chủ (mã 201);
    2. điện thoại thực sự hiện thông báo (service worker báo về);
    3. người dùng chạm mở thông báo.
Mốc 1 không bảo đảm mốc 2: điện thoại tắt mạng, tắt quyền thông báo hoặc chế độ tiết kiệm pin có thể chặn.
"""

import json
import os

from django.conf import settings
from django.urls import reverse
from django.utils import timezone


def public_key():
    return os.environ.get("WEBPUSH_VAPID_PUBLIC_KEY", "") or getattr(settings, "WEBPUSH_VAPID_PUBLIC_KEY", "")


def _private_key():
    """Đường dẫn tệp khóa riêng PEM hoặc nội dung khóa; pywebpush nhận cả hai."""
    return os.environ.get("WEBPUSH_VAPID_PRIVATE_KEY", "")


def status():
    """(sẵn sàng, lý do) để hiện trên giao diện và trong hướng dẫn."""
    try:
        import pywebpush  # noqa: F401
    except ImportError:
        return False, "Máy chủ chưa cài thư viện pywebpush."
    if not public_key() or not _private_key():
        return False, "Chưa cấu hình khóa VAPID (WEBPUSH_VAPID_PUBLIC_KEY, WEBPUSH_VAPID_PRIVATE_KEY)."
    return True, ""


def send_to_user(user, title, body, url="/", kind="canh_bao"):
    """Gửi đến mọi thiết bị đã đăng ký của người dùng. Trả (số thiết bị dịch vụ đẩy đã nhận, lý do nếu không gửi)."""
    from .models import PushMessage, PushSubscription

    ready, reason = status()
    subs = list(PushSubscription.objects.filter(user=user, is_active=True))
    if not ready or not subs:
        return 0, reason or "Người dùng chưa bật thông báo trên thiết bị nào."
    from pywebpush import WebPushException, webpush

    message = PushMessage.objects.create(user=user, title=title[:120], body=body[:255], url=url[:200], kind=kind)
    payload = json.dumps({"title": title, "body": body, "url": url, "id": str(message.pk),
                          "receipt": reverse("core:push_receipt", args=[message.pk, "nhan"]),
                          "opened": reverse("core:push_receipt", args=[message.pk, "mo"])})
    results, accepted = [], 0
    for sub in subs:
        entry = {"thiet_bi": sub.user_agent[:60], "luc": timezone.now().isoformat()}
        try:
            response = webpush(subscription_info={"endpoint": sub.endpoint,
                                                  "keys": {"p256dh": sub.p256dh, "auth": sub.auth}},
                               data=payload, vapid_private_key=_private_key(), ttl=3600,
                               vapid_claims={"sub": os.environ.get("WEBPUSH_CONTACT", "mailto:admin@example.com")})
            entry["ma"] = getattr(response, "status_code", 201)
            accepted += 1
        except WebPushException as error:
            code = getattr(error.response, "status_code", None)
            entry["ma"], entry["loi"] = code, str(error)[:200]
            if code in (404, 410):  # thiết bị đã hủy đăng ký: ngừng gửi
                sub.is_active = False
                sub.save(update_fields=["is_active"])
        results.append(entry)
    message.service_results, message.accepted_count = results, accepted
    message.save(update_fields=["service_results", "accepted_count"])
    return accepted, "" if accepted else "Dịch vụ đẩy không nhận yêu cầu; xem chi tiết lỗi."


def notify_alert(alert):
    """Gửi cảnh báo Khẩn hoặc Quan trọng đến người xử lý chính, hoặc mọi Chủ quán khi đã chuyển cấp."""
    from apps.accounts.models import Role, User

    if alert.assignee_id and not alert.level:
        targets = [alert.assignee]
    else:
        role = Role.CHU_QUAN if (alert.level or alert.assignee_role == Role.CHU_QUAN) else alert.assignee_role
        targets = [u for u in User.objects.filter(is_active=True) if u.has_role(role)]
    for user in targets:
        send_to_user(user, ("Khẩn: " if alert.severity == "khan" else "") + alert.title, alert.detail[:160],
                     alert.link or "/canh-bao/")

