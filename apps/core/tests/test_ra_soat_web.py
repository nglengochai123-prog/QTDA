"""Rà soát hoàn thiện web 03/11: tên tùy chọn trên phiếu, chữ hiển thị không còn mã tài liệu, ô kho của pha chế."""
import re
import uuid

from django.test import TestCase
from django.urls import reverse

from apps.catalog.models import Option, OptionGroup
from apps.orders import services
from apps.orders.models import OrderLine
from apps.orders.tests.helpers import PASSWORD, build_menu, cart, confirm_opening


class TicketNameTests(TestCase):
    def setUp(self):
        self.d = build_menu()
        self.ice = OptionGroup.objects.get(name="Đá")
        self.normal_ice = Option.objects.create(group=self.ice, name="Bình thường")

    def test_single_choice_option_without_group_word_gets_group_prefix(self):
        self.assertEqual(self.normal_ice.ticket_name, "Đá bình thường")
        self.assertEqual(self.d["less_ice"].ticket_name, "Ít đá")  # tên đã nói rõ nhóm
        self.assertEqual(self.d["cream"].ticket_name, "Kem muối")  # nhóm chọn nhiều giữ nguyên

    def test_order_line_keeps_clear_option_names(self):
        result, _ = services.submit_order(self.d["waiter"], uuid.uuid4().hex,
                                          cart(self.d, options=[self.d["cream"], self.normal_ice]))
        line = OrderLine.objects.get(order_id=result["order_id"])
        self.assertEqual(sorted(o.name for o in line.options.all()), ["Kem muối", "Đá bình thường"])

    def test_order_screen_sends_ticket_name_and_keeps_short_button_label(self):
        self.client.login(username="phucvu", password=PASSWORD)
        html = self.client.get(reverse("orders:create")).content.decode()
        self.assertIn('"ticket": "\\u0110\\u00e1 b\\u00ecnh th\\u01b0\\u1eddng"', html)
        self.assertIn('"name": "B\\u00ecnh th\\u01b0\\u1eddng"', html)


class PlainWordingTests(TestCase):
    def setUp(self):
        self.d = build_menu()

    def test_parameters_page_groups_settings_without_spec_codes(self):
        self.client.login(username="chuquan", password=PASSWORD)
        response = self.client.get(reverse("control:parameters"))
        self.assertEqual(response.status_code, 200)
        text = response.content.decode()
        for heading in ("Đơn và duyệt", "Tiền và ca", "Kho", "Phục vụ và lịch làm"):
            self.assertIn(heading, text)
        self.assertIsNone(re.search(r"\b(BRU|BO|AC|BRD)-\d", text))

    def test_barista_stock_tile_counts_ingredients_instead_of_yes_no(self):
        self.client.login(username="phache", password=PASSWORD)
        text = self.client.get(reverse("inventory:stock")).content.decode()
        self.assertIn("Dự kiến bỏ vì không dùng kịp", text)
        self.assertNotIn(">Có<", text)
        self.assertNotIn(">Không<", text)


class OrderScreenShiftNoticeTests(TestCase):
    def setUp(self):
        self.d = build_menu()

    def test_order_screen_warns_when_no_shift_is_running(self):
        from datetime import timedelta

        from django.utils import timezone

        from apps.shifts.models import Shift

        self.client.login(username="phucvu", password=PASSWORD)
        notice = "Chưa có ca đang mở"
        self.assertIn(notice, self.client.get(reverse("orders:create")).content.decode())
        now = timezone.now()
        Shift.objects.create(store=self.d["store"], name="Ca", starts_at=now - timedelta(hours=1),
                             ends_at=now + timedelta(hours=4), approver=self.d["owner"])
        self.assertNotIn(notice, self.client.get(reverse("orders:create")).content.decode())


from apps.orders.tests.test_backup import BackupBase  # noqa: E402
from apps.orders.tests.test_adjust_pay import key  # noqa: E402


