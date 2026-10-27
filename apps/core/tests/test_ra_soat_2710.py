"""Rà soát 27/10/2026: ngày cực trị trên thanh địa chỉ, số truy vấn của màn tạo đơn và lịch làm."""

import uuid
from datetime import date, timedelta

from django.db import connection
from django.test import Client, SimpleTestCase, TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.core.dates import parse_day, parse_month
from apps.orders import services
from apps.orders.tests.helpers import PASSWORD
from apps.orders.tests.test_adjust_pay import Base
from apps.reports import services as reports


class ParseDayTests(SimpleTestCase):
    def test_out_of_range_or_bad_values_fall_back(self):
        self.assertEqual(parse_day("2026-10-27"), date(2026, 10, 27))
        self.assertEqual(parse_month("2026-10"), date(2026, 10, 1))
        for bad in ("9999-12-31", "0001-01-01", "2026-13-45", "abc", "", None):
            self.assertIsNone(parse_day(bad))
        self.assertIsNone(parse_month("9999-12"))


class ExtremeDateTests(Base):
    """Ngày 9999-12-31 trên địa chỉ trang không còn gây lỗi máy chủ; trang dùng ngày mặc định."""

    def test_pages_ignore_dates_they_cannot_handle(self):
        c = Client()
        c.login(username="chuquan", password=PASSWORD)
        for url in ("/bao-cao/doanh-thu/?tu=9999-12-31", "/bao-cao/doanh-thu/?den=9999-12-31",
                    "/bao-cao/kiem-soat/?den=9999-12-31", "/bao-cao/nguyen-lieu/?tu=9999-12-31",
                    "/don/tra-cuu/?den=9999-12-31", "/kho/so-kho/?den=9999-12-31", "/lich/?tuan=9999-12-31",
                    "/tai/?ngay=9999-12-31", "/bang-dieu-khien/?thang=9999-12", "/kho/bao-cao/?thang=9999-12"):
            self.assertEqual(c.get(url).status_code, 200, url)


class QueryCountTests(Base):
    def test_order_screen_menu_does_not_query_per_item(self):
        with CaptureQueriesContext(connection) as one:
            services.availability()
        for name in ("Bạc xỉu", "Cà phê đen"):
            item = type(self.d["item"]).objects.create(store=self.d["store"], group=self.d["item"].group, name=name,
                                                       status=self.d["item"].status)
            item.sizes.create(name="M", price=20000)
        with CaptureQueriesContext(connection) as more:
            services.availability()
        self.assertEqual(len(one), len(more))

    def test_previous_period_total_matches_line_by_line_sum(self):
        order, line = self.order(quantity=2)
        self.finish(line)
        from apps.orders import payments
        from apps.orders.tests.test_adjust_pay import key

        payments.pay_table(self.cashier, key(), order.table_id, "tien_mat")
        today = date.today()
        start, end = reports.period_bounds(today - timedelta(days=1), today + timedelta(days=1))
        expected = sum(l.unit_price * l.billable_quantity for l in reports._paid_lines(start, end))
        self.assertGreater(expected, 0)
        self.assertEqual(reports._paid_total(start, end), expected)


class TemplateIdTests(SimpleTestCase):
    def test_no_element_reuses_an_icon_id(self):
        """Ô nhập trùng mã với biểu tượng (id="i-shift") làm biểu tượng đó biến mất trên cả trang."""
        import re
        from pathlib import Path

        from django.conf import settings

        root = Path(settings.BASE_DIR) / "templates"
        icons = set(re.findall(r'<symbol id="([^"]+)"', (root / "partials/icons.html").read_text(encoding="utf-8")))
        clashes = [(str(p.relative_to(root)), i) for p in root.rglob("*.html") if p.name != "icons.html"
                   for i in re.findall(r'\bid="([^"{]+)"', p.read_text(encoding="utf-8")) if i in icons]
        self.assertEqual(clashes, [])


