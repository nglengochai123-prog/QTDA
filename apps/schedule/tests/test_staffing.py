"""Mô hình hàng đợi gợi ý số người và cách đo sức làm (BRU-27, BRU-28, BRU-30)."""

import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from unittest import mock

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from apps.accounts.models import Role
from apps.catalog.models import ItemSize, MenuGroup, MenuItem
from apps.core import params
from apps.orders.models import Order, OrderLine
from apps.orders.tests.helpers import build_menu
from apps.schedule import services as sv
from apps.schedule import staffing as st
from apps.staff.models import Attendance


class QueueTests(SimpleTestCase):
    def test_erlang_c_known_values(self):
        self.assertAlmostEqual(st.erlang_c(1, 0.5), 0.5)  # M/M/1: xác suất chờ bằng hệ số sử dụng
        self.assertAlmostEqual(st.erlang_c(2, 1.0), 1 / 3)
        self.assertEqual(st.erlang_c(2, 2.0), 1.0)  # quá tải: luôn phải chờ

    def test_servers_needed_keeps_headroom(self):
        # 30 tải/giờ, mỗi người 40: chia thẳng làm tròn lên là 1 người (75% công suất) nhưng chỉ 61% việc chờ ≤ 4 phút.
        self.assertEqual(st.servers_needed(30, 40, 4 / 60, 0.7), 2)
        self.assertEqual(st.servers_needed(20, 40, 4 / 60, 0.7), 1)
        self.assertEqual(st.servers_needed(0, 40, 4 / 60, 0.7, minimum=1), 1)
        # Biến động lớn hơn (đơn nhiều ly) cần thêm người ở cùng tải.
        self.assertGreaterEqual(st.servers_needed(70, 40, 4 / 60, 0.8, scv=2.0), st.servers_needed(70, 40, 4 / 60, 0.8))

    def test_batch_scv(self):
        self.assertEqual(st.batch_scv({1: 1}), 1.0)
        self.assertAlmostEqual(st.batch_scv({1: 0.5, 3: 0.5}), 2.5)  # E[B²] = 5, E[B] = 2

    def test_cover_counts_overlap_once(self):
        shifts = [(16, 21), (17, 22)]
        need = {16: 1, 17: 1, 18: 2, 19: 1, 20: 1, 21: 1}
        self.assertEqual(st.cover_shifts(shifts, need), ([1, 1], []))
        self.assertEqual(st.peak_per_shift(shifts, need), [2, 2])  # cách cũ: 4 người cho giờ chỉ cần 2
        x, uncovered = st.cover_shifts([(6, 14)], {6: 1, 15: 1})
        self.assertEqual((x, uncovered), ([1], [15]))

    def test_cover_greedy_when_too_many_shifts(self):
        shifts = [(6, 14), (14, 22), (7, 11), (18, 22), (10, 14)]
        need = {h: 1 for h in range(6, 22)} | {7: 3, 8: 3, 19: 4, 20: 3}
        exact, _ = st.cover_shifts(shifts, need)
        with mock.patch.object(st, "SEARCH_LIMIT", 1):
            greedy, _ = st.cover_shifts(shifts, need)
        for x in (exact, greedy):
            for h, n in need.items():
                self.assertGreaterEqual(sum(xi for xi, s in zip(x, shifts) if st.covers(s, h)), n)
        hours = lambda x: sum(xi * (b - a) for xi, (a, b) in zip(x, shifts))  # noqa: E731
        self.assertLessEqual(hours(exact), hours(greedy))

    def test_saturated_rate(self):
        # Một pha chế, 10 ly gửi cùng lúc, cứ 2 phút xong một ly: sức làm 30 ly mỗi giờ.
        events = [(0.0, "gui", 1.0, 1)] * 10 + [(k / 30, "xong", 1.0, 1) for k in range(1, 11)]
        rate, busy = st.saturated_rate(events)
        self.assertAlmostEqual(rate, 30.0)
        self.assertAlmostEqual(busy, 1 / 3)
        # Dòng nhiều ly: đếm số ly đang chờ, không đếm số dòng.
        rate, _ = st.saturated_rate([(0.0, "gui", 5.0, 2, 5), (0.1, "xong", 5.0, 2, 5)])
        self.assertAlmostEqual(rate, 25.0)
        self.assertEqual(st.saturated_rate([(0.0, "gui", 1.0, 2), (0.1, "xong", 1.0, 2)]), (None, 0.0))