class BackupShortCodeTests(BackupBase):
    """Màn Tạo đơn chỉ hiện 8 ký tự đầu của mã để ghi lên phiếu; nhập bù bằng mã đó không được tạo đơn trùng."""

    def test_short_code_from_order_screen_links_the_saved_order(self):
        from apps.orders.models import Order

        self.issue()
        online_key = key()
        result, _ = services.submit_order(self.d["waiter"], online_key, cart(self.d))
        written = online_key[:4].upper() + "-" + online_key[4:8].upper()  # người ghi tay thêm gạch nối
        linked = self.enter(151, code=written)
        self.assertTrue(linked["linked"])
        self.assertEqual(linked["order_id"], result["order_id"])
        self.assertEqual(Order.objects.count(), 1)

    def test_draft_resent_after_slip_with_short_code_does_not_duplicate(self):
        from apps.orders.models import Order

        self.issue()
        draft_key = key()  # đơn chưa tới máy chủ, quán bán bằng phiếu ghi 8 ký tự đầu
        created = self.enter(151, code=draft_key[:8].upper())
        self.assertFalse(created["linked"])
        again, repeated = services.submit_order(self.d["waiter"], draft_key, cart(self.d))
        self.assertTrue(repeated)
        self.assertEqual(again["order_id"], created["order_id"])
        self.assertEqual(Order.objects.count(), 1)

    def test_too_short_code_is_rejected(self):
        from django.core.exceptions import ValidationError

        self.issue()
        with self.assertRaises(ValidationError):
            self.enter(151, code="A1B2")


class ChartGapTests(TestCase):
    def test_line_breaks_at_hours_without_data_instead_of_bridging(self):
        from apps.reports import charts

        chart = charts.line(["6h", "7h", "8h", "9h"], [{"name": "Chờ món", "values": [5.0, 6.0, None, 4.0]}])
        path = chart["series"][0]["d"]
        self.assertEqual(path.count("M"), 2)  # hai đoạn: 6h–7h và điểm 9h đứng riêng
        self.assertTrue(path.endswith("l0.01,0"))

    def test_shortage_reads_as_words_on_status_page(self):
        from apps.core.templatetags.loi_thuong import chenh_tien

        self.assertEqual(chenh_tien(-70000), "Thiếu 70.000 đ")


class StaleDataTests(TestCase):
    def test_days_old_counts_calendar_days_in_store_time(self):
        from datetime import timedelta

        from django.utils import timezone

        from apps.core.templatetags.loi_thuong import so_ngay_truoc

        now = timezone.now()
        self.assertEqual(so_ngay_truoc(now), 0)
        self.assertEqual(so_ngay_truoc(now - timedelta(days=8)), 8)
        self.assertIsNone(so_ngay_truoc(None))


class ForgottenClockOutTests(TestCase):
    """Người quên bấm Ra ca từ hôm trước không được tính là đang làm ở Tổng quan ca và bảng điều khiển."""

    def test_on_duty_skips_clock_in_from_days_ago(self):
        from datetime import timedelta

        from django.utils import timezone

        from apps.accounts.models import Role, User
        from apps.staff.models import Attendance
        from apps.staff.timekeeping import on_duty

        d = build_menu()
        now = timezone.now()
        old = User.objects.create_user("quenra", password=PASSWORD, role=Role.PHUC_VU)
        fresh = User.objects.create_user("dangla", password=PASSWORD, role=Role.PHUC_VU)
        Attendance.objects.create(store=d["store"], user=old, role=Role.PHUC_VU, clock_in=now - timedelta(days=8))
        Attendance.objects.create(store=d["store"], user=fresh, role=Role.PHUC_VU, clock_in=now - timedelta(minutes=5))
        self.assertEqual(list(on_duty(now).values_list("user__username", flat=True)), ["dangla"])


