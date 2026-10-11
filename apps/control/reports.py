"""Báo cáo điều chỉnh đơn theo ca (FR-14, AC-29)."""

from apps.orders.models import AdjustmentRequest, PostPrepCancellation


def request_value(req):
    if req.kind in (AdjustmentRequest.Kind.CANCEL_ITEMS, AdjustmentRequest.Kind.CHANGE_ITEM) and req.line_id:
        return req.cups * req.line.unit_price
    if req.kind == AdjustmentRequest.Kind.CANCEL_PAID:
        return req.order.total
    return 0


def adjustment_report(shift):
    requests = list(AdjustmentRequest.objects.filter(shift=shift)
                    .select_related("order", "order__table", "line", "reason", "requested_by", "decided_by")
                    .order_by("created_at"))
    rows = [{"req": r, "value": request_value(r)} for r in requests]
    rejected = [row for row in rows if row["req"].status == AdjustmentRequest.Status.REJECTED]
    paid_cancel = [row for row in rows if row["req"].kind == AdjustmentRequest.Kind.CANCEL_PAID]
    others = [row for row in rows if row not in rejected and row not in paid_cancel]
    post_prep_value = sum(p.cups * p.line.unit_price for p in
                          PostPrepCancellation.objects.filter(request__shift=shift).select_related("line"))
    by_employee = {}
    for row in rows:
        name = str(row["req"].requested_by)
        by_employee[name] = by_employee.get(name, 0) + 1
    return {"rows": others, "rejected": rejected, "paid_cancel": paid_cancel, "total": len(rows),
            "post_prep_value": post_prep_value, "by_employee": sorted(by_employee.items())}
