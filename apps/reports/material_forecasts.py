"""Read-only report projections from the same stored forecasts used by purchasing."""
from datetime import datetime, time, timedelta
from decimal import Decimal
from django.utils import timezone
from apps.forecast.models import IngredientPlan
from apps.forecast.planning import demand
from apps.inventory.models import StockMovement


def attach(rows, start_day, end_day):
    plans = list(IngredientPlan.objects.order_by('-calculated_at', '-id'))
    by_ingredient = {}
    current = {}
    for plan in plans:
        by_ingredient.setdefault(plan.ingredient_id, []).append(plan)
        if plan.is_current:
            current.setdefault(plan.ingredient_id, plan)
    today = timezone.localdate()
    last = min(end_day, today - timedelta(days=1))
    days = [start_day + timedelta(days=j) for j in range(max(0, (last-start_day).days+1))]
    lo = timezone.make_aware(datetime.combine(start_day, time.min))
    hi = timezone.make_aware(datetime.combine(last + timedelta(days=1), time.min))
    actual = {}
    if days:
        moves = StockMovement.objects.filter(created_at__gte=lo, created_at__lt=hi, quantity__lt=0,
                   kind__in=[StockMovement.Kind.CONSUME, StockMovement.Kind.PRODUCE,
                             StockMovement.Kind.WASTE, StockMovement.Kind.COUNT])
        for movement in moves:
            key = (movement.ingredient_id, timezone.localtime(movement.created_at).date())
            actual[key] = actual.get(key, Decimal(0)) - movement.quantity
    for row in rows:
        pk = row['ingredient'].pk
        plan = current.get(pk)
        row['estimate'] = None
        if plan and plan.forecast.get('method') and not plan.forecast.get('requires_approval'):
            dates = [plan.calc_date + timedelta(days=j) for j in range(7)]
            values = [demand(plan.forecast, d) for d in dates]
            if all(v is not None for v in values):
                row['estimate'] = {'mean': sum(values), 'from': dates[0], 'to': dates[-1],
                                   'method': plan.forecast.get('method'), 'calculated_at': plan.calculated_at,
                                   'stale': plan.calc_date < today, 'plan_id': plan.pk}
        predicted, observed, covered = Decimal(0), Decimal(0), 0
        for day in days:
            cutoff = timezone.make_aware(datetime.combine(day, time.min))
            for saved in by_ingredient.get(pk, []):
                if saved.calculated_at >= cutoff or not saved.forecast.get('method') or saved.forecast.get('requires_approval'):
                    continue
                value = demand(saved.forecast, day)
                if value is None:
                    continue
                predicted += Decimal(str(value))
                observed += actual.get((pk, day), Decimal(0))
                covered += 1
                break
        row['comparison'] = {'predicted': predicted if covered else None,
                             'actual': observed if covered else None,
                             'difference': observed-predicted if covered else None,
                             'covered': covered, 'days': len(days),
                             'complete': bool(days) and covered == len(days) and end_day < today}
    return rows
