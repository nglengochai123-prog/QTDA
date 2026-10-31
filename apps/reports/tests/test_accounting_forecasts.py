"""Regression scenarios for receipt accounting, period attribution and forecast governance."""
from datetime import datetime, time, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase
from django.urls import reverse
from django.utils import timezone

from apps.orders.tests.test_prepaid import Base, key
from apps.orders import prepaid
from apps.orders.models import Payment, PrepaidCharge, Order
from apps.shifts.models import Refund, Shift, Discrepancy
from apps.shifts import services as shifts
from apps.reports import services, insights
from apps.control import services as control
from apps.control.models import LossCase
from apps.forecast import methods, planning
from apps.forecast.models import IngredientPlan
from apps.inventory import stock
from apps.inventory.models import StockMovement


def at(day, hour=12):
    return timezone.make_aware(datetime.combine(day, time(hour)))


class MoneyRegressionTests(Base):
    def increase(self, order):
        line = order.lines.get()
        self.adjust(order, 'doi_mon', line=line.pk, cups=1,
                    new_line={'item': self.d['item'].pk, 'size': self.d['size_m'].pk,
                              'options': [self.d['cream'].pk], 'quantity': 1, 'note': ''})
        return PrepaidCharge.objects.get(order=order)

    def test_pending_extra_is_not_revenue_and_collection_is_split_by_method(self):
        order, _, _ = self.prepay()
        charge = self.increase(order)
        today = timezone.localdate()
        self.assertEqual(services.revenue(today,today)['total'],25000)
        op = key()
        prepaid.collect_charge(self.cashier,op,charge.pk,'chuyen_khoan',True)
        prepaid.collect_charge(self.cashier,op,charge.pk,'chuyen_khoan',True)
        rows = services.revenue(today,today,'phuong_thuc')['rows']
        self.assertEqual({r['key']:r['revenue'] for r in rows},{'Tiền mặt':25000,'Chuyển khoản':8000})
        analysis=insights.sales(today,today)
        self.assertEqual(analysis['revenue'],33000)
        self.assertFalse(analysis['has_cost'])
        self.assertTrue(any('khoản thu trước' in n for n in analysis['notes']))
        self.assertEqual(sum(r['cups'] for r in rows),1)
        self.client.force_login(self.owner)
        transfer = next(r for r in rows if r['key']=='Chuyển khoản')
        page = self.client.get(reverse('orders:lookup')+'?'+transfer['link'])
        self.assertEqual(page.context['receipt_total'],8000)
        self.assertEqual(page.context['page'].paginator.count,1)
        self.assertContains(page,'8.000')

    def test_carry_over_does_not_change_receipt_shift(self):
        order, _, _ = self.prepay()
        later = Shift.objects.create(store=self.d['store'],name='Ca sau',starts_at=self.shift.ends_at,
                                     ends_at=self.shift.ends_at+timedelta(hours=4),approver=self.owner)
        shifts.carry_over(self.owner,order.pk,later.pk,'Khách còn chờ')
        today = timezone.localdate()
        data = services.revenue(today,today,'ca')
        self.assertEqual([(r['key'],r['revenue']) for r in data['rows']],[(str(self.shift),25000)])
        self.client.force_login(self.owner)
        page=self.client.get(reverse('orders:lookup')+'?'+data['rows'][0]['link'])
        self.assertEqual(page.context['receipt_total'],25000)

    def test_later_adjustment_and_extra_do_not_rewrite_previous_day_in_any_dimension(self):
        order, _, _ = self.prepay()
        today=timezone.localdate(); yesterday=today-timedelta(days=1)
        Payment.objects.filter(pk=order.payment_id).update(created_at=at(yesterday))
        before={dim:services.revenue(yesterday,yesterday,dim)['rows'] for dim in services.DIMENSIONS}
        charge=self.increase(order)
        prepaid.collect_charge(self.cashier,key(),charge.pk,'chuyen_khoan',True)
        for dim in services.DIMENSIONS:
            self.assertEqual(services.revenue(yesterday,yesterday,dim)['rows'],before[dim],dim)
            self.assertEqual(services.revenue(today,today,dim)['total'],8000,dim)
        self.assertEqual(services.revenue(today,today)['previous'],25000)

    def test_decrease_is_reported_only_when_paid_and_refund_only_day_is_visible(self):
        order, _, _=self.prepay(quantity=2)
        self.adjust(order,'huy_mon',line=order.lines.get().pk,cups=1)
        today=timezone.localdate()
        self.assertEqual((services.revenue(today,today)['total'],services.revenue(today,today)['refunds']),(50000,0))
        refund=Refund.objects.get()
        shifts.confirm_refund(self.cashier,key(),refund.pk)
        data=services.revenue(today,today,'phuong_thuc')
        self.assertEqual((data['total'],data['refunds'],data['net']),(50000,25000,25000))
        self.assertEqual(data['rows'][0]['net'],25000)
        Payment.objects.filter(pk=order.payment_id).update(created_at=at(today-timedelta(days=1)))
        data=services.revenue(today,today)
        self.assertEqual((data['total'],data['refunds'],data['net']),(0,25000,-25000))
        self.client.force_login(self.owner)
        page=self.client.get(reverse('reports:revenue'),{'tu':str(today),'den':str(today)})
        self.assertEqual(page.status_code,200)
        self.assertContains(page,'Hoàn tiền đã trả trong kỳ')

    def test_legacy_receipt_preserves_money_without_inventing_item_history(self):
        Payment.objects.create(store=self.d['store'],table=self.d['table'],cashier=self.owner,shift=self.shift,
                               method='tien_mat',amount=731,operation_key=key())
        today=timezone.localdate()
        for dim in services.DIMENSIONS:
            data=services.revenue(today,today,dim)
            self.assertEqual(data['total'],731)
            self.assertEqual(data['legacy_amount'],731)
        self.assertEqual(services.revenue(today,today,'mon')['rows'][0]['key'],'Chưa có phân bổ lịch sử')

    def test_legacy_locked_postpaid_lines_remain_available_without_writing_audit(self):
        from apps.orders import services as order_services
        from apps.orders.tests.helpers import cart
        from apps.audit.models import AuditLog
        result, _ = order_services.submit_order(self.d['waiter'], key(), cart(self.d))
        order=Order.objects.get(pk=result['order_id'])
        payment=Payment.objects.create(store=self.d['store'],table=order.table,cashier=self.owner,shift=self.shift,
                                       method='tien_mat',amount=25000,operation_key=key())
        Order.objects.filter(pk=order.pk).update(payment=payment,status=Order.Status.PAID)
        before=AuditLog.objects.count()
        today=timezone.localdate()
        data=services.revenue(today,today,'mon')
        self.assertEqual((data['total'],data['legacy_amount'],data['cups']),(25000,0,1))
        self.assertNotEqual(data['rows'][0]['key'],'Chưa có phân bổ lịch sử')
        self.assertEqual(AuditLog.objects.count(),before)


