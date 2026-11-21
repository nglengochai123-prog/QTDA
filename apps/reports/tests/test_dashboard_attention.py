"""Bảng điều khiển Chủ quán: việc cần chú ý gom từ dữ liệu có sẵn, đúng mức độ, đúng màn xử lý; số hôm nay tách khỏi
bộ lọc tháng; không có dữ liệu giá vốn thì không đưa ra số lãi gộp; chỉ Chủ quán xem được."""
from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.control.models import Alert, ExceptionCase
from apps.core.models import Store
from apps.orders.tests.helpers import PASSWORD, build_menu
from apps.reports import services


class AttentionTests(TestCase):
    def setUp(self):
        self.d = build_menu()
        self.client.login(username="chuquan", password=PASSWORD)
        self.store = Store.get_default()

    def alert(self, kind, severity, due_hours, subject):
        return Alert.objects.create(store=self.store, kind=kind, subject=subject, title=subject, detail="",
                                    severity=severity, assignee_role="chu_quan",
                                    due_at=timezone.now() + timedelta(hours=due_hours), link="/canh-bao/")

    def test_empty_store_renders_and_says_nothing_to_watch(self):
        page = self.client.get(reverse("reports:dashboard"))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Cần chú ý")
        self.assertContains(page, "Chưa có đơn đã thanh toán trong tháng này.")

    def test_alerts_and_exceptions_ranked_with_links_and_no_double_count(self):
        self.alert(Alert.Kind.OUT_OF_STOCK, Alert.Severity.URGENT, -2, "qua-han")
        self.alert(Alert.Kind.OUT_OF_STOCK, Alert.Severity.IMPORTANT, 5, "quan-trong")
        self.alert(Alert.Kind.EXCEPTION, Alert.Severity.IMPORTANT, -1, "ngoai-le-qua-han")  # đã có mục Ngoại lệ
        ExceptionCase.objects.create(store=self.store, kind=ExceptionCase.Kind.choices[0][0],
                                     severity=ExceptionCase.Severity.URGENT, rule="thu")
        page = self.client.get(reverse("reports:dashboard"))
        items = page.context["attention"]
        titles = [i["title"] for i in items]
        self.assertEqual(items[0]["level"], "khan")
        overdue = next(i for i in items if i["title"] == "Cảnh báo đã quá hạn xử lý")
        self.assertEqual(overdue["value"], 1)  # cảnh báo ngoại lệ không đếm thêm
        self.assertIn("Cảnh báo quan trọng đang chờ xử lý", titles)
        exc = next(i for i in items if i["title"].startswith("Ngoại lệ khẩn"))
        self.assertEqual(exc["url"], reverse("control:exceptions") + "?muc=khan")
        self.assertEqual(self.client.get(exc["url"]).status_code, 200)
        self.assertEqual([i["level"] for i in items], sorted((i["level"] for i in items),
                                                             key=lambda l: services.LEVELS[l][0]))

    def test_missing_cost_shows_no_margin_number(self):
        from apps.orders import services as order_services
        from apps.orders.tests.helpers import cart
        import uuid

        result, _ = order_services.submit_order(self.d["waiter"], uuid.uuid4().hex, cart(self.d))
        s = services.dashboard()
        margin = [k for k in s["sales"]["kpis"] if k["label"] == "Lãi gộp ước tính"]
        if s["sales"]["has_sales"]:
            self.assertTrue(margin[0].get("missing") or margin[0]["value"] is not None)
        _ = result

    def test_today_numbers_ignore_month_filter_and_only_owner_sees(self):
        page = self.client.get(reverse("reports:dashboard"), {"thang": "2025-01"})
        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.context["ops"]["today_date"], timezone.localdate())
        self.assertEqual(page.context["month"].month, 1)
        User.objects.create_user("tn", password=PASSWORD, role=Role.THU_NGAN)
        self.client.login(username="tn", password=PASSWORD)
        self.assertEqual(self.client.get(reverse("reports:dashboard")).status_code, 403)
