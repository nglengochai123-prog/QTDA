"""Chuông thông báo trong ứng dụng: ghi theo sự việc, đúng người nhận, số chưa đọc, đánh dấu đã đọc, không mở trang ngoài."""
import uuid
from datetime import timedelta
from unittest import mock

from django.db import connection
from django.test.utils import CaptureQueriesContext

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.core import notifications
from apps.core.models import Notification
from apps.core.push import notify_later
from apps.orders import services
from apps.orders.models import Order
from apps.orders.tests.helpers import PASSWORD, build_menu, cart


def key():
    return uuid.uuid4().hex


class ReadyItemTests(TestCase):
    """Món pha xong: một thông báo mỗi đơn khi cả đơn đã pha xong, chỉ trên chuông; mang hết ra bàn thì thành đã đọc."""

    def setUp(self):
        self.d = build_menu()
        payload = cart(self.d, quantity=2)
        payload["lines"].append(dict(payload["lines"][0], quantity=1, note="ít ngọt"))
        result, _ = services.submit_order(self.d["waiter"], key(), payload)
        self.first, self.second = Order.objects.get(pk=result["order_id"]).lines.order_by("position")

    def finish(self, line, cups, before=0):
        with self.captureOnCommitCallbacks(execute=True):
            services.complete_line(self.d["barista"], key(), line.pk, cups, before)

    def test_one_notification_per_order_and_no_phone_push(self):
        with mock.patch("apps.core.push.send_to_user") as pushed:
            self.finish(self.first, 1)
            self.finish(self.first, 1, 1)
            self.assertFalse(Notification.objects.exists())  # còn dòng thứ hai đang chờ pha
            self.finish(self.second, 1)
        pushed.assert_not_called()
        n = Notification.objects.get()
        self.assertEqual((n.user, n.kind, n.url), (self.d["waiter"], "mon_san_sang", "/don/san-sang/"))
        self.assertEqual(n.title, "Bàn 5: 3 món đã pha xong")
        self.assertIn("2 × Cà phê sữa, 1 × Cà phê sữa", n.body)
        with self.captureOnCommitCallbacks(execute=True):
            services.serve_line(self.d["waiter"], key(), self.first.pk)
        n.refresh_from_db()
        self.assertIsNone(n.read_at)  # còn một món chưa mang ra
        with self.captureOnCommitCallbacks(execute=True):
            services.serve_line(self.d["waiter"], key(), self.second.pk)
        n.refresh_from_db()
        self.assertIsNotNone(n.read_at)

    def test_waiter_sees_ready_dish_in_bell_and_count(self):
        self.finish(self.first, 2)
        self.finish(self.second, 1)
        self.client.login(username="phucvu", password=PASSWORD)
        data = self.client.get(reverse("core:notification_summary")).json()
        self.assertEqual(data["unread"], 1)
        self.assertEqual(data["items"][0]["kind"], "mon_san_sang")
        self.assertIn("Ly pha xong chờ mang ra", [t["label"] for t in data["waiting"]])
        self.assertEqual(self.client.get(reverse("core:notification_summary") + "?chi_so=1").json(), {"unread": 1})
        page = self.client.get(reverse("core:notifications")).content.decode()
        self.assertIn('data-notif-badge>1</span>', page)
        self.assertIn("Ly pha xong chờ mang ra", page)
        # Pha chế không nhận thông báo món pha xong (đó là việc của người nhận đơn).
        self.client.login(username="phache", password=PASSWORD)
        self.assertEqual(self.client.get(reverse("core:notification_summary")).json()["unread"], 0)

    def test_count_poll_is_one_cheap_query(self):
        self.client.login(username="chuquan", password=PASSWORD)
        self.client.get(reverse("core:notification_summary") + "?chi_so=1")
        with CaptureQueriesContext(connection) as queries:
            self.client.get(reverse("core:notification_summary") + "?chi_so=1")
        # Chỉ một truy vấn đếm thông báo; phần còn lại là phiên đăng nhập và nhật ký truy cập của mọi trang.
        sql = [q["sql"] for q in queries]
        self.assertEqual(sum("core_notification" in q for q in sql), 1)
        self.assertFalse(any("orders_" in q or "control_" in q or "shifts_" in q for q in sql))


