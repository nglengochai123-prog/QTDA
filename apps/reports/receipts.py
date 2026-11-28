"""Sổ phân bổ doanh thu theo dòng món, ghi bất biến trong nhật ký thao tác (không xóa, không sửa).

Tiền theo từng lần thu và từng lần hoàn thực tế. Món, nhóm món, nhân viên theo phân bổ ghi lại tại lúc phát sinh:

- Thu tiền (thu sau, thu trước, thu thêm): `orders.PaymentAllocation` gắn với khoản thu.
- Điều chỉnh đơn thu trước (đổi món, hủy ly, thêm ly): phần chênh từng dòng giữa giá trị món hiện tại và phần đã
  phân bổ được tách làm hai phần:
    * phần đổi qua lại giữa các dòng, tổng bằng 0 (`orders.LineReallocation`, ghi ngay lúc duyệt; kèm số ly thay đổi);
    * phần chênh tiền, gắn với khoản chờ thu thêm (`orders.ChargeAllocation`) hoặc khoản chờ hoàn
      (`shifts.RefundAllocation`). Phần này chỉ vào báo cáo khi tiền thực thu hoặc thực hoàn.
- Hủy hóa đơn đã thanh toán: khoản hoàn mang phân bổ âm đúng bằng phần đã phân bổ cho đơn.

Cộng mọi dòng của một chiều xem (món, nhóm, nhân viên, ngày, ca, phương thức) luôn ra đúng tiền thu trừ hoàn.
Dữ liệu cũ thiếu phân bổ thì giữ nguyên tiền và ghi "Chưa có phân bổ lịch sử", không đoán.
"""
from collections import OrderedDict

from django.utils import timezone

from apps.audit.models import Action, AuditLog
from apps.audit.services import record
from apps.orders.models import Payment

ALLOCATION_TYPE = 'orders.PaymentAllocation'
CHARGE_TYPE = 'orders.ChargeAllocation'
REFUND_TYPE = 'shifts.RefundAllocation'
REALLOCATION_TYPE = 'orders.LineReallocation'
UNALLOCATED = 'Chưa có phân bổ lịch sử'

THU, HOAN, DOI = 'thu', 'hoan', 'doi'


# ---------------- ghi phân bổ ----------------

def _info(line, order):
    return {'order_ids': [order.pk], 'line_id': line.pk, 'size_id': line.size_id,
            'item': f'{line.item_name} {line.size_name}', 'group_id': line.item.group_id,
            'group': line.item.group.name, 'employee_id': order.created_by_id,
            'employee': str(order.created_by), 'ordered_at': order.created_at.isoformat()}


def _split(amount, weights):
    """Chia `amount` theo trọng số nguyên, phần dư chia theo phần lẻ lớn nhất: không mất đồng nào."""
    total = sum(weights.values())
    if not weights:
        return {}
    if total <= 0:
        first = min(weights)
        return {k: (amount if k == first else 0) for k in weights}
    parts, rest = {}, {}
    for k, w in weights.items():
        parts[k], rest[k] = divmod(amount * w, total)
    left = amount - sum(parts.values())
    for k in sorted(weights, key=lambda k: (-rest[k], k))[:left]:
        parts[k] += 1
    return parts


def _allocation(payment, orders):
    """Phân bổ một khoản thu theo giá trị món tính tiền tại lúc thu (thu sau, thu trước)."""
    infos, weights, cups = {}, {}, {}
    for order in orders:
        for line in sorted(order.lines.all(), key=lambda line: line.pk):
            qty = line.billable_quantity
            if qty <= 0:
                continue
            infos[line.pk] = _info(line, order)
            weights[line.pk], cups[line.pk] = line.unit_price * qty, qty
    if not infos:
        return []
    parts = _split(payment.amount, weights)
    return [{**infos[k], 'amount': parts[k], 'cups': cups[k]} for k in sorted(infos)]


def _log(object_type, obj, actor, lines, reason, **extra):
    record(Action.CREATE, actor=actor, obj=obj, object_type=object_type,
           after={'version': 1, 'amount': sum(x['amount'] for x in lines), 'lines': lines, **extra}, reason=reason)


def capture(payment, orders, *, extra=False, charge=None):
    """Ghi phân bổ của khoản thu trong cùng giao dịch với lần thu.

    Thu thêm: dùng đúng phần chênh đã ghi lúc duyệt điều chỉnh (dòng nào tăng thì dòng đó nhận tiền), không chia lại
    cho cả đơn. Thiếu phần chênh đã ghi (dữ liệu cũ) thì để chưa phân bổ."""
    if extra:
        plan = _plan(CHARGE_TYPE, charge.pk) if charge is not None else None
        if plan is None or sum(x['amount'] for x in plan) != payment.amount:
            return
        lines = [{**x, 'cups': 0} for x in plan]
    else:
        lines = _allocation(payment, orders)
    _log(ALLOCATION_TYPE, payment, payment.cashier, lines,
         'Phân bổ khoản thu theo dòng món tại lúc thu')


