"""Dự báo nhân sự theo từng vị trí: mỗi vị trí tính theo loại việc của mình, tỷ lệ theo giờ của đúng thứ."""
from datetime import date, time, timedelta
from unittest import mock

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from apps.accounts.models import Role
from apps.orders import payments, services as order_services
from apps.orders.tests.test_prepaid import Base, key
from apps.orders.tests.helpers import cart
from apps.schedule import demand
from apps.schedule import services as sv
from apps.schedule.models import WorkShift


class ProfileTests(SimpleTestCase):
    def test_weekday_profile_and_fallback(self):
        monday = date(2026, 10, 5)
        cups, work = {}, {r: {} for r in demand.UNITS}
        # 3 thứ Hai: sáng đông pha chế, quầy thu ngân đông giờ trưa; thứ Ba chỉ 1 ngày dữ liệu.
        for k in range(3):
            d = monday + timedelta(days=7 * k)
            cups[(d, 7)], cups[(d, 12)] = 30, 10
            work[Role.PHA_CHE][(d, 7)], work[Role.PHA_CHE][(d, 12)] = 30, 10
            work[Role.THU_NGAN][(d, 7)], work[Role.THU_NGAN][(d, 12)] = 5, 15
            work[Role.PHUC_VU][(d, 7)] = 8
        tuesday = monday + timedelta(days=1)
        cups[(tuesday, 9)] = 20
        work[Role.PHA_CHE][(tuesday, 9)] = 20
        p = demand.profile(work, cups)
        self.assertAlmostEqual(p[Role.PHA_CHE]["shares"][0][7], 0.75)
        self.assertAlmostEqual(p[Role.THU_NGAN]["shares"][0][12], 0.75)
        self.assertAlmostEqual(p[Role.THU_NGAN]["per_cup"][0], 0.5)
        self.assertEqual(p[Role.PHA_CHE]["basis"][0], "3 ngày cùng thứ")
        # Thứ Ba chưa đủ 3 ngày: gộp ngày thường.
        self.assertEqual(p[Role.PHA_CHE]["basis"][1], "4 ngày ngày thường")
        load = demand.hourly_work(p[Role.THU_NGAN], monday + timedelta(days=21), 100)
        self.assertAlmostEqual(load[12], 37.5)
        self.assertAlmostEqual(load[7], 12.5)


class SuggestByRoleTests(TestCase):
    def setUp(self):
        from apps.core.models import Store
        store = Store.get_default()
        self.day = date(2026, 11, 9)  # thứ Hai
        self.morning = WorkShift.objects.create(store=store, date=self.day, name="Ca sáng", start=time(6), end=time(12))
        self.noon = WorkShift.objects.create(store=store, date=self.day, name="Ca trưa", start=time(11), end=time(16))

    def test_each_role_uses_its_own_work_and_hours(self):
        def driver(shares, per_cup, unit):
            return {"shares": {0: shares}, "per_cup": {0: per_cup}, "basis": {0: "8 ngày cùng thứ"},
                    "label": unit, "unit": unit}
        inputs = {"today": self.day - timedelta(days=3), "scv": 1.0, "profile": ({False: {7: 1.0}, True: {}}, 1.0),
                  "rates": {r: {"value": 20.0, "source": "Chủ quán đặt", "kind": "owner"} for r in sv.ROLES},
                  "drivers": {Role.PHA_CHE: driver({7: 0.8, 12: 0.2}, 1.0, "tải"),
                              Role.PHUC_VU: driver({7: 0.5, 12: 0.5}, 0.4, "lượt"),
                              Role.THU_NGAN: driver({7: 0.2, 12: 0.8}, 0.5, "giao dịch")}}
        with mock.patch("apps.schedule.services._daily_cups", return_value=(100.0, "Dự báo")), \
                mock.patch("apps.schedule.services._daily_sigma", return_value=0.0):
            out = sv.suggest_day(self.day, [self.morning, self.noon], inputs)
        bar_morning = out[self.morning.pk][Role.PHA_CHE]
        cash_noon = out[self.noon.pk][Role.THU_NGAN]
        # Pha chế đông lúc 7 giờ (80 tải), thu ngân đông lúc 12 giờ (40 giao dịch): ca sáng cần thêm pha chế,
        # ca trưa cần thêm thu ngân, không chia đều như khi dùng chung số ly.
        self.assertIn([7, 80.0, bar_morning[1]["hours"][1][2]], bar_morning[1]["hours"])
        self.assertGreater(bar_morning[0], out[self.noon.pk][Role.PHA_CHE][0])
        self.assertGreaterEqual(cash_noon[0], out[self.morning.pk][Role.THU_NGAN][0])
        self.assertEqual(cash_noon[1]["unit"], "giao dịch")
        self.assertIn([12, 40.0, cash_noon[1]["hours"][1][2]], cash_noon[1]["hours"])

    def test_buffer_for_busier_day_than_forecast(self):
        inputs = {"today": self.day - timedelta(days=3), "scv": 1.0, "profile": ({False: {7: 1.0}, True: {}}, 1.0),
                  "rates": {r: {"value": 20.0, "source": "Chủ quán đặt", "kind": "owner"} for r in sv.ROLES}}
        with mock.patch("apps.schedule.services._daily_cups", return_value=(100.0, "Dự báo")), \
                mock.patch("apps.schedule.services._daily_sigma", return_value=20.0):
            basis = sv.suggest_day(self.day, [self.morning], inputs)[self.morning.pk][Role.PHA_CHE][1]
        # Phân vị 75: 100 + 0,674 × 20 ≈ 113,5 ly.
        self.assertAlmostEqual(basis["cups"], 113.5, places=1)
        self.assertEqual((basis["cups_mean"], basis["demand_percent"]), (100.0, 75))


class HistoryTests(Base):
    def test_history_counts_role_work(self):
        result, _ = order_services.submit_order(self.d["waiter"], key(), cart(self.d, quantity=2))
        self.prepay()  # thu ngân nhận đơn tại quầy và thu trước
        tomorrow = timezone.localdate() + timedelta(days=1)
        work, cups = demand.history(tomorrow, 7)
        total = lambda r: sum(work[r].values())
        self.assertEqual(sum(cups.values()), 3)
        self.assertEqual(total(Role.PHUC_VU), 1)  # một đơn nhận tại bàn, chưa mang món
        self.assertEqual(total(Role.THU_NGAN), 2)  # đơn tại quầy + khoản thu trước
        self.assertTrue(result)