class FreshInstallTests(TestCase):
    def test_home_flags_missing_setup_and_names_the_menu(self):
        from apps.accounts.models import Role, User

        owner = User.objects.create_user("chu", password=PASSWORD, role=Role.CHU_QUAN)
        c = Client()
        c.force_login(owner)
        body = c.get("/").content.decode()
        self.assertIn("<h2>Quản trị</h2>", body)
        self.assertIn('<span class="status-warn">0 bàn</span>', body)
        self.assertIn("Quản trị, mục Bàn", c.get("/don/moi/").content.decode())

    def test_stock_page_asks_for_opening_stock_and_opening_keeps_its_price(self):
        from apps.accounts.models import Role, User
        from apps.core.models import Store
        from apps.inventory.models import Ingredient, StockLot

        owner = User.objects.create_user("chu", password=PASSWORD, role=Role.CHU_QUAN)
        milk = Ingredient.objects.create(store=Store.get_default(), name="Sữa đặc", unit="g", pack_size=1000,
                                         lead_time_days=1)
        c = Client()
        c.force_login(owner)
        body = c.get("/kho/").content.decode()
        self.assertIn("Chưa ghi tồn đầu kỳ", body)
        self.assertIn(f"/du-lieu/nguyen-lieu/{milk.pk}/", body)
        c.post(f"/du-lieu/nguyen-lieu/{milk.pk}/ton-dau-ky/",
               {"ton-dau-ky-quantity": "2.500", "ton-dau-ky-unit_cost": "65"})
        lot = StockLot.objects.get(ingredient=milk)
        self.assertEqual((lot.remaining, lot.unit_cost, lot.value), (2500, 65, 162500))
        self.assertNotIn("Chưa ghi tồn đầu kỳ", c.get("/kho/").content.decode())

    def test_empty_catalogues_point_to_setup_instead_of_empty_lists(self):
        from apps.accounts.models import Role, User

        owner = User.objects.create_user("chu", password=PASSWORD, role=Role.CHU_QUAN)
        c = Client()
        c.force_login(owner)
        for url in ("/kho/phieu-nhap/", "/kho/dat-hang/", "/kho/hao-hut/", "/kho/kiem-ke/", "/kho/bao-nhanh/"):
            self.assertIn("Chưa có nguyên liệu nào đang dùng", c.get(url).content.decode(), url)
        self.assertIn("Chưa có nhà cung cấp nào", c.get("/kho/phieu-nhap/").content.decode())
        self.assertIn("Chưa có ca đang mở", c.get("/du-phong/").content.decode())
        self.assertIn("Chưa có ca nào.", c.get("/ca/tinh-trang/").content.decode())

    def test_no_registration_reminder_when_next_week_has_no_shifts(self):
        from apps.accounts.models import Role, User

        waiter = User.objects.create_user("an", password=PASSWORD, role=Role.PHUC_VU)
        c = Client()
        c.force_login(waiter)
        response = c.get("/lich/cua-toi/")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("reg-banner", response.content.decode())
        from datetime import time

        from apps.core.models import Store
        from apps.schedule import services as sv
        from apps.schedule.models import WorkShift

        WorkShift.objects.create(store=Store.get_default(), name="Ca sáng", start=time(7), end=time(12),
                                 date=sv.week_start(date.today()) + timedelta(days=8))
        self.assertIn("reg-banner", c.get("/lich/cua-toi/").content.decode())


class AlertDetailTests(Base):
    def test_cancelled_paid_invoice_alert_names_the_order(self):
        from apps.control import alerts
        from apps.control.models import Alert
        from apps.orders import adjustments, payments
        from apps.orders.tests.test_adjust_pay import key

        order, line = self.order()
        self.finish(line)
        payments.pay_table(self.cashier, key(), order.table_id, "tien_mat")
        req = self.request(self.cashier, order, "huy_hoa_don")
        adjustments.decide(self.d["owner"], key(), req.pk, True)
        alerts.sync()
        alert = Alert.objects.get(subject__startswith="nl-", title__contains="Hóa đơn đã thanh toán bị hủy")
        self.assertIn(f"Đơn {order.code}", alert.detail)
        self.assertIn("đ · duyệt bởi", alert.detail)