def _plan(object_type, pk):
    log = (AuditLog.objects.filter(object_type=object_type, object_id=str(pk), action=Action.CREATE)
           .order_by('id').first())
    return (log.after or {}).get('lines') if log else None


def _snapshot(payment_id):
    return _plan(ALLOCATION_TYPE, payment_id)


def attributed(order):
    """Phần tiền và số ly đã phân bổ cho từng dòng của đơn (kể cả khoản chờ thu, chờ hoàn).

    None khi lịch sử thiếu (đơn cũ trước khi có sổ phân bổ): khi đó không phân bổ thêm, không đoán."""
    from apps.shifts.models import Refund

    if order.payment_id is None:
        return None
    base = _snapshot(order.payment_id)
    if base is None:
        return None
    state, info = {}, {}

    def add(lines, sign=1):
        for x in lines:
            if x.get('line_id') is None:
                return False
            a, c = state.get(x['line_id'], (0, 0))
            state[x['line_id']] = (a + sign * x['amount'], c + sign * x.get('cups', 0))
            info.setdefault(x['line_id'], {k: v for k, v in x.items() if k not in ('amount', 'cups')})
        return True

    if not add([x for x in base if order.pk in x.get('order_ids', [])]):
        return None
    for charge in order.prepaid_charges.all():
        plan = _plan(CHARGE_TYPE, charge.pk)
        if plan is None or not add(plan):
            return None
    for refund in Refund.objects.filter(payment_id=order.payment_id, kind=Refund.Kind.PREPAID_DECREASE,
                                        order_code=order.code):
        plan = _plan(REFUND_TYPE, refund.pk)
        if plan is None or not add(plan):  # phân bổ hoàn đã ghi số âm
            return None
    for log in AuditLog.objects.filter(object_type=REALLOCATION_TYPE, object_id=str(order.pk)).order_by('id'):
        if not add((log.after or {}).get('lines') or []):
            return None
    return state, info


def _target(order):
    lines = list(order.lines.select_related('item__group').order_by('pk'))
    return {l.pk: (l.unit_price * l.billable_quantity, l.billable_quantity, l) for l in lines}


def plan_adjustment(order, actor, due):
    """Gọi ngay sau khi duyệt điều chỉnh đơn thu trước, trước khi tạo khoản thu thêm hoặc khoản hoàn.

    Trả về danh sách dòng của phần chênh tiền (dương: chờ thu thêm, âm: chờ hoàn), hoặc None khi không phân bổ được.
    Phần đổi qua lại giữa các dòng (tổng 0) và số ly thay đổi được ghi ngay."""
    from apps.shifts.models import Shift

    current = attributed(order)
    if current is None:
        return None
    state, info = current
    target = _target(order)
    diff, cups, infos = {}, {}, dict(info)
    for pk in set(state) | set(target):
        t_amount, t_cups, line = target.get(pk, (0, 0, None))
        s_amount, s_cups = state.get(pk, (0, 0))
        if line is not None:
            infos[pk] = _info(line, order)
        if t_amount != s_amount:
            diff[pk] = t_amount - s_amount
        if t_cups != s_cups:
            cups[pk] = t_cups - s_cups
    if sum(diff.values()) != due:
        return None  # sổ không khớp tổng tiền đơn: không ghi phân bổ sai
    up = {k: v for k, v in diff.items() if v > 0}
    down = {k: -v for k, v in diff.items() if v < 0}
    moved = min(sum(up.values()), sum(down.values()))
    move, money = {}, {}
    if due >= 0:
        for k, v in down.items():
            move[k] = -v
        took = _split(moved, up)
        for k, v in up.items():
            move[k] = move.get(k, 0) + took[k]
            money[k] = v - took[k]
    else:
        for k, v in up.items():
            move[k] = v
        took = _split(moved, down)
        for k, v in down.items():
            move[k] = move.get(k, 0) - took[k]
            money[k] = -(v - took[k])
    moves = [{**infos[k], 'amount': move.get(k, 0), 'cups': cups.get(k, 0)}
             for k in sorted(set(move) | set(cups)) if move.get(k, 0) or cups.get(k, 0)]
    if moves:
        payment = order.payment
        shift = Shift.objects.operating() or order.shift
        _log(REALLOCATION_TYPE, order, actor, moves,
             'Điều chỉnh đơn thu trước: chuyển phần đã thu giữa các dòng món, ghi số ly thay đổi',
             shift_id=shift.pk if shift else None, method=payment.method, at=timezone.now().isoformat())
    return [{**infos[k], 'amount': v, 'cups': 0} for k, v in sorted(money.items()) if v]


