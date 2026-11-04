"""Rà soát hoàn thiện web 03/11: tên tùy chọn trên phiếu, chữ hiển thị không còn mã tài liệu, ô kho của pha chế."""
import re
import uuid

from django.test import TestCase
from django.urls import reverse

from apps.catalog.models import Option, OptionGroup
from apps.orders import services
from apps.orders.models import OrderLine
from apps.orders.tests.helpers import PASSWORD, build_menu, cart


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