class ErrorPageTests(TestCase):
    def test_not_found_and_server_error_pages_speak_vietnamese(self):
        from django.template import loader
        from django.test import override_settings

        with override_settings(DEBUG=False):
            response = Client().get("/khong-co-trang-nay/")
        self.assertEqual(response.status_code, 404)
        self.assertIn("Không tìm thấy trang này", response.content.decode())
        self.assertIn("Có lỗi xảy ra", loader.get_template("500.html").render())


class PasswordChangeTests(TestCase):
    def test_staff_change_their_own_password_and_it_is_logged(self):
        from apps.accounts.models import Role, User
        from apps.audit.models import AuditLog

        waiter = User.objects.create_user("an", password=PASSWORD, role=Role.PHUC_VU)
        c = Client()
        self.assertEqual(c.get("/tai-khoan/doi-mat-khau/").status_code, 302)
        c.force_login(waiter)
        self.assertIn("Đổi mật khẩu", c.get("/").content.decode())
        wrong = c.post("/tai-khoan/doi-mat-khau/", {"old_password": "sai-roi", "new_password1": "ca-phe-sua-da-77",
                                                    "new_password2": "ca-phe-sua-da-77"})
        self.assertEqual(wrong.status_code, 200)
        response = c.post("/tai-khoan/doi-mat-khau/", {"old_password": PASSWORD, "new_password1": "ca-phe-sua-da-77",
                                                       "new_password2": "ca-phe-sua-da-77"}, follow=True)
        self.assertIn("Đã đổi mật khẩu", response.content.decode())
        self.assertEqual(c.get("/").status_code, 200)  # vẫn đăng nhập
        waiter.refresh_from_db()
        self.assertTrue(waiter.check_password("ca-phe-sua-da-77"))
        self.assertTrue(AuditLog.objects.filter(object_id=str(waiter.pk), after__mat_khau="tự đổi").exists())


class CommaInTextTests(Base):
    def test_amount_formatting_does_not_turn_commas_in_names_into_dots(self):
        """Câu ngoại lệ thanh toán theo món thực nhận: dấu phẩy giữa các tùy chọn giữ nguyên, số tiền có dấu chấm."""
        from datetime import timedelta

        from apps.catalog.models import ItemSize, MenuItem
        from apps.control.models import ExceptionCase
        from apps.orders import adjustments, payments
        from apps.orders.tests.test_adjust_pay import key

        order, line = self.order()
        self.finish(line)
        tea = MenuItem.objects.create(store=self.d["store"], group=self.d["item"].group, name="Trà đào",
                                      no_ingredients=True, status=MenuItem.Status.ON_SALE)
        size = ItemSize.objects.create(item=tea, name="M", price=30000)
        req = self.request(self.d["waiter"], order, "doi_mon", line=line.pk, cups=1,
                           new_line={"item": tea.pk, "size": size.pk, "quantity": 1, "options": []})
        type(req).objects.filter(pk=req.pk).update(new_line_text="1 × Trà đào M (Ít đá, Ít đường)")
        adjustments.escalate_due(req.level_since + timedelta(minutes=10))
        payments.pay_received_items(self.authorizer, key(), order.table_id, "tien_mat")
        detail = ExceptionCase.objects.get(requests=req, kind="tt_mon_thuc_nhan").detail
        self.assertIn("(Ít đá, Ít đường)", detail)
        self.assertIn("Tiền đơn 25.000 đ, thu theo món thực nhận 30.000 đ.", detail)


class BillChangedTests(Base):
    def test_cashier_form_carries_amount_and_refuses_changed_bill(self):
        from apps.orders.models import Payment

        order, line = self.order()
        self.finish(line)
        self.client.force_login(self.cashier)
        page = self.client.get(reverse("orders:cashier"))
        self.assertContains(page, 'name="expected" value="25000"')
        url = reverse("orders:pay", args=[order.table_id])
        page = self.client.post(url, {"operation_key": uuid.uuid4().hex, "method": "tien_mat", "expected": "20000"},
                                follow=True)
        self.assertContains(page, "vừa thay đổi")
        self.assertFalse(Payment.objects.exists())
        self.client.post(url, {"operation_key": uuid.uuid4().hex, "method": "tien_mat", "expected": "25000"})
        self.assertEqual(Payment.objects.get().amount, 25000)