class AlertNotificationTests(TestCase):
    def test_alert_writes_after_commit_and_closing_marks_read(self):
        from apps.control.alerts import _close
        from apps.control.models import Alert
        from apps.core.models import Store
        from apps.core.push import notify_alert

        d = build_menu()
        alert = Alert.objects.create(store=Store.get_default(), kind=Alert.Kind.choices[0][0], subject="thu-1",
                                     title="Sữa đặc đã hết", detail="Báo lúc 09:00", severity="khan",
                                     assignee_role="chu_quan", due_at=timezone.now() + timedelta(hours=1), link="/kho/")
        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            notify_alert(alert)
            self.assertFalse(Notification.objects.exists())  # chưa ghi khi giao dịch chưa xong
        for callback in callbacks:
            callback()
        n = Notification.objects.get(user=d["owner"])
        self.assertEqual((n.kind, n.title), ("canh_bao", "Khẩn: Sữa đặc đã hết"))
        _close(alert, d["owner"], "Đã mua thêm")
        n.refresh_from_db()
        self.assertIsNotNone(n.read_at)

    def test_non_urgent_alert_stays_off_the_bell(self):
        from apps.control.models import Alert
        from apps.core.models import Store
        from apps.core.push import notify_alert

        build_menu()
        alert = Alert.objects.create(store=Store.get_default(), kind=Alert.Kind.choices[0][0], subject="thu-2",
                                     title="Ngoại lệ chờ xem xét", detail="", severity="quan_trong",
                                     assignee_role="chu_quan", due_at=timezone.now() + timedelta(hours=1), link="/canh-bao/")
        with self.captureOnCommitCallbacks(execute=True):
            notify_alert(alert)
        self.assertFalse(Notification.objects.exists())