class LossAndForecastReportTests(Base):
    def discrepancy(self, day, amount):
        shift=Shift.objects.create(store=self.d['store'],name='Ca đối soát',starts_at=at(day),
                                   ends_at=at(day)+timedelta(hours=4),approver=self.owner)
        return Discrepancy.objects.create(store=self.d['store'],shift=shift,method='tien_mat',expected=amount,
                                          actual=0,difference=-amount,manager=self.owner)

    def test_late_verification_keeps_loss_in_original_month(self):
        today=timezone.localdate(); previous=today.replace(day=1)-timedelta(days=1)
        d=self.discrepancy(previous,100000)
        case=control.open_case(self.owner,'Lập muộn',operation_key=key())
        control.add_evidence(self.owner,case,discrepancy=d)
        self.assertEqual(control.monthly_control(previous.year,previous.month)['control_value'],100000)
        control.verify(self.owner,case,100000)
        old=control.monthly_control(previous.year,previous.month)
        self.assertEqual((old['control_value'],old['verified'],old['in_process']),(100000,100000,0))
        self.assertEqual(control.monthly_control(today.year,today.month)['control_value'],0)
        control.recover(self.owner,case,30000,operation_key=key())
        self.assertEqual(control.monthly_control(previous.year,previous.month)['verified_remaining'],70000)
        with self.assertRaises(ValidationError):
            control.add_evidence(self.owner,case,discrepancy=self.discrepancy(today,5))

    def test_multi_month_case_preserves_total_and_integer_recovery(self):
        today=timezone.localdate(); previous=today.replace(day=1)-timedelta(days=1)
        case=control.open_case(self.owner,'Nhiều kỳ',operation_key=key())
        control.add_evidence(self.owner,case,discrepancy=self.discrepancy(previous,100000))
        control.add_evidence(self.owner,case,discrepancy=self.discrepancy(today,50000))
        control.verify(self.owner,case,150001)
        control.recover(self.owner,case,10001,operation_key=key())
        reports=[control.monthly_control(d.year,d.month) for d in (previous,today)]
        self.assertEqual(sum(r['verified'] for r in reports),150001)
        self.assertEqual(sum(r['recovered'] for r in reports),10001)
        self.assertEqual(sum(r['in_process'] for r in reports),0)

    def plan(self, day, calculated, daily, current=False, factor=1):
        return IngredientPlan.objects.create(ingredient=self.d['coffee'],calc_date=day,calculated_at=calculated,
                data_hash=key(),is_current=current,forecast={'method':'LN','daily':daily,'factor':factor},
                action=IngredientPlan.Action.NONE)

    def test_historical_forecast_never_uses_later_revision_and_reports_missing_days(self):
        day=timezone.localdate()-timedelta(days=3)
        self.plan(day-timedelta(days=1),at(day-timedelta(days=1)),{str(day):20})
        self.plan(day+timedelta(days=1),at(day+timedelta(days=1)),{str(day):999},True)
        with patch('django.utils.timezone.now', return_value=at(day)):
            stock.move(self.d['coffee'].pk,-30,kind=StockMovement.Kind.CONSUME,actor=self.owner,
                       store=self.d['store'],source_type='regression')
        row=next(r for r in services.materials(day,day+timedelta(days=1))['rows'] if r['ingredient']==self.d['coffee'])
        c=row['comparison']
        self.assertEqual((c['predicted'],c['actual'],c['difference'],c['covered'],c['days']),(20,30,10,1,2))
        self.assertFalse(c['complete'])

    def test_current_material_forecast_uses_purchase_planning_adjustments(self):
        day=timezone.localdate()
        p=self.plan(day,timezone.now(),{str(day+timedelta(days=j)):10 for j in range(7)},True,2)
        row=next(r for r in services.materials(day,day)['rows'] if r['ingredient']==self.d['coffee'])
        self.assertEqual(row['estimate']['mean'],140)
        self.assertEqual(row['estimate']['plan_id'],p.pk)
        self.assertEqual(row['comparison']['covered'],0)

    def test_purchase_cannot_accept_forecast_awaiting_approval(self):
        day=timezone.localdate();p=self.plan(day,timezone.now(),{str(day):10},True)
        p.forecast['requires_approval']=True
        with self.assertRaises(ValidationError):
            planning.accept(self.owner,p,10,'',day,key())