class ExpiryTypoTests(TestCase):
    def test_expiry_years_away_is_rejected_as_a_typo(self):
        from django.core.exceptions import ValidationError

        from apps.accounts.models import Role, User
        from apps.core.models import Store
        from apps.inventory import operations, stock
        from apps.inventory.models import Ingredient, StockLot

        owner = User.objects.create_user("chu", password=PASSWORD, role=Role.CHU_QUAN)
        milk = Ingredient.objects.create(store=Store.get_default(), name="Sữa đặc", unit="g", pack_size=1000,
                                         lead_time_days=1)
        with self.assertRaisesMessage(ValidationError, "kiểm tra lại năm"):
            stock.record_opening(milk, 100, owner, expiry_date=date.today() + timedelta(days=365 * 36))
        stock.record_opening(milk, 100, owner, expiry_date=date.today() + timedelta(days=60))
        lot = StockLot.objects.get(ingredient=milk)
        with self.assertRaisesMessage(ValidationError, "kiểm tra lại năm"):
            operations.update_lot(owner, lot.pk, "9999-12-31")
        operations.update_lot(owner, lot.pk, (date.today() + timedelta(days=30)).isoformat())
        lot.refresh_from_db()
        self.assertEqual(lot.expiry_date, date.today() + timedelta(days=30))

    def test_cash_shift_longer_than_a_day_is_a_typo(self):
        from apps.accounts.models import Role, User
        from apps.shifts.models import Shift

        owner = User.objects.create_user("chu2", password=PASSWORD, role=Role.CHU_QUAN)
        c = Client()
        c.force_login(owner)
        r = c.post("/du-lieu/ca/moi/", {"name": "Ca ngày", "starts_at": "2026-10-27T06:00", "ends_at": "2026-11-27T22:00"})
        self.assertContains(r, "Một ca dài quá 24 giờ")
        self.assertFalse(Shift.objects.exists())

    def test_ordering_dates_and_payment_terms_are_checked(self):
        from apps.accounts.models import Role, User
        from apps.core.models import Store
        from apps.inventory.models import Ingredient, PurchaseOrder, Supplier

        owner = User.objects.create_user("chu3", password=PASSWORD, role=Role.CHU_QUAN)
        milk = Ingredient.objects.create(store=Store.get_default(), name="Sữa đặc", unit="g", pack_size=1000,
                                         lead_time_days=1)
        supplier = Supplier.objects.create(store=Store.get_default(), name="Đại lý An Phát")
        c = Client()
        c.force_login(owner)
        base = {"supplier": supplier.pk, "ingredient": milk.pk, "quantity": "1000", "operation_key": "k1"}
        for raw, text in (("", "Chọn ngày giao dự kiến."), ("2020-01-01", "không được trước hôm nay"),
                          ((date.today() + timedelta(days=800)).isoformat(), "kiểm tra lại năm")):
            r = c.post("/kho/dat-hang/", {**base, "expected_date": raw}, follow=True)
            self.assertContains(r, text)
        self.assertFalse(PurchaseOrder.objects.exists())
        from django.core.exceptions import ValidationError

        from apps.inventory import operations

        with self.assertRaisesMessage(ValidationError, "từ 0 tới 365"):
            operations.create_receipt(owner, "k2", supplier.pk, [], "tra_sau", due_days="3000")

    def test_receipt_flags_a_price_far_from_the_last_one(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        from apps.accounts.models import Role, User
        from apps.core.models import Store
        from apps.inventory import operations
        from apps.inventory.models import Ingredient, Supplier

        owner = User.objects.create_user("chu4", password=PASSWORD, role=Role.CHU_QUAN)
        milk = Ingredient.objects.create(store=Store.get_default(), name="Sữa đặc", unit="g", pack_size=1000,
                                         lead_time_days=1)
        supplier = Supplier.objects.create(store=Store.get_default(), name="Đại lý An Phát")
        png = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4"
               b"\x89\x00\x00\x00\rIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82")

        def receipt(price, _):
            import uuid

            return operations.create_receipt(owner, uuid.uuid4().hex, supplier.pk, [{"ingredient": milk.pk, "quantity": "1000",
                                                                       "unit_price": price}], "tra_ngay",
                                             invoice_photo=SimpleUploadedFile("hd.png", png, "image/png"))[0]

        self.assertEqual(receipt(65, "r1")["warnings"], [])
        self.assertEqual(receipt(70, "r2")["warnings"], [])
        self.assertIn("khác nhiều so với lần nhập trước (70 đ)", receipt(65000, "r3")["warnings"][0])
        page = Client()
        page.force_login(owner)
        self.assertContains(page.get("/kho/phieu-nhap/"), 'data-last-price="65000"')