def save_charge_plan(charge, actor, lines):
    if lines is not None:
        _log(CHARGE_TYPE, charge, actor, lines, 'Phần chênh theo dòng món của khoản chờ thu thêm')


def save_refund_plan(refund, actor, lines):
    if lines is not None:
        _log(REFUND_TYPE, refund, actor, lines, 'Phần hoàn theo dòng món (số âm)')


def plan_cancel_refund(refund, order, actor):
    """Hủy hóa đơn đã thanh toán: hoàn lại đúng phần đã phân bổ cho các dòng của đơn."""
    current = attributed(order)
    if current is None:
        # Thu sau, đơn khóa: phân bổ từ dòng món nếu khớp số tiền hoàn.
        lines = [{**_info(l, order), 'amount': l.unit_price * l.billable_quantity, 'cups': 0}
                 for l in order.lines.select_related('item__group').order_by('pk') if l.billable_quantity > 0]
    else:
        state, info = current
        lines = [{**info[k], 'amount': a, 'cups': 0} for k, (a, c) in sorted(state.items()) if a]
    if lines and sum(x['amount'] for x in lines) == refund.amount:
        save_refund_plan(refund, actor, [{**x, 'amount': -x['amount']} for x in lines])


# ---------------- đọc cho báo cáo ----------------

def _unallocated(amount, order_ids):
    return [{'amount': amount, 'cups': 0, 'order_ids': order_ids, 'line_id': None, 'size_id': None,
             'item': UNALLOCATED, 'group_id': None, 'group': UNALLOCATED, 'employee_id': None,
             'employee': UNALLOCATED, 'ordered_at': None}]


def _payment_entries(start, end):
    from django.db.models import prefetch_related_objects

    payments = list(Payment.objects.filter(created_at__gte=start, created_at__lt=end).select_related('shift'))
    snapshots = {}
    for log in (AuditLog.objects.filter(object_type=ALLOCATION_TYPE, object_id__in=[str(p.pk) for p in payments],
                                        action=Action.CREATE).order_by('id')):
        snapshots.setdefault(log.object_id, log.after or {})
    # Chỉ khoản thu chưa có sổ phân bổ mới cần đọc đơn và dòng món để ghép lại; khoản đã có sổ (gần như mọi khoản)
    # không phải dựng hàng nghìn dòng món (báo cáo doanh thu chậm vì bước này, QA BUG-03).
    unsnapped = [p for p in payments if not (snapshots.get(str(p.pk), {}).get('lines'))]
    if unsnapped:
        prefetch_related_objects(unsnapped, 'orders__created_by', 'orders__lines__item__group', 'prepaid_charge__order')
    result = []
    for p in payments:
        allocation = snapshots.get(str(p.pk), {}).get('lines') or []
        recovered = False
        # Thu sau: món, giá, số ly khóa sau khi thu. Chỉ ghép lại khi dòng món khớp đúng số tiền; không dùng cho thu
        # trước hay thu thêm.
        if not allocation and p.kind in (Payment.Kind.NORMAL, Payment.Kind.RECEIVED_ITEMS):
            orders = list(p.orders.all())
            if orders and all(o.status in ('da_thanh_toan', 'da_huy') for o in orders):
                billable = sum(l.unit_price * l.billable_quantity for o in orders for l in o.lines.all())
                if billable == p.amount:
                    allocation, recovered = _allocation(p, orders), True
        legacy = not allocation or sum(x.get('amount', 0) for x in allocation) != p.amount
        if legacy:
            orders = list(p.orders.all())
            if not orders:
                charge = getattr(p, 'prepaid_charge', None)
                orders = [charge.order] if charge else []
            allocation = _unallocated(p.amount, [o.pk for o in orders])
        for x in allocation:
            result.append({**x, 'kind': THU, 'at': p.created_at, 'shift': p.shift, 'shift_id': p.shift_id,
                           'method': p.method, 'method_label': p.get_method_display(), 'payment': p,
                           'source': p, 'legacy': legacy, 'recovered_allocation': recovered})
    return result