class ReadOnlyRecordTests(TestCase):
    """Định mức đã áp dụng chỉ xem: hiện giá trị thành chữ, không còn ô chọn bị khóa."""

    def setUp(self):
        self.d = build_menu()
        self.client.login(username="chuquan", password=PASSWORD)

    def test_published_recipe_shows_text_not_disabled_inputs(self):
        html = self.client.get(reverse("masterdata:edit", args=["dinh-muc", self.d["v1"].pk])).content.decode()
        self.assertNotIn("disabled", html)
        self.assertIn('<td data-label="Nguyên vật liệu">Cà phê (gram)</td>', html)
        self.assertIn('<td data-label="Lượng" class="num">20</td>', html)
        self.assertIn('class=" is-empty">—</td>', html)  # dòng theo kích cỡ không có tùy chọn
        self.assertIn("Bản nháp chép sẵn các dòng", html)


class HomeOverdueShiftTests(TestCase):
    """Ca đã quá giờ mà chưa kết, chưa có báo cáo: trang chủ người giữ quỹ báo ngay, không chỉ ở màn Ca của tôi."""

    def setUp(self):
        self.d = build_menu()
        self.client.login(username="chuquan", password=PASSWORD)

    def test_home_lists_overdue_shift_work(self):
        from datetime import timedelta

        from django.utils import timezone

        from apps.shifts.models import Shift

        now = timezone.now()
        shift = Shift.objects.create(store=self.d["store"], name="Ca sáng", starts_at=now - timedelta(days=2),
                                     ends_at=now - timedelta(days=2) + timedelta(hours=8), approver=self.d["owner"])
        confirm_opening(shift)  # ca đã thực sự mở rồi quên kết (ca lịch chưa ai mở thì không tính là việc quá hạn)
        html = self.client.get(reverse("core:notifications")).content.decode()
        self.assertIn(f"Việc quá hạn của ca sáng {timezone.localtime(shift.starts_at):%d/%m}", html)

    def test_home_quiet_while_shift_is_running(self):
        from datetime import timedelta

        from django.utils import timezone

        from apps.shifts.models import Shift

        now = timezone.now()
        Shift.objects.create(store=self.d["store"], name="Ca sáng", starts_at=now - timedelta(hours=1),
                             ends_at=now + timedelta(hours=4), approver=self.d["owner"])
        self.assertNotIn("của ca sáng", self.client.get(reverse("core:notifications")).content.decode())


class PasswordHelpTests(TestCase):
    def test_help_names_account_and_says_old_password_stops(self):
        from apps.masterdata.resources import _password_help
        from apps.staff.models import Employee

        d = build_menu()
        user = d["waiter"]
        employee = Employee(user=user, full_name="Hà")
        self.assertIn("Tên đăng nhập: phucvu", _password_help(employee))
        self.assertIn("mật khẩu cũ hết dùng", _password_help(employee))
        user.set_unusable_password()
        self.assertIn("chưa có mật khẩu", _password_help(employee))


class CriticalCoverTests(TestCase):
    """Bảng điều khiển: số ngày còn đủ dùng không tính lô quá hạn, giống trang Tồn kho."""

    def test_expired_quantity_is_left_out(self):
        from unittest import mock

        from django.utils import timezone

        from apps.reports import services as report_services

        d = build_menu()  # sữa đặc tồn đầu kỳ 1000 ml
        d["milk"].is_critical = True
        d["milk"].save()
        today = timezone.localdate()
        with mock.patch("apps.inventory.lots.daily_usage", return_value={d["milk"].pk: 100.0}), \
                mock.patch("apps.inventory.lots.overview", return_value={d["milk"].pk: {"expired_qty": 600.0}}):
            critical, chart = report_services._critical_stock(today)
        row = next(c for c in critical if c["ingredient"].pk == d["milk"].pk)
        self.assertAlmostEqual(row["days"], 4.0)  # (1000 − 600 quá hạn) / 100 mỗi ngày