class SessionExpiryTests(TestCase):
    def test_expired_session_answers_scripts_with_json_and_post_only_urls_lead_back(self):
        from apps.accounts.models import Role, User

        anon = Client()
        r = anon.post("/don/gui/", "{}", content_type="application/json", HTTP_REFERER="http://testserver/don/moi/")
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.json()["login"], "/tai-khoan/dang-nhap/?next=/don/moi/")
        self.assertIn("Phiên đăng nhập đã hết hạn", r.json()["error"])
        self.assertEqual(anon.get("/don/moi/").status_code, 302)  # mở trang bình thường vẫn chuyển tới đăng nhập
        waiter = User.objects.create_user("an", password=PASSWORD, role=Role.PHUC_VU)
        c = Client()
        c.force_login(waiter)
        r = c.get("/don/gui/", follow=True)
        self.assertEqual(r.redirect_chain[-1][0], "/don/moi/")
        self.assertContains(r, "Thao tác trước chưa được lưu")

    def test_stale_form_token_gets_a_vietnamese_page(self):
        from apps.accounts.models import Role, User

        owner = User.objects.create_user("chu", password=PASSWORD, role=Role.CHU_QUAN)
        c = Client(enforce_csrf_checks=True)
        c.force_login(owner)
        r = c.post("/kho/phai-tra/", {"payable": "1"})
        self.assertEqual(r.status_code, 403)
        self.assertContains(r, "Trang đã cũ", status_code=403)
        r = c.post("/don/gui/", "{}", content_type="application/json")
        self.assertEqual(r.json()["error"], "Trang đã cũ nên thao tác chưa được lưu. Tải lại trang rồi làm lại.")


class InstalledAppNavigationTests(TestCase):
    """Ứng dụng đã cài: mọi lần mở trang đi qua service worker, trình duyệt gửi Sec-Fetch-Dest "empty"."""

    SW = {"HTTP_SEC_FETCH_MODE": "navigate", "HTTP_SEC_FETCH_DEST": "empty"}

    def test_logout_and_expired_form_post_still_lead_to_the_login_page(self):
        from apps.accounts.models import Role, User

        waiter = User.objects.create_user("an", password=PASSWORD, role=Role.PHUC_VU)
        c = Client()
        c.force_login(waiter)
        r = c.post("/tai-khoan/dang-xuat/", **self.SW)
        self.assertEqual((r.status_code, r["Location"]), (302, "/tai-khoan/dang-nhap/"))
        r = Client().post("/thu-ngan/", {"table": "1"}, **self.SW)  # hết phiên rồi bấm gửi biểu mẫu
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r["Location"].startswith("/tai-khoan/dang-nhap/"))
        owner = User.objects.create_user("chu", password=PASSWORD, role=Role.CHU_QUAN)
        c = Client(enforce_csrf_checks=True)
        c.force_login(owner)
        self.assertContains(c.post("/kho/phai-tra/", {"payable": "1"}, **self.SW), "Trang đã cũ", status_code=403)


class RevenueOrderTests(Base):
    def test_rows_by_day_follow_the_calendar_across_months(self):
        from apps.orders import payments
        from apps.orders.models import Payment
        from apps.orders.tests.test_adjust_pay import key

        for when in (date(2026, 9, 30), date(2026, 10, 1)):
            order, line = self.order()
            self.finish(line)
            payments.pay_table(self.cashier, key(), order.table_id, "tien_mat")
            from datetime import datetime, time

            from django.utils import timezone

            order.refresh_from_db()
            Payment.objects.filter(pk=order.payment_id).update(
                created_at=timezone.make_aware(datetime.combine(when, time(10))))
        data = reports.revenue(date(2026, 9, 29), date(2026, 10, 2), "ngay")
        self.assertEqual([r["key"] for r in data["rows"]], ["30/09/2026", "01/10/2026"])
        self.assertEqual(data["cups"], 2)


