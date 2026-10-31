"""Amounts come from money movements. Item attribution is captured once in the append-only audit journal.

Locked postpaid receipts may be reconciled to their lines. Prepaid receipts without a captured allocation remain unallocated.
"""
from django.utils import timezone
from apps.audit.models import Action, AuditLog
from apps.audit.services import record
from apps.orders.models import Payment

ALLOCATION_TYPE = 'orders.PaymentAllocation'
UNALLOCATED = 'Chưa có phân bổ lịch sử'


def _allocation(payment, orders, *, extra=False):
    """Largest remainder preserves every dong."""
    lines = []
    for order in orders:
        for line in sorted(order.lines.all(), key=lambda line: line.pk):
            qty = line.billable_quantity
            if qty <= 0:
                continue
            lines.append({'order_ids': [order.pk], 'line_id': line.pk, 'size_id': line.size_id,
                          'item': f'{line.item_name} {line.size_name}', 'group_id': line.item.group_id,
                          'group': line.item.group.name, 'employee_id': order.created_by_id,
                          'employee': str(order.created_by), 'ordered_at': order.created_at.isoformat(),
                          'cups': 0 if extra else qty, 'weight': line.unit_price * qty})
    weight = sum(x['weight'] for x in lines)
    if weight:
        for x in lines:
            x['amount'], x['remainder'] = divmod(payment.amount * x['weight'], weight)
        left = payment.amount - sum(x['amount'] for x in lines)
        for x in sorted(lines, key=lambda x: (-x['remainder'], x['line_id']))[:left]:
            x['amount'] += 1
    elif lines:
        for x in lines:
            x['amount'] = 0
        lines[0]['amount'] = payment.amount
    for x in lines:
        x.pop('weight', None)
        x.pop('remainder', None)
    return lines


def capture(payment, orders, *, extra=False):
    """Capture in the same transaction as collection."""
    lines = _allocation(payment, orders, extra=extra)
    record(Action.CREATE, actor=payment.cashier, obj=payment, object_type=ALLOCATION_TYPE,
           after={'version': 1, 'amount': payment.amount, 'lines': lines},
           reason='Phân bổ khoản thu theo giá trị món tại lúc thu; thu thêm không đếm thêm ly')


def entries(start, end):
    payments = list(Payment.objects.filter(created_at__gte=start, created_at__lt=end)
                    .select_related('shift').prefetch_related('orders__created_by', 'orders__lines__item__group', 'prepaid_charge__order'))
    ids = [str(p.pk) for p in payments]
    snapshots = {}
    for log in AuditLog.objects.filter(object_type=ALLOCATION_TYPE, object_id__in=ids, action=Action.CREATE).order_by('id'):
        snapshots.setdefault(log.object_id, log.after or {})
    result = []
    for p in payments:
        snap = snapshots.get(str(p.pk), {})
        allocation = snap.get('lines') or []
        # Postpaid orders cannot change item/price/quantity after collection. Recover only when
        # their locked lines reconcile exactly; never use this path for prepaid or extra receipts.
        if not allocation and p.kind in (Payment.Kind.NORMAL, Payment.Kind.RECEIVED_ITEMS):
            orders = list(p.orders.all())
            locked = orders and all(o.status in ('da_thanh_toan', 'da_huy') for o in orders)
            if locked:
                candidate = _allocation(p, orders)
                billable = sum(line.unit_price * line.billable_quantity for o in orders for line in o.lines.all())
                if billable == p.amount:
                    allocation = candidate
        unallocated = not allocation or sum(x.get('amount', 0) for x in allocation) != p.amount
        if sum(x.get('amount', 0) for x in allocation) != p.amount or not allocation:
            orders = list(p.orders.all())
            if not orders:
                charge = getattr(p, 'prepaid_charge', None)
                orders = [charge.order] if charge else []
            allocation = [{'amount': p.amount, 'cups': 0, 'order_ids': [o.pk for o in orders],
                           'line_id': None, 'size_id': None, 'item': UNALLOCATED, 'group_id': None,
                           'group': UNALLOCATED, 'employee_id': None, 'employee': UNALLOCATED,
                           'ordered_at': None}]
        result.extend({**x, 'payment': p, 'legacy': unallocated, 'recovered_allocation': not bool(snap.get('lines')) and not unallocated} for x in allocation)
    return result


def key(entry, dim):
    p = entry['payment']
    at = timezone.localtime(p.created_at)
    return {'ngay': at.strftime('%d/%m/%Y'), 'khung_gio': f'{at:%H}–{at.hour + 1:02d} giờ',
            'ca': str(p.shift) if p.shift else 'Không gắn ca', 'phuong_thuc': p.get_method_display(),
            'mon': entry['item'], 'nhom_mon': entry['group'], 'nhan_vien': entry['employee']}[dim]


def row_filter(entry, dim):
    p = entry['payment']
    at = timezone.localtime(p.created_at)
    return {'ngay': ('ngay', at.date().isoformat()), 'khung_gio': ('gio', str(at.hour)),
            'ca': ('ca', str(p.shift_id or 'none')), 'phuong_thuc': ('phuong_thuc', p.method),
            'mon': ('mon', str(entry['size_id'] or 'none')), 'nhom_mon': ('nhom', str(entry['group_id'] or 'none')),
            'nhan_vien': ('nhan_vien', str(entry['employee_id'] or 'none'))}[dim]


def matches(entry, params):
    for dim in ('khung_gio', 'ca', 'phuong_thuc', 'mon', 'nhom_mon', 'nhan_vien'):
        name, value = row_filter(entry, dim)
        if params.get(name) and params[name] != value:
            return False
    return True
