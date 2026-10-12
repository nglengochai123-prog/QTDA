"""Yêu cầu điều chỉnh đơn, phê duyệt và chuyển cấp (FR-10, FR-11, BRU-08, BRU-09, BRU-19, AC-19 đến AC-24)."""

from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.audit.models import Action
from apps.audit.services import record
from apps.catalog.models import Table
from apps.core import params
from apps.core.idempotency import run_once
from apps.inventory import stock
from apps.control.models import ExceptionCase
from apps.shifts.models import Shift

from . import services
from .models import (AdjustmentReason, AdjustmentRequest, Order, OrderLine, OrderLineOption,
                     PostPrepCancellation)

Kind = AdjustmentRequest.Kind
Level = AdjustmentRequest.Level
Status = AdjustmentRequest.Status


def _request_value(req):
    if req.kind in (Kind.CANCEL_ITEMS, Kind.CHANGE_ITEM) and req.line_id:
        return req.cups * req.line.unit_price
    if req.kind == Kind.CANCEL_PAID:
        return req.order.total
    return req.order.total


def _exception(kind, req, *, rule, amount=0, detail="", one_per_scope=False):
    from apps.control.services import open_exception

    return open_exception(kind, rule=rule, employee=req.requested_by, shift=req.shift, order=req.order,
                          request=req, amount=amount, detail=detail, store=req.order.store,
                          one_per_scope=one_per_scope)


def _check_adjust_count(req):
    """AC-31: vượt số yêu cầu sau pha chế cho phép trong ca thì mở một ngoại lệ nhân viên; các yêu cầu sau gắn vào."""
    from apps.core import params

    limit = params.get("adjust_count_limit")
    count = AdjustmentRequest.objects.filter(requested_by=req.requested_by, shift=req.shift, after_prep=True).count()
    if count > limit:
        _exception(ExceptionCase.Kind.ADJUST_COUNT, req, one_per_scope=True,
                   rule=f"Hơn {limit} yêu cầu điều chỉnh sau pha chế trong ca (BRU-12)",
                   detail=f"Yêu cầu thứ {count}: {req.summary()}")


def _check_post_prep_value(req):
    from apps.core import params
    from apps.control.services import open_exception

    if req.shift is None:
        return
    limit = params.get("post_prep_value_limit")
    total = sum(p.cups * p.line.unit_price for p in
                PostPrepCancellation.objects.filter(request__shift=req.shift).select_related("line"))
    if total > limit:
        open_exception(ExceptionCase.Kind.POST_PREP_VALUE, shift=req.shift, store=req.order.store, request=req,
                       rule=f"Tổng giá trị món hủy sau pha chế trong ca vượt {limit:,} đ (BRU-12)".replace(",", "."),
                       amount=total, detail=f"Tổng hủy sau pha chế {total:,} đ".replace(",", "."))


def _record_shortage_from_request(req):
    """BRU-26: đổi hoặc hủy món vì Hết nguyên liệu được duyệt thì ghi trường hợp thiếu cho nguyên liệu không đủ."""
    from apps.inventory.models import Ingredient, ShortageCase
    from apps.inventory.operations import record_shortage

    usage = {int(k): Decimal(v) for k, v in (req.line.usage_per_unit or {}).items()}
    if not usage:
        return
    available = {k: v[2] for k, v in stock.snapshot_for(list(usage)).items()}
    short = [i for i, q in usage.items() if available.get(i, Decimal(0)) < q] or list(usage)[:1]
    for ingredient in Ingredient.objects.filter(pk__in=short):
        record_shortage(ingredient, ShortageCase.Source.ADJUSTMENT, f"Yêu cầu #{req.pk}")


SKIP_BACKUP_REASON = "Chuyển thẳng Chủ quán (ngoại lệ GD-08): ca chưa có người duyệt dự phòng"


def _shift_for(order):
    return order.shift or Shift.objects.current()


def _owners():
    return {u.pk for u in User.objects.filter(is_active=True) if u.is_owner}


def approver_ids(req, now=None):
    """Những người được xử lý yêu cầu ở cấp hiện tại; người tạo yêu cầu luôn bị loại (AC-22).

    Cấp được tính khi đọc (req.effective_level), không phụ thuộc việc ai đó vừa mở màn hình.
    """
    owners = _owners()
    if req.kind == Kind.CANCEL_PAID:
        allowed = owners  # AC-23: chỉ Chủ quán.
    else:
        shift = _shift_for(req.order)
        allowed = set(owners)
        if shift is not None:
            allowed.add(shift.approver_id)
            if req.effective_level(now) >= Level.BACKUP and shift.backup_approver_id:
                allowed.add(shift.backup_approver_id)
        else:
            # Chưa khai báo ca: mọi Quản lý ca đang làm được duyệt.
            allowed |= {u.pk for u in User.objects.filter(is_active=True) if u.has_role(Role.QUAN_LY_CA)}
    allowed.discard(req.requested_by_id)
    return allowed