class DuplicateMasterDataTests(TestCase):
    def test_duplicate_table_code_or_group_name_is_a_field_error_not_a_crash(self):
        from apps.catalog.models import MenuGroup, Table
        from apps.orders.tests.helpers import build_menu

        d = build_menu()
        self.client.force_login(d["owner"])
        code = Table.objects.first().code
        page = self.client.post("/du-lieu/ban/moi/", {"code": code, "seats": "4", "sort_order": "1", "is_active": "on"})
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, f"Đã có số bàn &quot;{code}&quot;")
        self.assertEqual(Table.objects.filter(code=code).count(), 1)
        group = MenuGroup.objects.first()
        page = self.client.post("/du-lieu/nhom-mon/moi/", {"name": group.name, "load_factor": "1", "sort_order": "1"})
        self.assertContains(page, "Đã có tên nhóm")
        # Sửa chính mục đó (giữ nguyên tên) thì không bị coi là trùng.
        page = self.client.post(f"/du-lieu/ban/{Table.objects.first().pk}/",
                                {"code": code, "seats": "6", "sort_order": "1", "is_active": "on"})
        self.assertEqual(page.status_code, 302)


class NumberLimitMessageTests(SimpleTestCase):
    def test_limit_messages_read_naturally(self):
        from django import forms

        from apps.core.numbers import SoNguyenField, SoThapPhanField

        with self.assertRaisesMessage(forms.ValidationError, "Nhập số từ 0 trở lên."):
            SoNguyenField(min_value=0).clean("-5")
        with self.assertRaisesMessage(forms.ValidationError, "Chỉ ghi tối đa 2 chữ số sau dấu phẩy."):
            SoThapPhanField(max_digits=8, decimal_places=2).clean("1,234")


class OrderCodeNextYearTests(Base):
    def test_same_day_next_year_skips_old_codes_without_a_query_per_code(self):
        from django.utils import timezone

        from apps.orders.models import Order

        old, _ = self.order()
        prefix = f"{timezone.localdate():%d%m}-"
        year_ago = timezone.now() - timedelta(days=365)
        Order.objects.filter(pk=old.pk).update(code=prefix + "001", created_at=year_ago)
        for n in range(2, 41):  # năm trước cùng ngày có 40 đơn
            Order.objects.create(store=old.store, table=old.table, code=f"{prefix}{n:03d}", created_by=old.created_by,
                                 operation_key=uuid.uuid4().hex, status=Order.Status.PAID)
        Order.objects.filter(code__startswith=prefix).update(created_at=year_ago)
        with CaptureQueriesContext(connection) as ctx:
            code = services._next_code(old.store)
        self.assertEqual(code, prefix + "041")
        self.assertLessEqual(len(ctx.captured_queries), 4)


class ShiftOverrunTests(Base):
    def test_open_shift_long_past_its_end_is_flagged_where_money_is_taken(self):
        from django.utils import timezone

        from apps.shifts.models import Shift

        self.client.force_login(self.manager)
        self.assertNotContains(self.client.get(reverse("orders:cashier")), "đã quá giờ kết thúc")
        now = timezone.now()
        Shift.objects.filter(pk=self.shift.pk).update(starts_at=now - timedelta(hours=20),
                                                      ends_at=now - timedelta(hours=4))
        self.assertContains(self.client.get(reverse("orders:cashier")), "đã quá giờ kết thúc")
        self.assertContains(self.client.get(reverse("orders:overview")), "Tiền thu lúc này vẫn vào quỹ của ca đó")
        self.assertContains(self.client.get(reverse("reports:dashboard")), "đã quá giờ kết thúc")
        Shift.objects.filter(pk=self.shift.pk).update(ends_at=now - timedelta(minutes=30))  # khách trả muộn ít phút
        self.assertNotContains(self.client.get(reverse("orders:cashier")), "đã quá giờ kết thúc")