class BellTests(TestCase):
    def setUp(self):
        self.d = build_menu()
        self.owner, self.waiter = self.d["owner"], self.d["waiter"]

    def test_push_events_also_write_bell_rows_with_kind_from_screen(self):
        with self.captureOnCommitCallbacks(execute=True):
            notify_later([self.owner.pk], "Yêu cầu duyệt: hủy 1 ly", "Bàn 5", "/duyet/")
            notify_later([self.owner.pk], "Đã hết Sữa đặc", "Phục vụ báo", "/kho/")
            notify_later([self.waiter.pk], "Lịch làm tuần 23/11", "Bạn có 3 ca", "/lich/cua-toi/")
        kinds = dict(Notification.objects.values_list("title", "kind"))
        self.assertEqual(kinds["Yêu cầu duyệt: hủy 1 ly"], "phe_duyet")
        self.assertEqual(kinds["Đã hết Sữa đặc"], "kho")
        self.assertEqual(kinds["Lịch làm tuần 23/11"], "lich")
        self.assertEqual(notifications.unread(self.owner).count(), 2)
        self.assertEqual(notifications.unread(self.waiter).count(), 1)

    def test_same_key_not_written_twice(self):
        notifications.create([self.owner.pk], "A", key="k-1")
        notifications.create([self.owner.pk], "A", key="k-1")
        notifications.create([self.waiter.pk], "A", key="k-1")
        self.assertEqual(Notification.objects.count(), 2)

    def test_mark_one_and_all_read_only_own(self):
        notifications.create([self.owner.pk, self.waiter.pk], "Báo cáo cuối ca")
        own = Notification.objects.get(user=self.owner)
        other = Notification.objects.get(user=self.waiter)
        self.client.login(username="chuquan", password=PASSWORD)
        r = self.client.post(reverse("core:notification_read"), {"id": [other.pk]}, HTTP_ACCEPT="application/json")
        self.assertEqual(r.json()["changed"], 0)  # không đánh dấu được thông báo của người khác
        notifications.create([self.owner.pk], "Thứ hai")
        r = self.client.post(reverse("core:notification_read"), HTTP_ACCEPT="application/json")
        self.assertEqual((r.json()["changed"], r.json()["unread"]), (2, 0))
        own.refresh_from_db(); other.refresh_from_db()
        self.assertIsNotNone(own.read_at)
        self.assertIsNone(other.read_at)

    def test_open_marks_read_and_redirects_inside_app_only(self):
        notifications.create([self.owner.pk], "Trong app", url="/duyet/")
        notifications.create([self.owner.pk], "Trang ngoài", url="//evil.example/x")
        inside = Notification.objects.get(title="Trong app")
        outside = Notification.objects.get(title="Trang ngoài")
        self.client.login(username="chuquan", password=PASSWORD)
        r = self.client.get(reverse("core:notification_open", args=[inside.pk]))
        self.assertRedirects(r, "/duyet/", fetch_redirect_response=False)
        inside.refresh_from_db()
        self.assertIsNotNone(inside.read_at)
        r = self.client.get(reverse("core:notification_open", args=[outside.pk]))
        self.assertRedirects(r, reverse("core:notifications"), fetch_redirect_response=False)
        # Không mở được thông báo của người khác.
        notifications.create([self.waiter.pk], "Của phục vụ")
        theirs = Notification.objects.get(title="Của phục vụ")
        self.assertEqual(self.client.get(reverse("core:notification_open", args=[theirs.pk])).status_code, 404)

    def test_page_filters_and_owner_waiting_list(self):
        notifications.create([self.owner.pk], "Đọc rồi", url="/kho/")
        Notification.objects.filter(title="Đọc rồi").update(read_at=timezone.now())
        notifications.create([self.owner.pk], "Chưa đọc", url="/duyet/")
        self.client.login(username="chuquan", password=PASSWORD)
        html = self.client.get(reverse("core:notifications")).content.decode()
        self.assertIn("Thông báo · 1 chưa đọc", html)
        self.assertIn("Đọc rồi", html)
        html = self.client.get(reverse("core:notifications") + "?loc=chua-doc").content.decode()
        self.assertNotIn("Đọc rồi", html)
        html = self.client.get(reverse("core:notifications") + "?loai=kho").content.decode()
        self.assertNotIn("Chưa đọc</strong>", html)

    def test_summary_requires_login(self):
        r = self.client.get(reverse("core:notification_summary"))
        self.assertEqual(r.status_code, 302)

    def test_purge_drops_old_and_keeps_recent(self):
        notifications.create([self.owner.pk], "Cũ đã đọc")
        notifications.create([self.owner.pk], "Cũ chưa đọc")
        notifications.create([self.owner.pk], "Mới chưa đọc")
        old = timezone.now() - timedelta(days=notifications.KEEP_DAYS + 1)
        Notification.objects.filter(title="Cũ đã đọc").update(created_at=old, read_at=old)
        Notification.objects.filter(title="Cũ chưa đọc").update(created_at=old)
        self.assertEqual(notifications.purge(), 2)
        self.assertEqual(list(Notification.objects.values_list("title", flat=True)), ["Mới chưa đọc"])

    def test_ago_wording(self):
        now = timezone.now()
        self.assertEqual(notifications.ago(now, now), "vừa xong")
        self.assertEqual(notifications.ago(now - timedelta(minutes=5), now), "5 phút trước")


