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
