from datetime import date
from django.urls import reverse
from django.utils import timezone
from apps.orders.tests.test_adjust_pay import Base
from apps.inventory import stock
from apps.inventory.models import StockMovement
from apps.inventory.views_ledger import filter_movements
from apps.reports import services
from apps.control.models import ExceptionCase, ExceptionReview

class ReviewRegressionTests(Base):
    def test_material_links_include_production_and_exclude_opposite_sign(self):
        ing=self.d['coffee']
        for kind, qty in [(StockMovement.Kind.RECEIPT,100),(StockMovement.Kind.PRODUCE,80),(StockMovement.Kind.PRODUCE,-30),(StockMovement.Kind.CONSUME,-20),(StockMovement.Kind.WASTE,-5)]:
            stock.move(ing.pk,qty,kind=kind,actor=self.d['owner'],store=self.d['store'],source_type='review_test')
        today=timezone.localdate()
        row=next(r for r in services.materials(today,today)['rows'] if r['ingredient']==ing)
        f={'nvl':str(ing.pk),'tu':str(today),'den':str(today)}
        self.assertEqual(sum(m.quantity for m in filter_movements({**f,'loai':'nhap_va_lam'})),row['receipts'])
        self.assertEqual(-sum(m.quantity for m in filter_movements({**f,'loai':'tieu_hao_va_lam'})),row['consumed'])
        self.client.force_login(self.d['owner'])
        self.assertContains(self.client.get(reverse('inventory:ledger'),{**f,'loai':'nhap_va_lam'}),'value="nhap_va_lam" selected')

    def test_exception_drilldown_uses_current_review_and_unreviewed(self):
        cases=[]
        for result in ['vi_pham','hop_le',None]:
            e=ExceptionCase.objects.create(store=self.d['store'],kind=ExceptionCase.Kind.PAID_CANCELLED,rule='test')
            cases.append(e)
            if result:
                ExceptionReview.objects.create(exception=e,result=result,reviewer=self.d['owner'])
        old=ExceptionReview.objects.create(exception=cases[1],result='vi_pham',reviewer=self.d['owner'])
        current=cases[1].reviews.get(result='hop_le')
        ExceptionReview.objects.filter(pk=old.pk).update(superseded_by=current)
        self.client.force_login(self.d['owner'])
        for result,e in zip(['vi_pham','hop_le','chua_xem'],cases):
            page=self.client.get(reverse('control:exceptions'),{'trang-thai':'tat-ca','ket_qua':result})
            self.assertEqual([x.pk for x in page.context['items']],[e.pk])
        today=timezone.localdate()
        data=services.revenue_control(today,today)
        self.assertEqual({r['result_value'] for r in data['exceptions']},{'vi_pham','hop_le','chua_xem'})
        page=self.client.get(reverse('reports:revenue_control'),{'tu':str(today),'den':str(today)})
        self.assertContains(page,'ket_qua=vi_pham')

    def test_control_reports_each_calendar_month_across_year_boundary(self):
        data=services.revenue_control(date(2025,12,28),date(2026,2,3))
        self.assertEqual([r['month'] for r in data['months']],[date(2025,12,1),date(2026,1,1),date(2026,2,1)])
        self.client.force_login(self.d['owner'])
        page=self.client.get(reverse('reports:revenue_control'),{'tu':'2025-12-28','den':'2026-02-03'})
        for label in ['12/2025','01/2026','02/2026']:
            self.assertContains(page,'Giá trị kiểm soát tạm tính tháng '+label)
