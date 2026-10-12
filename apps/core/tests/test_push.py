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


class NotifyOnEventsTests(TestCase):
    """NFR-17: yêu cầu phê duyệt đến người duyệt; AC-17: báo cáo cuối ca đến Chủ quán. Chỉ gửi khi giao dịch ghi xong."""

    def test_approval_request_and_shift_report_notify(self):
        from unittest import mock

        from apps.orders.tests.test_adjust_pay import Base

        base = Base(methodName="setUp")
        base.setUp()
        with mock.patch("apps.core.push.send_to_user", return_value=(1, "")) as send:
            with self.captureOnCommitCallbacks(execute=True):
                order, line = base.order()
                base.request(base.d["waiter"], order, "huy_mon", line=line.pk, cups=1)
            targets = {c.args[0] for c in send.call_args_list}
            self.assertIn(base.manager, targets)
            self.assertNotIn(base.d["waiter"], targets)  # người tạo yêu cầu không tự duyệt
            send.reset_mock()
            from apps.orders.models import Order
            from apps.shifts import services as shift_services

            Order.objects.update(status=Order.Status.CANCELLED)
            from apps.orders.models import AdjustmentRequest
            AdjustmentRequest.objects.update(status="tu_choi")
            with self.captureOnCommitCallbacks(execute=True):
                shift_services.add_cash_entry(base.manager, "k" * 12, base.shift.pk, "dau_ca", 0)
                shift_services.close_shift(base.manager, base.shift.pk)
                shift_services.submit_report(base.manager, base.shift.pk, 0, 0)
            self.assertIn(base.d["owner"], {c.args[0] for c in send.call_args_list})


class DataNoticeTests(TestCase):
    def test_notice_banner_until_acknowledged(self):
        User.objects.create_user("pv", password="matkhau-thu-123", role=Role.PHUC_VU)
        self.client.login(username="pv", password="matkhau-thu-123")
        self.assertContains(self.client.get(reverse("core:home")), "thông báo xử lý dữ liệu cá nhân")
        self.assertContains(self.client.get(reverse("core:data_notice")), "Kiểm soát doanh thu và thất thoát")
        self.client.post(reverse("core:data_notice"))
        self.client.post(reverse("core:data_notice"))
        from apps.core.models import DataNoticeAck

        self.assertEqual(DataNoticeAck.objects.count(), 1)
        self.assertNotContains(self.client.get(reverse("core:home")), "thông báo xử lý dữ liệu cá nhân")