class TableInUseTests(Base):
    def test_table_with_open_order_cannot_be_retired(self):
        from apps.catalog.models import Table

        order, _ = self.order()
        self.client.force_login(self.manager)
        url = f"/du-lieu/ban/{order.table_id}/"
        page = self.client.post(url, {"code": order.table.code, "seats": "4", "sort_order": "1"})
        self.assertContains(page, "còn 1 đơn chưa thu tiền")
        self.assertTrue(Table.objects.get(pk=order.table_id).is_active)
        # Bàn trống thì ngừng dùng bình thường.
        page = self.client.post(f"/du-lieu/ban/{self.other_table.pk}/", {"code": "7", "seats": "4", "sort_order": "1"})
        self.assertEqual(page.status_code, 302)
        self.assertFalse(Table.objects.get(pk=self.other_table.pk).is_active)


class RequiredOptionGroupTests(Base):
    def test_item_whose_required_group_has_no_active_option_is_not_offered(self):
        from apps.catalog.models import OptionGroup
        from apps.orders.views import _menu_data as _menu

        item = self.d["item"]
        group = OptionGroup.objects.create(store=self.d["store"], name="Mức đường", is_required=True)
        option = group.options.create(name="Ít đường", is_active=False)
        item.option_groups.add(group)
        self.assertIn("tùy chọn đang dùng cho nhóm bắt buộc Mức đường", item.sale_blockers())
        names = [i["name"] for g in _menu() for i in g["items"]]
        self.assertNotIn(item.name, names)
        option.is_active = True
        option.save()
        self.assertNotIn("tùy chọn đang dùng cho nhóm bắt buộc Mức đường", item.sale_blockers())
        self.assertIn(item.name, [i["name"] for g in _menu() for i in g["items"]])


class IngredientInUseTests(Base):
    def test_ingredient_in_current_recipe_cannot_be_retired(self):
        from apps.catalog.models import MenuItem
        from apps.inventory.models import Ingredient

        coffee = self.d["coffee"]
        self.client.force_login(self.manager)
        url = f"/du-lieu/nguyen-lieu/{coffee.pk}/"
        form = self.client.get(url).context["form"]
        data = {k: v for k, v in form.initial.items() if v is not None and k != "is_active"}
        data = {k: ("on" if v is True else v) for k, v in data.items() if v is not False}
        page = self.client.post(url, data)
        self.assertContains(page, f"còn trong định mức của {self.d['item'].name}")
        self.assertTrue(Ingredient.objects.get(pk=coffee.pk).is_active)
        MenuItem.objects.filter(pk=self.d["item"].pk).update(status=MenuItem.Status.STOPPED)
        self.assertEqual(self.client.post(url, data).status_code, 302)
        self.assertFalse(Ingredient.objects.get(pk=coffee.pk).is_active)


