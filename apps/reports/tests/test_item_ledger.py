"""Sổ phân bổ theo món: hoàn tiền trừ đúng món, đổi món chuyển sang món mới, mọi chiều cộng lại ra thu trừ hoàn."""
import tempfile
from datetime import timedelta

from django.test import override_settings

from django.utils import timezone

from apps.catalog.models import ItemSize, MenuItem
from apps.inventory.models import RecipeLine, RecipeVersion
from apps.orders import prepaid
from apps.orders.models import Order, Payment
from apps.orders.tests.test_prepaid import Base, key
from apps.reports import insights, services
from apps.shifts import services as shifts
from apps.shifts.models import Refund

from .test_accounting_forecasts import at


class ItemLedgerTests(Base):
    def setUp(self):
        super().setUp()
        item = MenuItem.objects.create(store=self.d['store'], group=self.d['item'].group, name='Bạc xỉu')
        self.bx = ItemSize.objects.create(item=item, name='M', price=30000)
        version = RecipeVersion.objects.create(item=item)
        RecipeLine.objects.create(version=version, size=self.bx, ingredient=self.d['milk'], quantity=60)
        version.publish(self.owner)
        item.status = MenuItem.Status.ON_SALE
        item.save()
        self.today = timezone.localdate()

    def by(self, dim, day=None):
        day = day or self.today
        data = services.revenue(day, day, dim)
        return {r['key']: (r['net'], r['cups']) for r in data['rows']}, data

    def assert_all_dimensions_add_up(self, day=None):
        day = day or self.today
        for dim in services.DIMENSIONS:
            data = services.revenue(day, day, dim)
            self.assertEqual(sum(r['net'] for r in data['rows']), data['net'], dim)
            self.assertEqual(sum(r['cups'] for r in data['rows']), data['cups'], dim)

    def swap(self, order, cups=1):
        line = order.lines.get(item_name='Cà phê sữa')
        return self.adjust(order, 'doi_mon', line=line.pk, cups=cups,
                           new_line={'item': self.bx.item_id, 'size': self.bx.pk, 'options': [], 'quantity': cups,
                                     'note': ''})

    def test_decrease_refund_is_taken_from_the_item(self):
        order, _, _ = self.prepay(quantity=2)
        self.adjust(order, 'huy_mon', line=order.lines.get().pk, cups=1)
        # Chưa hoàn: tiền món giữ nguyên, số ly đã giảm ngay khi duyệt.
        rows, data = self.by('mon')
        self.assertEqual(rows, {'Cà phê sữa M': (50000, 1)})
        shifts.confirm_refund(self.cashier, key(), Refund.objects.get().pk)
        rows, data = self.by('mon')
        self.assertEqual(rows, {'Cà phê sữa M': (25000, 1)})
        self.assertEqual((data['total'], data['refunds'], data['net'], data['legacy_amount']), (50000, 25000, 25000, 0))
        self.assertEqual(self.by('nhom_mon')[0], {'Pha phin': (25000, 1)})
        self.assert_all_dimensions_add_up()

    def test_swap_moves_money_and_cups_to_the_new_item(self):
        order, _, _ = self.prepay()
        self.swap(order)
        charge = order.prepaid_charges.get()
        self.assertEqual(charge.amount, 5000)
        # Khoản chờ thu chưa vào doanh thu; món mới đã nhận phần tiền đã thu của món cũ.
        self.assertEqual(self.by('mon')[0], {'Cà phê sữa M': (0, 0), 'Bạc xỉu M': (25000, 1)})
        prepaid.collect_charge(self.cashier, key(), charge.pk, 'chuyen_khoan', True)
        rows, data = self.by('mon')
        self.assertEqual(rows, {'Cà phê sữa M': (0, 0), 'Bạc xỉu M': (30000, 1)})
        methods = {r['key']: r['net'] for r in services.revenue(self.today, self.today, 'phuong_thuc')['rows']}
        self.assertEqual(methods, {'Tiền mặt': 25000, 'Chuyển khoản': 5000})
        self.assertEqual(data['cups'], 1)
        self.assert_all_dimensions_add_up()

    def test_swap_to_cheaper_item_refunds_from_the_old_item(self):
        order, _, _ = self.prepay()
        line = order.lines.get()
        self.adjust(order, 'doi_mon', line=line.pk, cups=1,
                    new_line={'item': self.bx.item_id, 'size': self.bx.pk, 'options': [], 'quantity': 1, 'note': ''})
        charge = order.prepaid_charges.get()
        prepaid.collect_charge(self.cashier, key(), charge.pk, 'tien_mat', False, 5000)
        # Đổi tiếp sang món rẻ hơn bằng cách hủy 1 ly Bạc xỉu và thêm lại Cà phê sữa qua đổi món.
        new = order.lines.get(item_name='Bạc xỉu')
        self.adjust(order, 'doi_mon', line=new.pk, cups=1,
                    new_line={'item': self.d['item'].pk, 'size': self.d['size_m'].pk, 'options': [], 'quantity': 1,
                              'note': ''})
        refund = Refund.objects.get(kind=Refund.Kind.PREPAID_DECREASE)
        self.assertEqual(refund.amount, 5000)
        shifts.confirm_refund(self.cashier, key(), refund.pk)
        rows, data = self.by('mon')
        self.assertEqual(rows['Cà phê sữa M'], (25000, 1))
        self.assertEqual(rows['Bạc xỉu M'], (0, 0))
        self.assertEqual(data['net'], 25000)
        self.assert_all_dimensions_add_up()

    def test_swap_on_a_later_day_keeps_the_old_day_and_moves_item_on_the_new_day(self):
        order, _, _ = self.prepay()
        yesterday = self.today - timedelta(days=1)
        Payment.objects.filter(pk=order.payment_id).update(created_at=at(yesterday))
        before = {dim: services.revenue(yesterday, yesterday, dim)['rows'] for dim in services.DIMENSIONS}
        self.swap(order)
        prepaid.collect_charge(self.cashier, key(), order.prepaid_charges.get().pk, 'chuyen_khoan', True)
        for dim in services.DIMENSIONS:
            self.assertEqual(services.revenue(yesterday, yesterday, dim)['rows'], before[dim], dim)
        rows, data = self.by('mon')
        self.assertEqual(rows, {'Cà phê sữa M': (-25000, -1), 'Bạc xỉu M': (30000, 1)})
        self.assertEqual(data['net'], 5000)
        # Gộp hai ngày: chỉ còn món thật sự bán.
        month = services.revenue(yesterday, self.today, 'mon')
        self.assertEqual({r['key']: (r['net'], r['cups']) for r in month['rows']},
                         {'Cà phê sữa M': (0, 0), 'Bạc xỉu M': (30000, 1)})

    def test_cancel_paid_invoice_refund_is_taken_from_its_items(self):
        from apps.orders.tests.helpers import cart
        from apps.orders import payments, services as order_services
        result, _ = order_services.submit_order(self.d['waiter'], key(), cart(self.d, quantity=2))
        order = Order.objects.get(pk=result['order_id'])
        line = order.lines.get()
        self.done(self.d['barista'], line, 2)
        order_services.serve_line(self.d['waiter'], key(), line.pk)
        payments.pay_table(self.cashier, key(), order.table_id, 'tien_mat')
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.PAID)
        self.adjust(order, 'huy_hoa_don')
        shifts.confirm_refund(self.cashier, key(), Refund.objects.get().pk)
        rows, data = self.by('mon')
        self.assertEqual(rows, {'Cà phê sữa M': (0, 2)})
        self.assertEqual((data['total'], data['refunds'], data['legacy_amount']), (50000, 50000, 0))
        self.assert_all_dimensions_add_up()

    @override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix="lam-test-media-"))
    def test_margin_is_shown_for_prepaid_periods(self):
        from apps.inventory import operations as ops
        from apps.inventory.models import Supplier
        from .test_insights import photo
        supplier = Supplier.objects.create(store=self.d['store'], name='NCC mẫu')
        ops.create_receipt(self.owner, key(), supplier.pk, [
            {'ingredient': self.d['coffee'].pk, 'quantity': '1000', 'unit_price': 300},
            {'ingredient': self.d['milk'].pk, 'quantity': '380', 'unit_price': 60}], 'tra_ngay', invoice_photo=photo())
        order, _, _ = self.prepay(quantity=2)
        self.done(self.cashier, order.lines.get(), 2)
        analysis = insights.sales(self.today, self.today)
        # 2 ly × (20 g × 300 đ + 30 ml × 60 đ) = 15.600 đ giá vốn trên 50.000 đ thu trước
        self.assertEqual(round(analysis['cost']), 15600)
        labels = [k['label'] for k in analysis['kpis']]
        self.assertIn('Lãi gộp ước tính', labels)
        self.assertTrue(analysis['has_cost'])
        self.assertFalse(any('chưa lưu phân bổ' in n for n in analysis['notes']))
