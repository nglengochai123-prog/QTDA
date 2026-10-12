"""Nhập thực đơn thật: bán thành phẩm quy ra nguyên liệu gốc, tùy chọn có định mức riêng, chạy lại không trùng."""

from decimal import Decimal

from django.core.management import call_command
from django.test import TestCase

from apps.catalog import thuc_don_lam
from apps.catalog.models import MenuItem
from apps.inventory.models import RecipeLine


class RealMenuImportTests(TestCase):
    def lines(self, item, **kw):
        return {(l.ingredient.name): l.quantity
                for l in RecipeLine.objects.filter(version__item__name=item, **kw).select_related("ingredient")}

    def test_import_expands_bases_and_is_idempotent(self):
        call_command("nhap_thuc_don_lam", verbosity=0)
        self.assertEqual(MenuItem.objects.count(), len(thuc_don_lam.ITEMS))
        self.assertEqual(self.lines("Cà phê Sài Gòn đen"),
                         {"Cà phê bột": Decimal("30.00"), "Đường cát": Decimal("12.50")})
        foam = self.lines("Cà phê muối / trứng", option__name="Trứng")
        self.assertEqual(foam["Bột kem trứng"], Decimal("1.03"))
        self.assertNotIn("Muối", foam)
        item = MenuItem.objects.get(name="Cà phê kem")
        self.assertEqual(item.status, MenuItem.Status.DRAFT)
        self.assertIn("giá bán cỡ Chuẩn", item.sale_blockers())  # giá 0 thì chưa mở bán được
        call_command("nhap_thuc_don_lam", verbosity=0)
        self.assertEqual(MenuItem.objects.count(), len(thuc_don_lam.ITEMS))