class HomeTests(TestCase):
    """Không còn trang chủ: "/" mở màn việc chính của vai trò; việc đang chờ ở chuông và trang Việc và thông báo."""

    def setUp(self):
        self.d = build_menu()

    def test_each_role_lands_on_its_main_screen(self):
        from apps.accounts.models import Role, User

        User.objects.create_user("thungan", password=PASSWORD, role=Role.THU_NGAN)
        for user, url in [("phucvu", "/don/moi/"), ("phache", reverse("orders:bar")),
                          ("thungan", reverse("orders:cashier")), ("chuquan", reverse("core:notifications"))]:
            self.client.login(username=user, password=PASSWORD)
            self.assertRedirects(self.client.get("/"), url, fetch_redirect_response=False, msg_prefix=user)
        # Quán còn thiếu nhân viên nên Chủ quán vào trang Việc để khai báo; khai báo đủ thì vào Bảng điều khiển.
        from apps.staff.models import Employee

        Employee.objects.create(store=self.d["store"], user=self.d["waiter"], full_name="Phục vụ", phone="0901234567")
        self.assertRedirects(self.client.get("/"), reverse("reports:dashboard"), fetch_redirect_response=False)

    def test_work_page_lists_only_non_zero_work_and_no_home_tab(self):
        result, _ = services.submit_order(self.d["waiter"], key(), cart(self.d))
        line = Order.objects.get(pk=result["order_id"]).lines.get()
        with self.captureOnCommitCallbacks(execute=True):
            services.complete_line(self.d["barista"], key(), line.pk, 1, 0)
        self.client.login(username="chuquan", password=PASSWORD)
        html = self.client.get(reverse("core:notifications")).content.decode()
        self.assertIn("Ly pha xong chờ mang ra", html)
        self.assertNotIn("Kiểm kê chờ xác nhận", html)  # số 0 thì không hiện
        self.assertNotIn(">Trang chủ<", html)
        self.assertNotIn('title="Duyệt điều chỉnh"', html)
        self.assertNotIn('title="Tham số"', html)


class HomeLogicTests(TestCase):
    """Số trên Trang chủ khớp các màn khác: không đếm một việc hai lần, cùng đơn vị, báo khi số liệu đã cũ."""

    def setUp(self):
        self.d = build_menu()
        self.client.login(username="chuquan", password=PASSWORD)

    def test_exception_alerts_not_counted_twice(self):
        from apps.control.models import Alert, ExceptionCase
        from apps.core.models import Store

        store = Store.get_default()
        for i, kind in enumerate([Alert.Kind.EXCEPTION, Alert.Kind.EXCEPTION, Alert.Kind.OUT_OF_STOCK]):
            Alert.objects.create(store=store, kind=kind, subject=f"s-{i}", title=f"Việc {i}", detail="",
                                 severity="quan_trong", assignee_role="chu_quan",
                                 due_at=timezone.now() + timedelta(hours=1), link="/canh-bao/")
        tasks = {t["label"]: t["count"] for t in notifications.pending_tasks(self.d["owner"])}
        self.assertEqual(tasks["Cảnh báo của tôi"], 1)  # hai cảnh báo ngoại lệ đã nằm ở dòng Ngoại lệ
        self.assertIn("Ngoại lệ chờ xem xét", tasks)
        self.assertEqual(ExceptionCase.objects.count(), tasks["Ngoại lệ chờ xem xét"])

    def test_ready_counted_in_cups_like_shift_overview(self):
        result, _ = services.submit_order(self.d["waiter"], key(), cart(self.d, quantity=3))
        line = Order.objects.get(pk=result["order_id"]).lines.get()
        services.complete_line(self.d["barista"], key(), line.pk, 3, 0)
        tasks = {t["label"]: t["count"] for t in notifications.pending_tasks(self.d["owner"])}
        self.assertEqual(tasks["Ly pha xong chờ mang ra"], 3)

    def test_stale_forecast_is_flagged_on_home(self):
        from apps.forecast.models import ForecastRelease

        self.assertEqual(notifications.forecast_stale(), "")  # chưa có dự báo: không báo
        rel = ForecastRelease.objects.create(issued_at=timezone.now() - timedelta(hours=40),
                                             first_day=timezone.localdate(), horizon_days=14, model_version="t",
                                             data_version="x")
        html = self.client.get(reverse("core:notifications")).content.decode()
        self.assertIn("chưa cập nhật từ", html)
        self.assertIn("tác vụ hằng đêm chưa chạy", html)
        rel.issued_at = timezone.now() - timedelta(hours=2)
        rel.save()
        self.assertNotIn("tác vụ hằng đêm chưa chạy", self.client.get(reverse("core:notifications")).content.decode())