class ForecastApprovalTests(SimpleTestCase):
    def test_unavailable_approved_method_is_not_silently_replaced(self):
        from datetime import date
        today=date(2026,10,20)
        series=[(today-timedelta(days=10-i),10.0,'ok') for i in range(10)]
        result=methods.forecast_series(series,today=today,horizon=7,approved='HW',candidates=('LN','WMA'))
        self.assertTrue(result['requires_approval'])
        self.assertIsNone(result['method'])
        self.assertEqual(result['daily'],{})
        self.assertFalse(result['auto_pick'])
        self.assertEqual(result['proposal']['from'],'HW')
        self.assertTrue(result['proposal']['urgent'])
        planning._hold_proposal(result,None,today,28)
        self.assertIsNotNone(result['proposal'])

    def test_hierarchy_does_not_use_total_forecast_pending_approval(self):
        from datetime import date
        from apps.forecast import hierarchy
        today=date(2026,10,20)
        pending={'method':'LN','requires_approval':True,'daily':{str(today):10}}
        with patch.object(methods,'forecast_series',return_value=pending), patch.object(methods,'rolling') as rolling:
            result=hierarchy.build([(today-timedelta(days=1),10,'ok')],[],today=today,horizon=7)
        rolling.assert_not_called()
        self.assertEqual(result['today'],{})