def can_decide(user, req, now=None):
    return req.status == Status.PENDING and user.is_active and user.pk in approver_ids(req, now)


def _initial_level(user, order, kind):
    if kind == Kind.CANCEL_PAID:
        return Level.OWNER
    shift = _shift_for(order)
    if shift is not None and shift.approver_id == user.pk:
        return Level.BACKUP if shift.backup_approver_id else Level.OWNER  # AC-22
    return Level.SHIFT


def _cups(value, maximum, label):
    try:
        cups = int(value)
    except (TypeError, ValueError):
        raise ValidationError("Số ly không hợp lệ.")
    if not 1 <= cups <= maximum:
        raise ValidationError(f"Số ly {label} phải từ 1 đến {maximum}.")
    return cups


def create_request(user, operation_key, payload):
    """Tạo yêu cầu điều chỉnh. Thiếu lý do thì không cho gửi (AC-20)."""
    clean = {
        "order": payload.get("order"), "kind": payload.get("kind"), "line": payload.get("line"),
        "cups": payload.get("cups"), "target_table": payload.get("target_table"),
        "new_line": payload.get("new_line"), "reason": payload.get("reason"), "note": str(payload.get("note") or "")[:255],
    }

    def action():
        order = Order.objects.select_for_update().filter(pk=clean["order"]).first()
        if order is None:
            raise ValidationError("Không tìm thấy đơn.")
        if clean["kind"] not in Kind.values:
            raise ValidationError("Chọn loại điều chỉnh.")
        reason = AdjustmentReason.objects.filter(pk=clean["reason"] or 0, is_active=True).first()
        if reason is None:
            raise ValidationError("Chọn lý do điều chỉnh từ danh mục.")
        if order.status == Order.Status.CANCELLED:
            raise ValidationError("Đơn đã hủy.")
        if order.pending_request() is not None:
            raise ValidationError("Đơn này đang có một yêu cầu chờ duyệt; chờ xử lý xong rồi gửi tiếp.")
        kind = clean["kind"]
        if kind == Kind.CANCEL_PAID:
            if order.status != Order.Status.PAID:
                raise ValidationError("Chỉ hủy hóa đơn khi đơn đã thanh toán.")
        elif order.status == Order.Status.PAID:
            raise ValidationError("Đơn đã thanh toán; chỉ có thể gửi yêu cầu hủy hóa đơn.")
        fields = {}
        if kind in (Kind.CANCEL_ITEMS, Kind.CHANGE_ITEM):
            line = order.lines.filter(pk=clean["line"] or 0).first()
            if line is None or line.billable_quantity == 0:
                raise ValidationError("Chọn món cần điều chỉnh.")
            fields["line"] = line
            fields["cups"] = _cups(clean["cups"], line.billable_quantity, "điều chỉnh")
        if kind == Kind.CHANGE_ITEM:
            raw = clean["new_line"] or {}
            _, built = services.build_lines({"table": order.table_id, "lines": [raw]})
            new = built[0]
            fields["new_line"] = {"item": new["item"].pk, "size": new["size"].pk,
                                  "options": [o.pk for o in new["options"]], "quantity": new["quantity"],
                                  "note": new["note"]}
            option_text = ", ".join(o.name for o in new["options"])
            fields["new_line_text"] = (f"{new['quantity']} × {new['item'].name} {new['size'].name}"
                                       + (f" ({option_text})" if option_text else ""))[:200]
        if kind == Kind.MOVE_TABLE:
            target = Table.objects.filter(pk=clean["target_table"] or 0, is_active=True).first()
            if target is None or target.pk == order.table_id:
                raise ValidationError("Chọn bàn mới khác bàn hiện tại.")
            fields["target_table"] = target
        after_prep = order.lines.filter(done_quantity__gt=0).exists()
        req = AdjustmentRequest.objects.create(
            store=order.store, order=order, kind=kind, reason=reason, note=clean["note"],
            level=_initial_level(user, order, kind), level_since=timezone.now(),
            level_minutes=params.get("approval_level_minutes"),
            requested_by=user, operation_key=operation_key, after_prep=after_prep,
            shift=order.shift or Shift.objects.current(), **fields)
        if after_prep:
            _check_adjust_count(req)
        if kind != Kind.CANCEL_PAID and req.level == Level.OWNER:
            record(Action.STATUS_CHANGE, actor=user, obj=req, object_type="orders.AdjustmentRequest",
                   after={"cap": req.get_level_display()}, reason=SKIP_BACKUP_REASON)
        record(Action.CREATE, actor=user, obj=req, object_type="orders.AdjustmentRequest",
               after={"summary": req.summary(), "level": req.get_level_display()}, reason=reason.name)
        from apps.core.push import notify_later

        notify_later(approver_ids(req), f"Yêu cầu duyệt: {req.summary()}"[:120],
                     f"Bàn {order.table.code} · {reason.name} · {user}", "/duyet/")  # NFR-17
        return {"request": req.pk, "summary": req.summary(), "level": req.get_level_display()}

    return run_once(operation_key, "adjust_request", clean, action, actor=user)