def at(day, hour, minute=0):
    return timezone.make_aware(datetime.combine(day, datetime.min.time()) + timedelta(hours=hour, minutes=minute))


class RateTests(TestCase):
    def setUp(self):
        self.d = build_menu()
        self.day = timezone.localdate() - timedelta(days=1)
        group = MenuGroup.objects.create(store=self.d["store"], name="Pha máy", load_factor=Decimal("1.0"))
        item = MenuItem.objects.create(store=self.d["store"], group=group, name="Cà phê đá")
        size = ItemSize.objects.create(item=item, name="M", price=20000)
        sent = at(self.day, 7)
        # 20 ly gửi lúc 7 giờ, một pha chế làm, cứ 3 phút xong một ly.
        for k in range(1, 21):
            order = Order.objects.create(store=self.d["store"], code=uuid.uuid4().hex[:12], table=self.d["table"],
                                         created_by=self.d["waiter"], operation_key=uuid.uuid4().hex, total=20000)
            Order.objects.filter(pk=order.pk).update(created_at=sent)
            done = sent + timedelta(minutes=3 * k)
            OrderLine.objects.create(order=order, position=1, item=item, size=size, item_name="Cà phê đá",
                                     size_name="M", unit_price=20000, quantity=1, done_quantity=1,
                                     status=OrderLine.Status.SERVED, done_at=done, served_at=done)
        Attendance.objects.create(store=self.d["store"], user=self.d["barista"], role=Role.PHA_CHE,
                                  clock_in=at(self.day, 6, 30), clock_out=at(self.day, 11))

    def test_bar_rate_measured_when_everyone_busy(self):
        with mock.patch.object(sv, "MIN_BUSY_HOURS", 0.5):
            rates = sv.rates(timezone.localdate())
        self.assertEqual(rates[Role.PHA_CHE]["kind"], "measured")
        self.assertAlmostEqual(rates[Role.PHA_CHE]["value"], 20.0)  # không lẫn thời gian rảnh 8–11 giờ
        # Chưa đủ 3 giờ-người bận thì không tin số đo; giờ 7 quá tải nên cũng không có giờ êm để ước lượng thận trọng.
        self.assertIsNone(sv.rates(timezone.localdate())[Role.PHA_CHE])

    def test_owner_value_wins(self):
        default = params.DEFAULTS["schedule_productivity_phuc_vu"]
        with mock.patch.dict(params.DEFAULTS, {"schedule_productivity_phuc_vu": (33,) + default[1:]}):
            rates = sv.rates(timezone.localdate())
        self.assertEqual(rates[Role.PHUC_VU], {"value": 33.0, "source": "Đặt trong file tham số", "kind": "owner"})
        self.assertIsNone(rates[Role.THU_NGAN])  # chưa ai chấm công thu ngân: Chủ quán nhập tay


class SimulationTests(SimpleTestCase):
    """Quán giả lập dùng để chọn mô hình (docs/KET_QUA_MO_PHONG.md): kiểm tra ý chính còn đúng sau khi sửa mã."""

    def test_measured_rate_close_to_true_and_median_far_below(self):
        import random

        from apps.schedule import simulation as ss

        hist = ss.history(7, random.Random(5))
        rates, old = ss.estimate_rates(hist), ss.old_productivity(hist)
        # Sức làm thật của quán giả lập khoảng 45,7 tải/giờ (phút pha theo nhóm món và hệ số tải Chủ quán khai).
        self.assertTrue(38 < rates["pha_che"] < 54, rates)
        self.assertLess(old["pha_che"], rates["pha_che"] / 2)  # trung vị cả giờ rảnh: dưới một nửa sức làm