class OwnerLockoutTests(TestCase):
    def test_owner_cannot_retire_themselves_and_profile_roles_govern_rights(self):
        from apps.accounts.models import Role
        from apps.accounts.permissions import Cap, user_can
        from apps.orders.tests.helpers import build_menu
        from apps.staff.models import Employee

        build_menu()
        boss = Employee.create_with_account(full_name="Lê Lâm", phone="0905000001", roles=[Role.CHU_QUAN])
        cashier = Employee.create_with_account(full_name="Trần Hà", phone="0905000002", roles=[Role.THU_NGAN])
        self.client.force_login(boss.user)
        form = {"full_name": "Lê Lâm", "phone": "0905000001", "roles": [Role.CHU_QUAN], "hourly_wage": "0",
                "status": "nghi_viec"}
        page = self.client.post(f"/du-lieu/nhan-vien/{boss.pk}/", form)
        self.assertContains(page, "Không tự chuyển mình sang Nghỉ việc")
        page = self.client.post(f"/du-lieu/nhan-vien/{boss.pk}/", {**form, "status": "dang_lam",
                                                                   "roles": [Role.PHA_CHE]})
        self.assertContains(page, "bỏ vai trò Chủ quán của chính mình")
        boss.refresh_from_db()
        self.assertTrue(boss.user.is_active and boss.user.is_owner)
        # Thu ngân chuyển sang chỉ phục vụ: mất quyền thu tiền dù lúc tạo tài khoản vai trò chính là Thu ngân.
        self.assertTrue(user_can(cashier.user, Cap.PAYMENT))
        page = self.client.post(f"/du-lieu/nhan-vien/{cashier.pk}/", {
            "full_name": "Trần Hà", "phone": "0905000002", "roles": [Role.PHUC_VU], "hourly_wage": "0",
            "status": "dang_lam"})
        self.assertEqual(page.status_code, 302)
        user = type(cashier.user).objects.get(pk=cashier.user_id)
        self.assertEqual((user.role, user.roles), (Role.PHUC_VU, {Role.PHUC_VU}))
        self.assertFalse(user_can(user, Cap.PAYMENT))
        # Bỏ vai trò Chủ quán của một Chủ quán khác: thôi vào trang quản trị.
        partner = Employee.create_with_account(full_name="Võ Nam", phone="0905000004", roles=[Role.CHU_QUAN])
        self.assertTrue(partner.user.is_staff)
        self.client.post(f"/du-lieu/nhan-vien/{partner.pk}/", {
            "full_name": "Võ Nam", "phone": "0905000004", "roles": [Role.PHA_CHE], "hourly_wage": "0",
            "status": "dang_lam"})
        user = type(partner.user).objects.get(pk=partner.user_id)
        self.assertEqual((user.is_owner, user.is_staff), (False, False))

    def test_rights_follow_profile_even_before_the_profile_is_saved_again(self):
        from apps.accounts.models import Role
        from apps.staff.models import Employee

        old = Employee.create_with_account(full_name="Ngô Vy", phone="0905000003", roles=[Role.THU_NGAN])
        Employee.objects.filter(pk=old.pk).update(roles=[Role.PHUC_VU])  # dữ liệu cũ: vai trò chính chưa đổi theo
        user = type(old.user).objects.get(pk=old.user_id)
        self.assertEqual(user.role, Role.THU_NGAN)
        self.assertEqual(user.roles, {Role.PHUC_VU})


class StaffPushTests(TestCase):
    def test_staff_can_turn_on_notifications_and_logout_stops_them_on_that_device(self):
        from apps.accounts.models import Role, User
        from apps.core.models import PushSubscription

        waiter = User.objects.create_user("an", password=PASSWORD, role=Role.PHUC_VU)
        other = User.objects.create_user("binh", password=PASSWORD, role=Role.PHUC_VU)
        c = Client()
        c.force_login(waiter)
        self.assertContains(c.get("/lich/cua-toi/"), "Bật trên thiết bị này")  # trước đây chỉ có ở trang Cảnh báo
        sub = {"endpoint": "https://push.example/abc", "keys": {"p256dh": "k", "auth": "a"}}
        import json

        c.post("/thong-bao/dang-ky/", json.dumps(sub), content_type="application/json")
        c2 = Client()
        c2.force_login(other)
        c2.post("/thong-bao/thoi/", {"endpoint": sub["endpoint"]})  # không phải của mình: không đổi gì
        self.assertTrue(PushSubscription.objects.get().is_active)
        c.post("/thong-bao/thoi/", {"endpoint": sub["endpoint"]})
        self.assertFalse(PushSubscription.objects.get().is_active)
        c2.post("/thong-bao/dang-ky/", json.dumps(sub), content_type="application/json")  # người sau đăng nhập máy đó
        row = PushSubscription.objects.get()
        self.assertEqual((row.user, row.is_active), (other, True))


class CashierChangeSignalTests(Base):
    def test_cashier_learns_that_tables_changed_without_reloading(self):
        import re

        order, line = self.order()
        self.client.force_login(self.cashier)
        page = self.client.get(reverse("orders:cashier")).content.decode()
        sig = re.search(r'data-sig="([0-9a-f]+)"', page).group(1)
        url = reverse("orders:cashier_changes")
        self.assertEqual(self.client.get(url).json()["sig"], sig)  # chưa có gì đổi
        self.finish(line)  # món đã pha và mang ra: bàn thu được
        self.assertNotEqual(self.client.get(url).json()["sig"], sig)
        self.client.force_login(self.d["waiter"])
        self.assertEqual(self.client.get(url).status_code, 403)