def escalate_due(now=None):
    """Ghi các lần chuyển cấp đã đến hạn vào yêu cầu và nhật ký (BRU-09, AC-24).

    Chỉ tác vụ định kỳ (apps.core.periodic) gọi hàm này. Màn hình và thao tác duyệt không cần chờ
    nó chạy vì cấp hiện hành được tính khi đọc; hàm chỉ để lưu vết đúng thời điểm chuyển cấp.
    """
    now = now or timezone.now()
    moved = []
    with transaction.atomic():
        for req in (AdjustmentRequest.objects.select_for_update(of=("self",))
                    .filter(status=Status.PENDING, level__lt=Level.EXHAUSTED).select_related("order", "shift")):
            steps = req.level_steps(now)
            for level, since in steps:
                before_level, before = req.level, req.get_level_display()
                req.level, req.level_since = level, since
                reason = "Chuyển cấp do quá thời hạn duyệt"
                if before_level == Level.SHIFT and level == Level.OWNER:
                    reason = SKIP_BACKUP_REASON
                record(Action.STATUS_CHANGE, obj=req, object_type="orders.AdjustmentRequest",
                       actor_label="hệ thống", before={"cap": before}, after={"cap": req.get_level_display()},
                       reason=reason)
            if steps:
                req.save(update_fields=["level", "level_since", "updated_at"])
                moved.append(req.pk)
                from apps.core.push import notify_later

                notify_later(approver_ids(req, now), f"Chuyển cấp duyệt: {req.summary()}"[:120],
                             f"Quá hạn ở cấp trước; giờ chờ {req.get_level_display()}.", "/duyet/")
    return moved


def pending_for(user):
    pending = (AdjustmentRequest.objects.filter(status=Status.PENDING)
               .select_related("order", "order__table", "line", "reason", "requested_by", "target_table"))
    return [r for r in pending if user.pk in approver_ids(r)]


def _cancel_cups(line, cups, req, actor):
    """Hủy `cups` ly: ly chưa pha trả lại tồn có thể dùng; ly đã pha ghi Hủy sau pha chế (BRU-08, BRU-19)."""
    from_pending = min(cups, line.pending_quantity)
    if from_pending:
        stock.release(line.usage_for(from_pending))
        line.cancelled_quantity += from_pending
    from_done = min(cups - from_pending, line.done_quantity - line.voided_done_quantity)
    if from_done:
        line.voided_done_quantity += from_done
        PostPrepCancellation.objects.create(
            line=line, cups=from_done, reason=req.reason, request=req,
            usage={str(k): str(v) for k, v in line.usage_for(from_done).items()})
    if from_pending + from_done != cups:
        raise ValidationError("Số ly cần hủy vượt quá số ly còn lại của món.")
    line.settle_status()
    line._progress_update = True
    line.save(update_fields=["cancelled_quantity", "voided_done_quantity", "status", "updated_at"])


