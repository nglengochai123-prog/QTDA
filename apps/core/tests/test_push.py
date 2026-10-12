"""Thông báo đẩy (NFR-17): lưu đăng ký thiết bị; khi máy chủ chưa đủ điều kiện thì không gửi và nói rõ lý do."""

import json

from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import Role, User
from apps.core import push
from apps.core.models import PushSubscription


class PushTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("qlca", password="matkhau-thu-123", role=Role.QUAN_LY_CA)
        self.client.login(username="qlca", password="matkhau-thu-123")

    def test_subscribe_and_status_without_library(self):
        sub = {"endpoint": "https://push.example/abc", "keys": {"p256dh": "k", "auth": "a"}}
        for _ in range(2):
            self.assertEqual(self.client.post(reverse("core:push_subscribe"), json.dumps(sub),
                                              content_type="application/json").status_code, 200)
        self.assertEqual(PushSubscription.objects.count(), 1)
        status = self.client.get(reverse("core:push_status")).json()
        self.assertEqual(status["devices"], 1)
        ready, reason = push.status()
        sent, why = push.send_to_user(self.user, "Thử", "Nội dung")
        if not ready:
            self.assertEqual((sent, why), (0, reason))
        self.assertEqual(self.client.post(reverse("core:push_subscribe"), "x", content_type="application/json").status_code, 400)


class PushDeliveryTests(TestCase):
    """Tách mốc: dịch vụ đẩy đã nhận (máy chủ gửi được) với điện thoại thực sự hiện thông báo."""

    def setUp(self):
        self.user = User.objects.create_user("qlca", password="matkhau-thu-123", role=Role.QUAN_LY_CA)
        PushSubscription.objects.create(user=self.user, endpoint="https://push.example/1", p256dh="k", auth="a")

    def test_service_accepted_is_not_device_received(self):
        from unittest import mock

        from apps.core.models import PushMessage

        class Accepted:
            status_code = 201

        env = {"WEBPUSH_VAPID_PUBLIC_KEY": "BPub", "WEBPUSH_VAPID_PRIVATE_KEY": "khoa"}
        with mock.patch.dict("os.environ", env), mock.patch("pywebpush.webpush", return_value=Accepted()) as sent:
            accepted, reason = push.send_to_user(self.user, "Thử", "Nội dung")
        self.assertEqual((accepted, reason), (1, ""))
        payload = json.loads(sent.call_args.kwargs["data"])
        message = PushMessage.objects.get()
        self.assertEqual((message.accepted_count, message.received_at), (1, None))  # chưa biết điện thoại có hiện
        self.client.post(payload["receipt"])  # service worker báo đã hiện
        self.client.post(payload["opened"])
        message.refresh_from_db()
        self.assertIsNotNone(message.received_at)
        self.assertIsNotNone(message.opened_at)


class AlertPageTests(TestCase):
    def test_alert_page_renders_push_panel(self):
        User.objects.create_user("qlca", password="matkhau-thu-123", role=Role.QUAN_LY_CA)
        self.client.login(username="qlca", password="matkhau-thu-123")
        page = self.client.get(reverse("control:alerts"))
        self.assertContains(page, "Thông báo đẩy trên điện thoại")
        self.assertContains(page, "js/push.js")