def _refund_entries(start, end):
    from apps.orders.models import Order
    from apps.shifts.models import Refund

    refunds = list(Refund.objects.filter(status=Refund.Status.PAID, paid_at__gte=start, paid_at__lt=end)
                   .select_related('shift'))
    plans = {}
    for log in (AuditLog.objects.filter(object_type=REFUND_TYPE, object_id__in=[str(r.pk) for r in refunds],
                                        action=Action.CREATE).order_by('id')):
        plans.setdefault(log.object_id, (log.after or {}).get('lines') or [])
    codes = dict(Order.objects.filter(code__in=[r.order_code for r in refunds]).values_list('code', 'pk'))
    result = []
    for r in refunds:
        lines = plans.get(str(r.pk)) or []
        legacy = not lines or sum(x['amount'] for x in lines) != -r.amount
        if legacy:
            lines = _unallocated(-r.amount, [codes[r.order_code]] if r.order_code in codes else [])
        for x in lines:
            result.append({**x, 'cups': 0, 'kind': HOAN, 'at': r.paid_at, 'shift': r.shift, 'shift_id': r.shift_id,
                           'method': 'tien_mat' if r.method == Refund.Method.CASH else 'chuyen_khoan',
                           'method_label': r.get_method_display(), 'payment': None, 'source': r,
                           'legacy': legacy, 'recovered_allocation': False})
    return result


def _reallocation_entries(start, end):
    from apps.shifts.models import Shift

    logs = list(AuditLog.objects.filter(object_type=REALLOCATION_TYPE, created_at__gte=start, created_at__lt=end)
                .order_by('id'))
    shifts = Shift.objects.in_bulk({(l.after or {}).get('shift_id') for l in logs} - {None})
    labels = dict(Payment.Method.choices)
    result = []
    for log in logs:
        data = log.after or {}
        shift = shifts.get(data.get('shift_id'))
        for x in data.get('lines') or []:
            result.append({**x, 'kind': DOI, 'at': log.created_at, 'shift': shift, 'shift_id': data.get('shift_id'),
                           'method': data.get('method'), 'method_label': labels.get(data.get('method'), ''),
                           'payment': None, 'source': log, 'legacy': False, 'recovered_allocation': False})
    return result


def entries(start, end, *, refunds=True):
    """Mọi bút toán phân bổ trong [start, end): thu (dương), hoàn (âm), chuyển giữa các dòng (tổng 0)."""
    from apps.core.reqcache import get_or_set

    def read():
        result = _payment_entries(start, end) + _reallocation_entries(start, end)
        if refunds:
            result += _refund_entries(start, end)
        return result

    # Báo cáo doanh thu đọc cùng kỳ hai lần (bảng số và phân tích bán hàng); trả bản sao để nơi gọi sửa thoải mái.
    return [dict(e) for e in get_or_set(("receipt_entries", start, end, refunds), read)]


def key(entry, dim):
    at = timezone.localtime(entry['at'])
    shift = entry['shift']
    return {'ngay': at.strftime('%d/%m/%Y'), 'khung_gio': f'{at:%H}–{at.hour + 1:02d} giờ',
            'ca': str(shift) if shift else 'Không gắn ca', 'phuong_thuc': entry['method_label'],
            'mon': entry['item'], 'nhom_mon': entry['group'], 'nhan_vien': entry['employee']}[dim]


def sort_key(entry, dim):
    at = timezone.localtime(entry['at'])
    if dim == 'ngay':
        return at.date().toordinal()
    if dim == 'khung_gio':
        return at.hour
    if dim == 'ca':
        return entry['shift'].starts_at.timestamp() if entry['shift'] else float('inf')
    return 0


def row_filter(entry, dim):
    at = timezone.localtime(entry['at'])
    return {'ngay': ('ngay', at.date().isoformat()), 'khung_gio': ('gio', str(at.hour)),
            'ca': ('ca', str(entry['shift_id'] or 'none')), 'phuong_thuc': ('phuong_thuc', entry['method']),
            'mon': ('mon', str(entry['size_id'] or 'none')), 'nhom_mon': ('nhom', str(entry['group_id'] or 'none')),
            'nhan_vien': ('nhan_vien', str(entry['employee_id'] or 'none'))}[dim]


def matches(entry, params):
    for dim in ('khung_gio', 'ca', 'phuong_thuc', 'mon', 'nhom_mon', 'nhan_vien'):
        name, value = row_filter(entry, dim)
        if params.get(name) and params[name] != value:
            return False
    return True


def counts_order(entry):
    """Đơn được đếm ở dòng có tiền thu, hoặc dòng nhận thêm món sau điều chỉnh."""
    return entry['kind'] == THU or (entry['kind'] == DOI and (entry['amount'] > 0 or entry['cups'] > 0))


def grouped(items, dim):
    rows = OrderedDict()
    for entry in items:
        k = key(entry, dim)
        row = rows.setdefault(k, {'key': k, 'revenue': 0, 'refunds': 0, 'cups': 0, 'orders': set(),
                                  'filters': set(), 'sort': (sort_key(entry, dim), k)})
        row['filters'].add(row_filter(entry, dim))
        if entry['kind'] == HOAN:
            row['refunds'] -= entry['amount']
        else:
            row['revenue'] += entry['amount']
        row['cups'] += entry['cups']
        if counts_order(entry):
            row['orders'].update(entry['order_ids'])
    return list(rows.values())
