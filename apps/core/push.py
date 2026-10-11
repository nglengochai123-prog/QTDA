"""Thông báo đẩy Web Push (NFR-17, BRU-36): gửi cảnh báo đến điện thoại người xử lý kể cả khi ứng dụng đóng.

Gửi thật cần thư viện `pywebpush` (kèm `cryptography`) và cặp khóa VAPID trong biến môi trường:
    WEBPUSH_VAPID_PUBLIC_KEY, WEBPUSH_VAPID_PRIVATE_KEY, WEBPUSH_CONTACT (mailto:...)
Khi chưa đủ điều kiện, `send_to_user` không gửi và trả lý do, để luồng nghiệp vụ không bị chặn;
cảnh báo vẫn có trong trung tâm cảnh báo. Cảnh báo mức Thông tin không gửi tức thời (NFR-23).
"""

import json
import os

from django.conf import settings


def public_key():
    return os.environ.get("WEBPUSH_VAPID_PUBLIC_KEY", "") or getattr(settings, "WEBPUSH_VAPID_PUBLIC_KEY", "")


def status():
    """(sẵn sàng, lý do) để hiện trên giao diện và trong hướng dẫn."""
    try:
        import pywebpush  # noqa: F401
    except ImportError:
        return False, "Máy chủ chưa cài thư viện pywebpush."
    if not public_key() or not os.environ.get("WEBPUSH_VAPID_PRIVATE_KEY"):
        return False, "Chưa cấu hình khóa VAPID (WEBPUSH_VAPID_PUBLIC_KEY, WEBPUSH_VAPID_PRIVATE_KEY)."
    return True, ""


def send_to_user(user, title, body, url="/"):
    """Gửi đến mọi thiết bị đã đăng ký của người dùng. Trả số thiết bị đã gửi được và lý do nếu không gửi."""
    from .models import PushSubscription

    ready, reason = status()
    subs = list(PushSubscription.objects.filter(user=user, is_active=True))
    if not ready or not subs:
        return 0, reason or "Người dùng chưa bật thông báo trên thiết bị nào."
    from pywebpush import WebPushException, webpush

    sent = 0
    payload = json.dumps({"title": title, "body": body, "url": url})
    for sub in subs:
        try:
            webpush(subscription_info={"endpoint": sub.endpoint, "keys": {"p256dh": sub.p256dh, "auth": sub.auth}},
                    data=payload, vapid_private_key=os.environ["WEBPUSH_VAPID_PRIVATE_KEY"],
                    vapid_claims={"sub": os.environ.get("WEBPUSH_CONTACT", "mailto:admin@example.com")})
            sent += 1
        except WebPushException as error:  # thiết bị đã hủy đăng ký: ngừng gửi
            if getattr(error.response, "status_code", None) in (404, 410):
                sub.is_active = False
                sub.save(update_fields=["is_active"])
    return sent, ""


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
