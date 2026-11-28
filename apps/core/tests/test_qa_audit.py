"""Bộ kiểm thử bổ sung của đợt kiểm toán QA (28/11/2026, phiên bản f0e5d30).

Mỗi test có mã QA-... ở dòng đầu docstring, khớp docs/qa/QA_TEST_CASES.md. Bộ này chỉ thêm bằng chứng, không sửa
logic sản phẩm. Test thất bại là lỗi được ghi trong docs/qa/QA_BUG_REPORT.md; test mang nhãn NEEDS SPEC ghi lại hành
vi hiện tại để Hai quyết định quy tắc.
Chạy riêng: .venv\\Scripts\\python.exe manage.py test apps.core.tests.test_qa_audit
"""
import io
import uuid
import zipfile
from datetime import datetime, time, timedelta
from decimal import Decimal
from unittest import mock

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection
from django.db.models import Sum
from django.test import Client, RequestFactory, TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.accounts.permissions import Cap, user_can
from apps.audit.models import AuditLog
from apps.catalog.models import MenuItem
from apps.core.context_processors import navigation
from apps.core.idempotency import OperationKeyError
from apps.core.integrity import problems
from apps.inventory import operations as ops
from apps.inventory import stock
from apps.inventory.models import StockCount, StockMovement, Supplier
from apps.orders import adjustments, payments, services
from apps.orders.models import AdjustmentReason, AdjustmentRequest, Order, Payment
from apps.orders.tests.helpers import PASSWORD, build_menu, cart, confirm_opening, levels
from apps.shifts import services as shifts
from apps.shifts.models import CashEntry, Refund, Shift


def key():
    return uuid.uuid4().hex


def nav_urls(user):
    request = RequestFactory().get("/")
    request.user = user
    return navigation(request)["NAV_ITEMS"]


class Base(TestCase):
    """Quán mẫu: Cà phê sữa M 25.000 đ (20 g cà phê + 30 ml sữa đặc), topping Kem muối +8.000 đ (+15 ml sữa đặc),
    tồn 2.000 g cà phê và 1.000 ml sữa đặc, bàn 5, một ca đang mở do Chủ quán phụ trách."""

    def setUp(self):
        self.d = build_menu()
        self.owner, self.waiter, self.barista = self.d["owner"], self.d["waiter"], self.d["barista"]
        self.cashier = User.objects.create_user("thungan", password=PASSWORD, role=Role.THU_NGAN)
        now = timezone.now()
        self.shift = Shift.objects.create(store=self.d["store"], name="Ca kiểm thử", starts_at=now - timedelta(hours=1),
                                          ends_at=now + timedelta(hours=6), approver=self.owner,
                                          payment_authorizer=self.cashier)
        self.reason = AdjustmentReason.objects.get(name="Khách đổi ý")

    def submit(self, quantity=1, options=(), user=None, table=None):
        payload = cart(self.d, quantity=quantity, options=options)
        if table is not None:
            payload["table"] = table.pk
        result, _ = services.submit_order(user or self.waiter, key(), payload)
        return Order.objects.get(pk=result["order_id"])

    def finish(self, order):
        for line in order.lines.all():
            services.complete_line(self.barista, key(), line.pk, line.pending_quantity, line.done_quantity)
            services.serve_line(self.waiter, key(), line.pk)

    def pay(self, method="tien_mat", user=None, op=None):
        if method == "tien_mat" and not self.shift.cash_entries.filter(kind=CashEntry.Kind.OPENING).exists():
            confirm_opening(self.shift)  # quy tắc 28/11: thu tiền mặt cần tiền đầu ca
        result, _ = payments.pay_table(user or self.cashier, op or key(), self.d["table"].pk, method,
                                       transfer_confirmed=method == "chuyen_khoan")
        return result

    def request(self, user, order, kind, **fields):
        result, _ = adjustments.create_request(user, key(), {"order": order.pk, "kind": kind, "reason": self.reason.pk,
                                                             **fields})
        return AdjustmentRequest.objects.get(pk=result["request"])


# ------------------------------------------------------------- Giai đoạn 1: tài khoản, phân quyền, nhật ký