def _add_line(order, spec, actor, delivered=False):
    _, built = services.build_lines({"table": order.table_id, "lines": [spec]})
    new = built[0]
    totals = {int(k): Decimal(v) * new["quantity"] for k, v in new["usage"].items()}
    position = (order.lines.aggregate(m=Max("position"))["m"] or 0) + 1
    stock.reserve(totals)
    line = OrderLine.objects.create(
        order=order, position=position, item=new["item"], size=new["size"], item_name=new["item"].name,
        size_name=new["size"].name, unit_price=new["unit_price"], quantity=new["quantity"], note=new["note"],
        recipe_version=new["version"], usage_per_unit=new["usage"])
    OrderLineOption.objects.bulk_create([OrderLineOption(line=line, option=o, name=o.name, extra_price=o.extra_price)
                                         for o in new["options"]])
    if delivered:
        # Món khách đã thực nhận (AC-10): đã pha nên trừ tồn vật lý ngay.
        stock.consume(totals, actor=actor, store=order.store, source_type="dong_mon", source_id=line.pk,
                      note=f"Đơn {order.code}: món thực nhận")
        line.done_quantity = line.quantity
        line.status = OrderLine.Status.SERVED
        line.done_at = line.served_at = timezone.now()
        line.served_by = actor
        line._progress_update = True
        line.save(update_fields=["done_quantity", "status", "done_at", "served_at", "served_by", "updated_at"])
    return line


def apply_effects(req, actor, delivered=False):
    order = Order.objects.select_for_update().get(pk=req.order_id)
    before = {"table": order.table.code, "total": order.total, "status": order.status}
    if req.kind in (Kind.CANCEL_ITEMS, Kind.CHANGE_ITEM):
        line = OrderLine.objects.select_for_update().get(pk=req.line_id)
        _cancel_cups(line, req.cups, req, actor)
    if req.kind == Kind.CHANGE_ITEM:
        _add_line(order, req.new_line, actor, delivered=delivered)
    if req.kind == Kind.MOVE_TABLE:
        order.table = req.target_table
        order.save(update_fields=["table", "updated_at"])
    if req.kind == Kind.CANCEL_PAID:
        from apps.shifts.services import approve_refund

        order.status = Order.Status.CANCELLED
        order.save(update_fields=["status", "updated_at"])
        approve_refund(order, actor, req.pk)
        _exception(ExceptionCase.Kind.PAID_CANCELLED, req, rule="Hóa đơn đã thanh toán bị hủy (BRU-12)",
                   amount=order.total, detail=f"{req.summary()} · duyệt bởi {actor}")
        payment = order.payment
        if payment is not None and not payment.orders.exclude(status=Order.Status.CANCELLED).exists():
            payment.status = payment.Status.VOIDED
            payment.save(update_fields=["status", "updated_at"])
    else:
        order.recompute_total()
        order.refresh_status()
        if req.kind in (Kind.CANCEL_ITEMS, Kind.CHANGE_ITEM):
            _check_post_prep_value(req)
            if req.reason.name.strip().lower() == "hết nguyên liệu":
                _record_shortage_from_request(req)
    order.refresh_from_db()
    return before, {"table": order.table.code, "total": order.total, "status": order.status}


def decide(user, operation_key, request_id, approve, note=""):
    """Phê duyệt hoặc từ chối. Người tạo yêu cầu không tự duyệt được (AC-22)."""
    payload = {"request": int(request_id), "approve": bool(approve), "note": str(note or "")[:255]}

    def action():
        req = AdjustmentRequest.objects.select_for_update().select_related("order", "reason").get(pk=payload["request"])
        if req.status != Status.PENDING:
            return {"request": req.pk, "status": req.get_status_display(), "message": "Yêu cầu đã được xử lý trước đó."}
        if not can_decide(user, req):
            raise ValidationError("Bạn không có quyền xử lý yêu cầu này ở cấp hiện tại.")
        before = after = None
        if payload["approve"]:
            before, after = apply_effects(req, user)
            req.status = Status.APPROVED
        else:
            req.status = Status.REJECTED
            if req.after_prep:
                _exception(ExceptionCase.Kind.REJECTED_ADJUSTMENT, req,
                           rule="Yêu cầu điều chỉnh sau pha chế bị từ chối (BRU-12)",
                           amount=_request_value(req),
                           detail=f"{req.summary()} · bị từ chối bởi {user} · {payload['note']}")
        req.decided_by, req.decided_at, req.decision_note = user, timezone.now(), payload["note"]
        req.save(update_fields=["status", "decided_by", "decided_at", "decision_note", "updated_at"])
        record(Action.STATUS_CHANGE, actor=user, obj=req, object_type="orders.AdjustmentRequest",
               before=before, after={"ket_qua": req.get_status_display(), **(after or {})},
               reason=f"{req.summary()} · lý do {req.reason.name} · người yêu cầu {req.requested_by}")
        return {"request": req.pk, "status": req.get_status_display(), "message": ""}

    return run_once(operation_key, "adjust_decide", payload, action, actor=user)
