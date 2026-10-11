"""Đối chiếu tiêu hao nguyên liệu trọng yếu (FR-16, BRU-17, AC-32, AC-33)."""

import time
import uuid
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.control.models import ExceptionCase
from apps.inventory import operations as ops
from apps.inventory import stock
from apps.inventory.models import ConsumptionCheck, StockCount, StockMovement
from apps.orders.tests.helpers import build_menu


def key():
    return uuid.uuid4().hex


class ConsumptionTests(TestCase):
    def setUp(self):
        self.d = build_menu(milk_opening=5000)
        self.milk = self.d["milk"]
        self.milk.is_critical = True
        self.milk.save()
        owner = self.d["owner"]
        ops.submit_count(self.d["barista"], key(), self.milk.pk, "5000")  # kiểm kê 01/12: mốc
        StockCount.objects.update(created_at=timezone.now() - timedelta(days=6))
        kw = {"actor": owner, "store": self.d["store"], "source_type": "thu", "source_id": "1"}
        stock.move(self.milk.pk, 6000, kind=StockMovement.Kind.RECEIPT, **kw)
        stock.move(self.milk.pk, -200, kind=StockMovement.Kind.WASTE, **kw)
        stock.move(self.milk.pk, -8000, kind=StockMovement.Kind.CONSUME, **kw)  # gồm 300 ml hủy sau pha chế
        time.sleep(0.01)

    def count(self, closing):
        result, _ = ops.submit_count(self.d["barista"], key(), self.milk.pk, closing, "Đếm cuối kỳ")
        ops.confirm_count(self.d["owner"], result["count"], True)
        return ConsumptionCheck.objects.get()

    def test_ac32_over_tolerance_creates_exception(self):
        c = self.count("2000")
        self.assertEqual((c.actual, c.by_orders, c.excess, c.percent, c.over),
                         (Decimal(8800), Decimal(8000), Decimal(800), Decimal("10.00"), True))
        self.assertTrue(ExceptionCase.objects.filter(kind="tieu_hao_vuot", ingredient=self.milk).exists())

    def test_ac33_within_tolerance_only_reported(self):
        c = self.count("2500")
        self.assertEqual((c.actual, c.percent, c.over), (Decimal(8300), Decimal("3.75"), False))
        self.assertFalse(ExceptionCase.objects.filter(kind="tieu_hao_vuot").exists())

    def test_non_critical_ingredient_not_checked(self):
        self.milk.is_critical = False
        self.milk.save()
        result, _ = ops.submit_count(self.d["barista"], key(), self.milk.pk, "2500", "Đếm")
        ops.confirm_count(self.d["owner"], result["count"], True)
        self.assertFalse(ConsumptionCheck.objects.exists())