class AuthTests(Base):
    def test_qa_auth_01_lockout_then_unlock_after_time(self):
        """QA-AUTH-01: sai mật khẩu đủ số lần thì tạm khóa; mật khẩu đúng khi đang khóa vẫn bị chặn; hết hạn khóa thì vào được."""
        from django.conf import settings

        url = reverse("accounts:login")
        for _ in range(settings.LOGIN_MAX_FAILED_ATTEMPTS):
            self.client.post(url, {"username": "phucvu", "password": "sai-mat-khau"})
        self.waiter.refresh_from_db()
        self.assertTrue(self.waiter.is_temporarily_locked)
        self.client.post(url, {"username": "phucvu", "password": PASSWORD})
        self.assertNotIn("_auth_user_id", self.client.session)
        User.objects.filter(pk=self.waiter.pk).update(locked_until=timezone.now() - timedelta(seconds=1))
        self.client.post(url, {"username": "phucvu", "password": PASSWORD})
        self.assertIn("_auth_user_id", self.client.session)

    def test_qa_auth_02_idle_session_expires(self):
        """QA-AUTH-02: không thao tác quá thời gian chờ (SESSION_COOKIE_AGE) thì phải đăng nhập lại."""
        from django.conf import settings

        self.client.login(username="phucvu", password=PASSWORD)
        self.assertEqual(self.client.get(reverse("orders:create")).status_code, 200)
        later = timezone.now() + timedelta(seconds=settings.SESSION_COOKIE_AGE + 60)
        with mock.patch("django.utils.timezone.now", return_value=later):
            response = self.client.get(reverse("orders:create"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response["Location"])

    def test_qa_auth_03_anonymous_redirected_everywhere(self):
        """QA-AUTH-03: mọi màn hình trên menu của Chủ quán đều chuyển về đăng nhập khi chưa đăng nhập."""
        anon = Client()
        bad = [i["url"] for i in nav_urls(self.owner) if anon.get(i["url"]).status_code != 302]
        self.assertEqual(bad, [])


class PermissionMatrixTests(Base):
    def test_qa_perm_01_every_menu_screen_matches_declared_capability(self):
        """QA-PERM-01: mỗi vai trò, mỗi màn hình trên menu của Chủ quán: vào được (200) khi và chỉ khi vai trò có quyền."""
        mismatches, matrix = [], {}
        owner_items = nav_urls(self.owner)
        for user in (self.waiter, self.barista, self.cashier):
            client = Client()
            client.force_login(user)
            allowed = {i["url"] for i in nav_urls(user)}
            for item in owner_items:
                status = client.get(item["url"]).status_code
                matrix[(user.username, item["label"])] = status
                if (status == 200) != (item["url"] in allowed):
                    mismatches.append((user.username, item["label"], item["url"], status))
        self.assertEqual(mismatches, [])
        self.assertGreater(len(matrix), 100)

    def test_qa_perm_02_direct_post_beyond_role_is_rejected(self):
        """QA-PERM-02: phục vụ gửi POST thẳng vào màn của Chủ quán và thu ngân thì máy chủ trả 403, dữ liệu không đổi."""
        order = self.submit()
        self.finish(order)
        c = Client()
        c.force_login(self.waiter)
        targets = [reverse("orders:cashier"), reverse("control:parameters"), reverse("schedule:board"),
                   reverse("masterdata:list", args=["mon"]), reverse("masterdata:create", args=["mon"]),
                   reverse("inventory:count")]
        statuses = {u: c.post(u, {"action": "x"}).status_code for u in targets}
        statuses[reverse("orders:approvals")] = c.post(reverse("orders:approvals")).status_code  # chỉ nhận GET: 405
        self.assertTrue(all(s in (403, 405) for s in statuses.values()), statuses)
        self.assertFalse(Payment.objects.exists())

    def test_qa_perm_03_service_layer_rules_not_only_ui(self):
        """QA-PERM-03: tầng nghiệp vụ tự chặn: pha chế không xác nhận được kiểm kê vượt ngưỡng; thu ngân không xác minh tổn thất."""
        ops.submit_count(self.barista, key(), self.d["milk"].pk, "500", "Đổ vỡ")
        with self.assertRaises(ValidationError):
            ops.confirm_count(self.barista, StockCount.objects.get().pk)
        from apps.control import services as control

        case = control.open_case(self.owner, "Thử", operation_key=key())
        with self.assertRaises(ValidationError):
            control.verify(self.cashier, case, 1000)


class AuditTests(Base):
    def test_qa_audit_01_logs_actor_and_are_append_only(self):
        """QA-AUDIT-01: tạo đơn, pha xong, thu tiền đều có nhật ký kèm người làm; nhật ký không sửa, không xóa qua ORM."""
        order = self.submit()
        self.finish(order)
        self.pay()
        types = set(AuditLog.objects.values_list("object_type", flat=True))
        self.assertTrue({"orders.Order", "orders.OrderLine", "orders.Payment"} <= types, types)
        self.assertFalse(AuditLog.objects.filter(object_type="orders.Payment", actor__isnull=True).exists())
        entry = AuditLog.objects.first()
        with self.assertRaises(Exception):
            entry.reason = "sửa"
            entry.save()
        with self.assertRaises(Exception):
            entry.delete()


# ------------------------------------------------------------- Giai đoạn 2: dữ liệu nền, định mức, đơn vị

class MasterDataTests(Base):
    def test_qa_md_01_price_change_keeps_old_order_price(self):
        """QA-MD-01: đổi giá sau khi có đơn thì đơn cũ giữ giá lúc bán, đơn mới theo giá mới."""
        old = self.submit()
        self.d["size_m"].price = 30000
        self.d["size_m"].save()
        new = self.submit()
        self.assertEqual((old.lines.get().unit_price, new.lines.get().unit_price), (25000, 30000))
        old.refresh_from_db()
        self.assertEqual(old.total, 25000)

    def test_qa_md_02_new_recipe_version_only_affects_new_orders(self):
        """QA-MD-02: định mức mới chỉ áp cho đơn mới; đơn đang chờ pha vẫn trừ theo định mức lúc nhận đơn."""
        from apps.inventory.models import RecipeLine, RecipeVersion

        waiting = self.submit()
        v2 = RecipeVersion.objects.create(item=self.d["item"])
        RecipeLine.objects.create(version=v2, size=self.d["size_m"], ingredient=self.d["coffee"], quantity=25)
        RecipeLine.objects.create(version=v2, size=self.d["size_m"], ingredient=self.d["milk"], quantity=30)
        RecipeLine.objects.create(version=v2, option=self.d["cream"], ingredient=self.d["milk"], quantity=15)
        v2.publish(self.owner)
        start = levels(self.d["coffee"])[0]
        services.complete_line(self.barista, key(), waiting.lines.get().pk, 1, 0)
        self.assertEqual(start - levels(self.d["coffee"])[0], 20)
        newer = self.submit()
        services.complete_line(self.barista, key(), newer.lines.get().pk, 1, 0)
        self.assertEqual(start - levels(self.d["coffee"])[0], 45)

    def test_qa_md_03_price_zero_on_selling_item_via_form(self):
        """QA-MD-03: Chủ quán sửa giá một cỡ của món Đang bán thành 0 trên form Món và giá: phải bị chặn
        (giá 0 không được mở bán). Kiểm tra qua đúng màn hình, không qua ORM."""
        import re

        c = Client()
        c.force_login(self.owner)
        url = reverse("masterdata:edit", args=["mon", self.d["item"].pk])
        html = c.get(url).content.decode()
        data = {}
        for tag in re.findall(r"<(?:input|select|textarea)[^>]*>", html):
            name = re.search(r'name="([^"]+)"', tag)
            if not name or 'type="submit"' in tag:
                continue
            value = re.search(r'value="([^"]*)"', tag)
            if 'type="checkbox"' in tag and "checked" not in tag:
                continue
            data[name.group(1)] = value.group(1) if value else ("on" if 'type="checkbox"' in tag else "")
        for sel in re.finditer(r'<select[^>]*name="([^"]+)"[^>]*>(.*?)</select>', html, re.S):
            chosen = re.search(r'<option value="([^"]*)"[^>]*selected', sel.group(2))
            data[sel.group(1)] = chosen.group(1) if chosen else ""
        price_field = next(k for k, v in data.items() if k.endswith("-price") and v.replace(".", "") == "25000")
        # Đối chứng trước: giá hợp lệ 26000 phải lưu được, chứng tỏ dữ liệu POST đầy đủ
        data[price_field] = "26000"
        ok = c.post(url, data)
        self.d["size_m"].refresh_from_db()
        print("QA-MD-03 đối chứng 26000:", ok.status_code, self.d["size_m"].price)
        self.assertEqual(self.d["size_m"].price, 26000, "POST đối chứng không lưu được, phép thử giá 0 không có giá trị")
        data[price_field] = "0"
        resp = c.post(url, data)
        errors = re.findall(r'class="error">([^<]*)<', resp.content.decode())
        self.d["size_m"].refresh_from_db()
        print("QA-MD-03 gửi giá 0:", resp.status_code, errors[:3], "giá sau:", self.d["size_m"].price)
        try:
            zero_order = self.submit()
            print("QA-MD-03 đơn tạo được, tổng tiền:", zero_order.total)
        except Exception as exc:  # noqa: BLE001
            print("QA-MD-03 tạo đơn bị chặn:", type(exc).__name__, exc)
        sellable_at_zero = self.d["size_m"].price == 0 and MenuItem.objects.sellable().filter(pk=self.d["item"].pk).exists()
        self.assertFalse(sellable_at_zero, "Món Đang bán vẫn bán được với giá 0 đ sau khi sửa trên form")

    def test_qa_md_04_decimal_quantities_do_not_drift(self):
        """QA-MD-04: định mức số lẻ 0,1 g lặp 30 lần không sinh sai số: tồn giảm đúng 3,0 g."""
        from apps.inventory.models import RecipeLine

        RecipeLine.objects.filter(ingredient=self.d["coffee"]).update(quantity=Decimal("0.1"))
        start = levels(self.d["coffee"])[0]
        for _ in range(30):
            order = self.submit()
            services.complete_line(self.barista, key(), order.lines.get().pk, 1, 0)
        self.assertEqual(start - levels(self.d["coffee"])[0], Decimal("3.0"))


# ------------------------------------------------------------- Giai đoạn 3: bán hàng xuyên suốt

class SalesFlowTests(Base):
    def test_qa_sale_a_single_order_end_to_end(self):
        """QA-SALE-A: đơn 2 ly có topping + 1 ly ít đá: giá, giữ kho, trừ kho, thu tiền, ghi chú và sổ khớp nhau."""
        payload = cart(self.d, quantity=2, options=[self.d["cream"]])
        payload["lines"].append({"item": self.d["item"].pk, "size": self.d["size_m"].pk,
                                 "options": [self.d["less_ice"].pk], "quantity": 1, "note": "ít ngọt"})
        result, _ = services.submit_order(self.waiter, key(), payload)
        order = Order.objects.get(pk=result["order_id"])
        self.assertEqual(order.total, 2 * 33000 + 25000)
        self.assertEqual(levels(self.d["coffee"])[1], 60)
        self.assertEqual(levels(self.d["milk"])[1], 2 * 45 + 30)
        self.finish(order)
        self.assertEqual(levels(self.d["coffee"]), (Decimal(1940), Decimal(0), Decimal(1940)))
        self.assertEqual(levels(self.d["milk"]), (Decimal(880), Decimal(0), Decimal(880)))
        result = self.pay()
        order.refresh_from_db()
        self.assertEqual((order.status, result["amount"]), (Order.Status.PAID, 91000))
        self.assertEqual(order.lines.filter(note="ít ngọt").count(), 1)
        self.assertEqual(problems(), [])

    def test_qa_sale_c_shortage_rejects_whole_order(self):
        """QA-SALE-C: thiếu nguyên liệu thì không nhận cả đơn, không giữ dở dang, tồn không âm."""
        payload = cart(self.d, quantity=50)
        payload["lines"] = payload["lines"] * 3  # 150 ly × 20 g = 3.000 g > 2.000 g tồn
        with self.assertRaises(stock.InsufficientStock) as err:
            services.submit_order(self.waiter, key(), payload)
        self.assertEqual(err.exception.shortages[0]["ingredient"], "Cà phê")
        self.assertFalse(Order.objects.exists())
        self.assertEqual(levels(self.d["coffee"]), (Decimal(2000), Decimal(0), Decimal(2000)))

    def test_qa_sale_d_same_key_resend_and_conflicting_payload(self):
        """QA-SALE-D: gửi lại cùng mã không sinh đơn thứ hai, không giữ kho hai lần; cùng mã khác nội dung bị từ chối."""
        op = key()
        first, repeated1 = services.submit_order(self.waiter, op, cart(self.d, quantity=2))
        second, repeated2 = services.submit_order(self.waiter, op, cart(self.d, quantity=2))
        self.assertEqual((repeated1, repeated2, first["order_id"]), (False, True, second["order_id"]))
        self.assertEqual(Order.objects.count(), 1)
        self.assertEqual(levels(self.d["coffee"])[1], 40)
        with self.assertRaises(OperationKeyError):
            services.submit_order(self.waiter, op, cart(self.d, quantity=3))

    def test_qa_sale_d2_payment_resend_and_second_key(self):
        """QA-SALE-D2: bấm thu tiền hai lần cùng mã chỉ có một giao dịch; mã khác thì báo bàn không còn đơn."""
        self.finish(self.submit())
        op = key()
        self.pay(op=op)
        self.pay(op=op)
        with self.assertRaises(ValidationError):
            self.pay()
        self.assertEqual(Payment.objects.count(), 1)

    def test_qa_sale_e_payment_with_stale_amount_is_refused(self):
        """QA-SALE-E: thu theo số tiền cũ trên màn khi bàn vừa có thêm đơn thì bị chặn, không ghi tiền."""
        self.finish(self.submit())
        stale = payments.bill(self.d["table"])["amount"]
        self.finish(self.submit())
        with self.assertRaises(ValidationError):
            payments.pay_table(self.cashier, key(), self.d["table"].pk, "tien_mat", expected=stale)
        self.assertFalse(Payment.objects.exists())

    def test_qa_sale_f_cash_blocked_before_opening_cash(self):
        """QA-SALE-F (quyết định 28/11): ca chưa xác nhận tiền đầu ca thì không thu tiền mặt; chuyển khoản vẫn được;
        ghi tiền đầu ca xong thì thu tiền mặt được."""
        self.finish(self.submit())
        with self.assertRaises(ValidationError):
            payments.pay_table(self.cashier, key(), self.d["table"].pk, "tien_mat")
        self.assertFalse(Payment.objects.exists())
        shifts.add_cash_entry(self.cashier, key(), self.shift.pk, "dau_ca", 0)
        payments.pay_table(self.cashier, key(), self.d["table"].pk, "tien_mat")
        self.assertEqual(Payment.objects.get().shift, self.shift)

    def test_qa_sale_f2_transfer_allowed_without_opening_cash(self):
        """QA-SALE-F2: chuyển khoản không phụ thuộc tiền đầu ca."""
        self.finish(self.submit())
        payments.pay_table(self.cashier, key(), self.d["table"].pk, "chuyen_khoan", transfer_confirmed=True)
        self.assertEqual(Payment.objects.get().method, "chuyen_khoan")

    def test_qa_sale_g_staff_not_clocked_in_cannot_send_order(self):
        """QA-SALE-G (quyết định 28/11): trên màn Tạo đơn, nhân viên chưa vào ca không gửi được đơn; vào ca rồi thì
        được; Chủ quán không cần chấm công; gửi lại đơn đã nhận vẫn trả đúng đơn đó."""
        import json

        from apps.staff import timekeeping

        c = Client()
        c.force_login(self.waiter)
        body = {"operation_key": key(), "order": cart(self.d)}
        send = lambda b: c.post(reverse("orders:submit"), json.dumps(b), content_type="application/json")  # noqa: E731
        self.assertEqual(send(body).status_code, 400)
        self.assertFalse(Order.objects.exists())
        self.assertContains(c.get(reverse("orders:create")), "chưa vào ca")
        timekeeping.clock_in(self.waiter, key(), Role.PHUC_VU)
        self.assertEqual(send(body).status_code, 200)
        timekeeping.clock_out(self.waiter, key())
        again = send(body)
        self.assertEqual((again.status_code, Order.objects.count()), (200, 1))  # gửi lại sau khi ra ca: cùng đơn
        owner = Client()
        owner.force_login(self.owner)
        r = owner.post(reverse("orders:submit"), json.dumps({"operation_key": key(), "order": cart(self.d)}),
                       content_type="application/json")
        self.assertEqual(r.status_code, 200)


# ------------------------------------------------------------- Giai đoạn 4: pha chế, phục vụ, điều chỉnh, hủy, hoàn

class BarAndServeTests(Base):
    def test_qa_bar_01_cannot_overcomplete_or_double_consume(self):
        """QA-BAR-01: bấm Xong vượt số ly chỉ tính số còn lại; bấm lại từ màn cũ không trừ kho thêm."""
        line = self.submit(quantity=2).lines.get()
        services.complete_line(self.barista, key(), line.pk, 5, 0)
        line.refresh_from_db()
        self.assertEqual((line.done_quantity, levels(self.d["coffee"])[0]), (2, Decimal(1960)))
        result, _ = services.complete_line(self.barista, key(), line.pk, 2, 0)
        self.assertEqual(result["applied"], 0)
        self.assertEqual(levels(self.d["coffee"])[0], Decimal(1960))

    def test_qa_bar_02_serve_only_after_done_and_idempotent(self):
        """QA-BAR-02: không ghi mang ra trước khi pha xong; ghi mang ra hai lần không đổi gì."""
        line = self.submit().lines.get()
        with self.assertRaises(ValidationError):
            services.serve_line(self.waiter, key(), line.pk)
        services.complete_line(self.barista, key(), line.pk, 1, 0)
        services.serve_line(self.waiter, key(), line.pk)
        result, _ = services.serve_line(self.waiter, key(), line.pk)
        self.assertFalse(result["applied"])

    def test_qa_bar_03_cashier_can_mark_done(self):
        """QA-BAR-03: thu ngân bấm Xong ở quầy được (quyết định 21/11), trừ kho một lần như pha chế."""
        self.assertTrue(user_can(self.cashier, Cap.BAR_PREPARE))
        services.complete_line(self.cashier, key(), self.submit().lines.get().pk, 1, 0)
        self.assertEqual(levels(self.d["coffee"])[0], Decimal(1980))


class AdjustmentRefundTests(Base):
    def test_qa_adj_01_requester_cannot_approve_own(self):
        """QA-ADJ-01: phục vụ không duyệt được yêu cầu của chính mình (và không có quyền duyệt)."""
        order = self.submit(quantity=2)
        req = self.request(self.waiter, order, AdjustmentRequest.Kind.CANCEL_ITEMS, line=order.lines.get().pk, cups=1)
        with self.assertRaises((ValidationError, PermissionDenied)):
            adjustments.decide(self.waiter, key(), req.pk, True)
        req.refresh_from_db()
        self.assertEqual(req.status, AdjustmentRequest.Status.PENDING)

    def test_qa_adj_02_cancel_after_prep_keeps_stock_consumed(self):
        """QA-ADJ-02: hủy 1 ly đã pha: tổng tiền giảm, kho không hoàn (đã tiêu hao), sổ vẫn khớp."""
        order = self.submit(quantity=2)
        line = order.lines.get()
        services.complete_line(self.barista, key(), line.pk, 2, 0)
        req = self.request(self.waiter, order, AdjustmentRequest.Kind.CANCEL_ITEMS, line=line.pk, cups=1)
        adjustments.decide(self.owner, key(), req.pk, True)
        order.refresh_from_db()
        self.assertEqual(order.total, 25000)
        self.assertEqual(levels(self.d["coffee"])[0], Decimal(1960))
        self.assertEqual(problems(), [])

    def test_qa_adj_03_cancel_before_prep_releases_reservation(self):
        """QA-ADJ-03: hủy ly chưa pha thì trả phần đang giữ."""
        order = self.submit(quantity=2)
        req = self.request(self.waiter, order, AdjustmentRequest.Kind.CANCEL_ITEMS, line=order.lines.get().pk, cups=1)
        adjustments.decide(self.owner, key(), req.pk, True)
        self.assertEqual(levels(self.d["coffee"])[1], 20)

    def test_qa_adj_04_decision_twice_is_single(self):
        """QA-ADJ-04: duyệt cùng yêu cầu hai lần (hai mã khác nhau) không trừ tiền hai lần."""
        order = self.submit(quantity=3)
        req = self.request(self.waiter, order, AdjustmentRequest.Kind.CANCEL_ITEMS, line=order.lines.get().pk, cups=1)
        adjustments.decide(self.owner, key(), req.pk, True)
        try:
            adjustments.decide(self.owner, key(), req.pk, True)
        except ValidationError:
            pass
        order.refresh_from_db()
        self.assertEqual(order.total, 50000)

    def test_qa_ref_01_cancel_paid_invoice_refund_once(self):
        """QA-REF-01: hủy hóa đơn đã thu: một khoản hoàn đúng phương thức; xác nhận hoàn hai lần chỉ ghi một lần;
        quỹ ca trừ một lần; sổ khớp."""
        shifts.add_cash_entry(self.cashier, key(), self.shift.pk, "dau_ca", 100000)
        order = self.submit()
        self.finish(order)
        self.pay(method="tien_mat")
        req = self.request(self.cashier, order, AdjustmentRequest.Kind.CANCEL_PAID)
        adjustments.decide(self.owner, key(), req.pk, True)
        refund = Refund.objects.get()
        self.assertEqual((refund.method, refund.amount), (Refund.Method.CASH, 25000))
        shifts.confirm_refund(self.cashier, key(), refund.pk)
        again, _ = shifts.confirm_refund(self.cashier, key(), refund.pk)
        self.assertFalse(again["applied"])
        f = shifts.figures(self.shift)
        self.assertEqual((f["refunds_cash"], f["expected_cash"]), (25000, 100000))
        self.assertEqual(problems(), [])

    def test_qa_ref_02_transfer_refund_follows_original_method(self):
        """QA-REF-02: khách trả chuyển khoản thì hoàn chuyển khoản, không trừ tiền mặt trong két."""
        order = self.submit()
        self.finish(order)
        self.pay(method="chuyen_khoan")
        req = self.request(self.cashier, order, AdjustmentRequest.Kind.CANCEL_PAID)
        adjustments.decide(self.owner, key(), req.pk, True)
        refund = Refund.objects.get()
        shifts.confirm_refund(self.cashier, key(), refund.pk)
        f = shifts.figures(self.shift)
        self.assertEqual((refund.method, f["refunds_cash"], f["refunds_transfer"]), (Refund.Method.TRANSFER, 0, 25000))


# ------------------------------------------------------------- Giai đoạn 5: kho

class InventoryTests(Base):
    def test_qa_inv_01_waste_cannot_exceed_physical(self):
        """QA-INV-01: hao hụt vượt tồn vật lý bị chặn; hao hụt hợp lệ trừ đúng, sổ kho khớp."""
        with self.assertRaises(ValidationError):
            ops.record_waste(self.barista, key(), self.d["milk"].pk, "1001", "do_vo")
        ops.record_waste(self.barista, key(), self.d["milk"].pk, "100", "do_vo")
        self.assertEqual(levels(self.d["milk"])[0], Decimal(900))
        self.assertEqual(list(stock.ledger_problems()), [])

    def test_qa_inv_02_count_threshold_and_single_adjustment(self):
        """QA-INV-02: lệch nhỏ điều chỉnh ngay; lệch vượt ngưỡng chờ Chủ quán; xác nhận hai lần chỉ điều chỉnh một lần."""
        ops.submit_count(self.barista, key(), self.d["coffee"].pk, "1990")
        self.assertEqual(levels(self.d["coffee"])[0], Decimal(1990))
        ops.submit_count(self.barista, key(), self.d["milk"].pk, "500", "Đổ vỡ chưa ghi")
        count = StockCount.objects.get(status=StockCount.Status.PENDING)
        self.assertEqual(levels(self.d["milk"])[0], Decimal(1000))
        ops.confirm_count(self.owner, count.pk)
        ops.confirm_count(self.owner, count.pk)
        self.assertEqual(levels(self.d["milk"])[0], Decimal(500))
        self.assertEqual(StockMovement.objects.filter(kind=StockMovement.Kind.COUNT, ingredient=self.d["milk"]).count(), 1)

    def test_qa_inv_03_receipt_requires_invoice_photo(self):
        """QA-INV-03: phiếu nhập không có ảnh hóa đơn bị từ chối, tồn không đổi."""
        sup = Supplier.objects.create(store=self.d["store"], name="NCC thử")
        with self.assertRaises(ValidationError):
            ops.create_receipt(self.owner, key(), sup.pk, [{"ingredient": self.d["milk"].pk, "quantity": "100",
                                                            "unit_price": 50}], "tra_ngay")
        self.assertEqual(levels(self.d["milk"])[0], Decimal(1000))

    def test_qa_inv_04_ledger_sums_to_balance(self):
        """QA-INV-04: sau bán, hao hụt, kiểm kê: tổng biến động sổ kho bằng tồn vật lý từng nguyên liệu."""
        self.finish(self.submit(quantity=3))
        ops.record_waste(self.barista, key(), self.d["coffee"].pk, "15", "hu_hong")
        ops.submit_count(self.barista, key(), self.d["coffee"].pk, "1920")
        for ing in (self.d["coffee"], self.d["milk"]):
            total = StockMovement.objects.filter(ingredient=ing).aggregate(s=Sum("quantity"))["s"]
            self.assertEqual(total, levels(ing)[0], ing.name)


# ------------------------------------------------------------- Giai đoạn 6: ca, quỹ, kết ca

class ShiftMoneyTests(Base):
    def test_qa_shift_01_handover_rules(self):
        """QA-SHIFT-01: không nộp cho chính mình, cho người không giữ quỹ, hoặc quá tiền két; khoản nộp chưa xác nhận
        thì không kết ca; chỉ người nhận xác nhận được."""
        shifts.add_cash_entry(self.cashier, key(), self.shift.pk, "dau_ca", 200000)
        for receiver, amount in ((self.cashier, 50000), (self.waiter, 50000), (self.owner, 900000)):
            with self.assertRaises(ValidationError):
                shifts.add_cash_entry(self.cashier, key(), self.shift.pk, "nop", amount, receiver_id=receiver.pk)
        shifts.add_cash_entry(self.cashier, key(), self.shift.pk, "nop", 50000, receiver_id=self.owner.pk)
        with self.assertRaises(ValidationError):
            shifts.close_shift(self.cashier, self.shift.pk)
        entry = CashEntry.objects.get(kind="nop")
        with self.assertRaises(ValidationError):
            shifts.confirm_handover(self.cashier, entry.pk)
        shifts.confirm_handover(self.owner, entry.pk)
        shifts.close_shift(self.cashier, self.shift.pk)

    def test_qa_shift_02_close_report_reconcile(self):
        """QA-SHIFT-02: còn đơn chưa thu thì không kết ca; báo cáo thiếu 20.000 đ sinh đúng một chênh lệch; gửi lại cùng
        số không đối soát lần hai; gửi số khác bị chặn; ca đã kết không ghi thêm quỹ."""
        shifts.add_cash_entry(self.cashier, key(), self.shift.pk, "dau_ca", 100000)
        order = self.submit(quantity=2)
        with self.assertRaises(ValidationError):
            shifts.close_shift(self.cashier, self.shift.pk)
        self.finish(order)
        self.pay(method="tien_mat")
        shifts.close_shift(self.cashier, self.shift.pk)
        expected = shifts.figures(self.shift)["expected_cash"]
        self.assertEqual(expected, 150000)
        shifts.submit_report(self.cashier, self.shift.pk, expected - 20000, 0)
        shifts.submit_report(self.cashier, self.shift.pk, expected - 20000, 0)
        gaps = list(self.shift.discrepancies.current())
        self.assertEqual([(g.method, g.difference) for g in gaps], [("tien_mat", -20000)])
        with self.assertRaises(ValidationError):
            shifts.submit_report(self.cashier, self.shift.pk, expected, 0)
        with self.assertRaises(ValidationError):
            shifts.add_cash_entry(self.cashier, key(), self.shift.pk, "chi", 1000, category="sua_chua", note="x")

    def test_qa_shift_03_expense_needs_photo_over_threshold(self):
        """QA-SHIFT-03: khoản chi từ ngưỡng ảnh chứng từ trở lên mà không có ảnh thì bị chặn."""
        from apps.core import params

        limit = params.get("receipt_photo_threshold")
        shifts.add_cash_entry(self.cashier, key(), self.shift.pk, "dau_ca", limit * 2)
        with self.assertRaises(ValidationError):
            shifts.add_cash_entry(self.cashier, key(), self.shift.pk, "chi", limit, category="sua_chua", note="Sửa máy")


# ------------------------------------------------------------- Giai đoạn 7: ngoại lệ, tổn thất

class StaleShiftTests(Base):
    def test_qa_shift_04_forgotten_shift_does_not_take_new_money_and_new_shift_opens_now(self):
        """QA-SHIFT-04 (yêu cầu 28/11): ca quên kết đã quá giờ hơn 2 giờ thì đơn và tiền mới không vào ca đó; thu ngân
        mở ca theo giờ hiện tại; ca cũ vẫn kết được sau."""
        from apps.shifts import from_schedule

        confirm_opening(self.shift)
        now = timezone.now()
        Shift.objects.filter(pk=self.shift.pk).update(starts_at=now - timedelta(hours=20), ends_at=now - timedelta(hours=5))
        self.assertIsNone(Shift.objects.operating())
        self.assertEqual(list(Shift.objects.stale()), [Shift.objects.get(pk=self.shift.pk)])
        c = Client()
        c.force_login(self.cashier)
        self.assertContains(c.get(reverse("shifts:my_shift")), "Mở ca theo giờ hiện tại")
        r = c.post(reverse("shifts:open_now"))
        new = Shift.objects.exclude(pk=self.shift.pk).get()
        self.assertRedirects(r, reverse("shifts:my_shift_detail", args=[new.pk]))
        self.assertEqual(Shift.objects.operating(), new)
        again, created = from_schedule.open_now(self.cashier)  # bấm lại: không mở ca thứ hai
        self.assertEqual((again, created, Shift.objects.count()), (new, False, 2))
        order = self.submit()
        self.assertEqual(order.shift, new)
        self.finish(order)
        shifts.add_cash_entry(self.cashier, key(), new.pk, "dau_ca", 0)
        self.pay()
        self.assertEqual(Payment.objects.get().shift, new)
        shifts.close_shift(self.owner, self.shift.pk)  # ca cũ kết sau, không có tiền mới lọt vào
        self.assertEqual(Shift.objects.get(pk=self.shift.pk).closed_cash_revenue, 0)
        self.assertEqual(problems(), [])


class LossCaseTests(Base):
    def test_qa_loss_01_recovery_bounded_and_owner_only(self):
        """QA-LOSS-01: thu hồi sau xác minh, không vượt phần còn lại, chỉ Chủ quán; gửi lại cùng mã không ghi hai lần."""
        from apps.control import services as control
        from apps.control.models import LossRecovery

        case = control.open_case(self.owner, "Thiếu két", operation_key=key())
        with self.assertRaises(ValidationError):
            control.recover(self.owner, case, 1000, operation_key=key())
        control.verify(self.owner, case, 50000)
        with self.assertRaises(ValidationError):
            control.recover(self.cashier, case, 1000, operation_key=key())
        with self.assertRaises(ValidationError):
            control.recover(self.owner, case, 60000, operation_key=key())
        op = key()
        control.recover(self.owner, case, 30000, operation_key=op)
        control.recover(self.owner, case, 30000, operation_key=op)
        self.assertEqual(sum(r.amount for r in LossRecovery.objects.all()), 30000)


# ------------------------------------------------------------- Giai đoạn 8: báo cáo, Excel, bảng điều khiển

class ReportTests(Base):
    def test_qa_rep_01_revenue_equals_payments_minus_refunds(self):
        """QA-REP-01: doanh thu kỳ = tiền thu − tiền hoàn đã trả; mọi chiều xem cộng lại bằng nhau."""
        from apps.reports import services as reports

        shifts.add_cash_entry(self.cashier, key(), self.shift.pk, "dau_ca", 100000)
        for _ in range(2):
            self.finish(self.submit(quantity=2))
            self.pay(method="tien_mat")
        last = Order.objects.order_by("-pk").first()
        req = self.request(self.cashier, last, AdjustmentRequest.Kind.CANCEL_PAID)
        adjustments.decide(self.owner, key(), req.pk, True)
        shifts.confirm_refund(self.cashier, key(), Refund.objects.get().pk)
        today = timezone.localdate()
        data = reports.revenue(today, today)
        self.assertEqual((data["total"], data["refunds"], data["net"]), (100000, 50000, 50000))
        for dim in reports.DIMENSIONS:
            self.assertEqual(sum(r["net"] for r in reports.revenue(today, today, dim)["rows"]), 50000, dim)

    def test_qa_rep_02_day_boundary_uses_local_time(self):
        """QA-REP-02: khoản thu lúc 23:30 giờ Việt Nam (16:30 UTC) thuộc đúng ngày đó, không sang ngày sau."""
        from apps.reports import services as reports

        self.finish(self.submit())
        self.pay()
        day = timezone.localdate() - timedelta(days=3)
        Payment.objects.update(created_at=timezone.make_aware(datetime.combine(day, time(23, 30))))
        self.assertEqual(reports.revenue(day, day)["total"], 25000)
        self.assertEqual(reports.revenue(day + timedelta(days=1), day + timedelta(days=1))["total"], 0)

    def test_qa_rep_03_excel_totals_match_screen(self):
        """QA-REP-03: tệp Excel mở được, mỗi chiều xem một trang, có số doanh thu thuần khớp màn hình."""
        from apps.reports import services as reports

        self.finish(self.submit(quantity=3))
        self.pay()
        today = timezone.localdate()
        z = zipfile.ZipFile(io.BytesIO(reports.revenue_xlsx(today, today)))
        sheets = [n for n in z.namelist() if n.startswith("xl/worksheets/sheet")]
        self.assertEqual(len(sheets), len(reports.DIMENSIONS))
        text = "".join(z.read(n).decode("utf-8") for n in z.namelist() if n.endswith(".xml"))
        self.assertIn("75000", text)
        self.assertEqual(reports.revenue(today, today)["net"], 75000)

    def test_qa_rep_04_excel_forbidden_for_staff(self):
        """QA-REP-04: nhân viên không tải được Excel doanh thu."""
        c = Client()
        c.force_login(self.cashier)
        today = timezone.localdate().isoformat()
        self.assertEqual(c.get(reverse("reports:revenue"), {"tu": today, "den": today, "xuat": "excel"}).status_code, 403)

    def test_qa_dash_01_today_revenue_traceable(self):
        """QA-DASH-01: doanh thu hôm nay trên bảng điều khiển bằng tổng tiền thu hôm nay."""
        from apps.reports import services as reports

        self.finish(self.submit(quantity=2))
        self.pay()
        self.assertEqual(reports.today_vs_last_week()["net"], 50000)


# ------------------------------------------------------------- Giai đoạn 9: lịch làm

class ScheduleTests(Base):
    def test_qa_sch_01_registration_role_and_deadline(self):
        """QA-SCH-01: nhân viên chỉ đăng ký vị trí mình đảm nhận và trước hạn."""
        from apps.schedule import services as sched
        from apps.schedule.models import WorkShift
        from apps.staff.models import Employee

        Employee.objects.create(store=self.d["store"], user=self.waiter, full_name="PV", phone="0900000001",
                                roles=["phuc_vu"])
        week = sched.next_week()
        ws = WorkShift.objects.create(store=self.d["store"], date=week, name="Ca sáng", start=time(6, 30),
                                      end=time(14, 30))
        before = sched.deadline_for(week) - timedelta(hours=1)
        with self.assertRaises(ValidationError):
            sched.register(self.waiter, {ws.pk: "pha_che"}, now=before)
        with self.assertRaises(ValidationError):
            sched.register(self.waiter, {ws.pk: "phuc_vu"}, now=sched.deadline_for(week) + timedelta(minutes=1))
        sched.register(self.waiter, {ws.pk: "phuc_vu"}, now=before)


# ------------------------------------------------------------- Giai đoạn 10: hiệu năng (số truy vấn)

class QueryCountTests(Base):
    def _count(self, user, url):
        c = Client()
        c.force_login(user)
        c.get(url)
        with CaptureQueriesContext(connection) as ctx:
            c.get(url)
        return len(ctx.captured_queries)

    def test_qa_perf_01_no_n_plus_one_on_hot_screens(self):
        """QA-PERF-01: số truy vấn của Quầy pha chế, Thu ngân, Tổng quan ca không tăng theo số đơn (1 so với 9 đơn)."""
        from apps.catalog.models import Table

        tables = [Table.objects.create(store=self.d["store"], code=f"T{i}") for i in range(8)]
        self.submit()
        screens = {"bar": (self.barista, reverse("orders:bar")), "cashier": (self.cashier, reverse("orders:cashier")),
                   "overview": (self.owner, reverse("orders:overview"))}
        one = {k: self._count(u, url) for k, (u, url) in screens.items()}
        for t in tables:
            self.submit(table=t)
        many = {k: self._count(u, url) for k, (u, url) in screens.items()}
        self.assertTrue(all(many[k] - one[k] <= 3 for k in screens), {"1 đơn": one, "9 đơn": many})


class NoShiftOrderTests(Base):
    def test_qa_sale_h_no_open_shift_no_order_from_screen(self):
        """QA-SALE-H (Hai 28/11): không có ca đang mở thì màn Tạo đơn không nhận đơn; mở ca rồi thì nhận."""
        import json

        from apps.staff import timekeeping

        Shift.objects.filter(pk=self.shift.pk).update(status=Shift.Status.CLOSED)
        timekeeping.clock_in(self.waiter, key(), Role.PHUC_VU)
        c = Client()
        c.force_login(self.waiter)
        body = {"operation_key": key(), "order": cart(self.d)}
        r = c.post(reverse("orders:submit"), json.dumps(body), content_type="application/json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("Chưa có ca đang mở", r.json()["error"])
        self.assertFalse(Order.objects.exists())
        self.assertContains(c.get(reverse("orders:create")), "chưa gửi được đơn")
        Shift.objects.filter(pk=self.shift.pk).update(status=Shift.Status.OPEN)
        r = c.post(reverse("orders:submit"), json.dumps(body), content_type="application/json")
        self.assertEqual(r.status_code, 200)
