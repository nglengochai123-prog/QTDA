"""Bán hàng dự phòng bằng phiếu đánh số và nhập bù (FR-06, BRU-03, NFR-16, AC-12, AC-13).

- Chủ quán cấp cho mỗi ca một dãy số phiếu, ghi người nhận.
- Khi có kết nối, Chủ quán nhập bù từng phiếu kèm số phiếu, mã nghiệp vụ nếu có, thời điểm bán,
  giờ có mạng lại và phương thức thanh toán thực tế.
  * Có mã nghiệp vụ trùng một đơn đã lưu: liên kết phiếu với đơn đó, chỉ bổ sung phần pha chế,
    phục vụ, thanh toán còn thiếu; không trừ kho lần nữa.
  * Chưa có đơn: tạo một đơn đã pha, đã phục vụ, đã thanh toán; định mức theo phiên bản có hiệu lực
    tại thời điểm bán ghi trên phiếu (BRU-39).
- Giá theo lịch sử giá và định mức theo phiên bản tại thời điểm bán; thiếu dữ liệu lịch sử thì phiếu
  chờ Chủ quán xác nhận (có nhật ký), chưa ghi đơn, chưa trừ kho, chưa thu tiền.
- Mỗi số phiếu chỉ liên kết một đơn. Số trùng, số ngoài dãy, nhập bù quá hạn, phiếu khai báo hủy
  đều tạo ngoại lệ. Kết ca bị chặn khi chưa khai báo số phiếu cuối đã dùng hoặc còn số chưa xử lý.
"""

from datetime import datetime, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.audit.models import Action
from apps.audit.services import record
from apps.core import numbers, params
from apps.core.idempotency import run_once
from apps.core.models import OperationRecord
from apps.inventory import stock
from apps.inventory.models import StockMovement

from apps.catalog.models import Table

from .models import BackupSlip, BackupSlipRange, Order, OrderLine, OrderLineOption, Payment
from .services import build_lines


def fmt(number):
    return f"{int(number):04d}"


def _when(value, label):
    if isinstance(value, datetime):
        return value if timezone.is_aware(value) else timezone.make_aware(value)
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        raise ValidationError(f"{label} không hợp lệ.")
    return parsed if timezone.is_aware(parsed) else timezone.make_aware(parsed)


def _number(value):
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        raise ValidationError("Số phiếu không hợp lệ.")
    if number <= 0:
        raise ValidationError("Số phiếu không hợp lệ.")
    return number


def _exception(kind, rule, *, shift, employee=None, order=None, detail="", amount=0):
    from apps.control.services import open_exception

    return open_exception(kind, rule=rule, shift=shift, employee=employee, order=order, detail=detail,
                          amount=amount, store=shift.store, one_per_scope=False)


# ---------------- Cấp dãy phiếu cho ca ----------------

@transaction.atomic
def issue_range(user, shift_id, first, last, receiver_id):
    from apps.accounts.models import User
    from apps.shifts.models import Shift

    shift = Shift.objects.select_for_update().get(pk=shift_id)
    first, last = _number(first), _number(last)
    if last < first:
        raise ValidationError("Số cuối phải không nhỏ hơn số đầu.")
    overlap = BackupSlipRange.objects.filter(first_number__lte=last, last_number__gte=first).first()
    if overlap is not None:
        raise ValidationError(f"Dãy {fmt(first)}–{fmt(last)} trùng dãy đã cấp {overlap}.")
    receiver = User.objects.get(pk=receiver_id, is_active=True)
    rng = BackupSlipRange.objects.create(store=shift.store, shift=shift, first_number=first, last_number=last,
                                         receiver=receiver, issued_by=user)
    record(Action.CREATE, actor=user, obj=rng, object_type="orders.BackupSlipRange",
           after={"ca": str(shift), "day_so": f"{fmt(first)}–{fmt(last)}", "nguoi_nhan": str(receiver)})
    return rng


def _range_for(number):
    return BackupSlipRange.objects.select_related("shift").filter(first_number__lte=number,
                                                                  last_number__gte=number).first()


# ---------------- Nhập bù ----------------

def enter_slip(user, operation_key, payload):
    """payload: number, operation_code, sold_at, restored_at, method, transfer_confirmed, table, lines."""
    clean = {
        "number": str(payload.get("number", "")).strip(),
        "operation_code": str(payload.get("operation_code") or "").strip(),
        "sold_at": str(payload.get("sold_at") or ""), "restored_at": str(payload.get("restored_at") or ""),
        "method": payload.get("method") or "", "transfer_confirmed": bool(payload.get("transfer_confirmed")),
        "table": payload.get("table"),
        "lines": [{"item": l.get("item"), "size": l.get("size"), "options": sorted(l.get("options") or []),
                   "quantity": l.get("quantity", 1), "note": l.get("note") or ""} for l in payload.get("lines") or []],
    }

    def action():
        from apps.control.models import ExceptionCase
        from apps.orders.payments import _check_method

        number = _number(clean["number"])
        sold_at = _when(clean["sold_at"], "Thời điểm bán")
        restored_at = _when(clean["restored_at"] or timezone.now().isoformat(), "Giờ có mạng lại")
        # Gõ nhầm ngày giờ trên phiếu làm sai giá, định mức và hạn nhập bù; chặn những giá trị không thể xảy ra.
        soon = timezone.now() + timedelta(minutes=5)
        if sold_at > soon:
            raise ValidationError(f"Thời điểm bán {timezone.localtime(sold_at):%H:%M %d/%m/%Y} chưa tới; kiểm tra "
                                  "lại ngày giờ ghi trên phiếu.")
        if restored_at > soon:
            raise ValidationError(f"Giờ có mạng lại {timezone.localtime(restored_at):%H:%M %d/%m/%Y} chưa tới; "
                                  "kiểm tra lại.")
        rng = _range_for(number)
        if rng is None:
            from apps.shifts.models import Shift

            shift = Shift.objects.operating() or Shift.objects.order_by("-starts_at").first()
            if shift is not None:
                _exception(ExceptionCase.Kind.BACKUP_OUT_OF_RANGE, f"Số phiếu {fmt(number)} không thuộc dãy nào đã cấp",
                           shift=shift, employee=user, detail=f"Nhập bởi {user}")
            return {"ok": False, "message": f"Số phiếu {fmt(number)} không thuộc dãy nào đã cấp; đã tạo ngoại lệ."}
        shift = rng.shift
        existing = BackupSlip.objects.filter(number=number).select_related("order").first()
        if existing is not None:
            _exception(ExceptionCase.Kind.BACKUP_DUPLICATE, f"Số phiếu {fmt(number)} bị nhập trùng",
                       shift=shift, employee=user, order=existing.order,
                       detail=f"Phiếu đã {existing.get_status_display().lower()} lúc "
                              f"{timezone.localtime(existing.created_at):%H:%M %d/%m}; nhập lại bởi {user}")
            return {"ok": False, "message": f"Số phiếu {fmt(number)} đã được xử lý trước đó; đã tạo ngoại lệ trùng số."}
        if shift.status != shift.Status.OPEN:
            raise ValidationError(f"{shift} đã kết; phiếu dự phòng phải nhập bù trước khi kết ca.")
        _check_method(clean["method"], clean["transfer_confirmed"])

        code = clean["operation_code"]
        order = Order.objects.filter(operation_key=code).first() if code else None
        if code and order is None and OperationRecord.objects.filter(key=code).exists():
            raise ValidationError("Mã nghiệp vụ trên phiếu thuộc một thao tác khác, không phải đơn; kiểm tra lại "
                                  "trước khi nhập bù.")
        if order is not None:
            if hasattr(order, "backup_slip"):
                raise ValidationError(f"Đơn {order.code} đã liên kết phiếu {fmt(order.backup_slip.number)}.")
            filled = _complete_existing(order, user, clean, shift, operation_key)
            linked = True
        else:
            missing = []
            lines = _lines_at(clean, sold_at, missing)
            if missing:
                return _hold(user, rng, number, code, sold_at, restored_at, clean, missing, operation_key)
            order = _create_from_slip(user, code or f"pdp-{number}-{operation_key[:40]}", clean, shift, sold_at,
                                      number, operation_key, lines)
            filled = ["tạo đơn mới"]
            linked = False
        deadline = restored_at + timedelta(hours=params.get("backup_entry_hours", at=restored_at))
        late = timezone.now() > deadline
        slip = BackupSlip.objects.create(
            store=shift.store, range=rng, number=number, status=BackupSlip.Status.ENTERED, order=order,
            operation_code=code, sold_at=sold_at, restored_at=restored_at, late=late, linked_existing=linked,
            entered_by=user, operation_key=operation_key)
        record(Action.CREATE, actor=user, obj=slip, object_type="orders.BackupSlip",
               after={"so_phieu": fmt(number), "don": order.code, "lien_ket_don_cu": linked, "bo_sung": filled,
                      "ban_luc": timezone.localtime(sold_at).isoformat(), "qua_han": late})
        if late:
            _exception(ExceptionCase.Kind.BACKUP_LATE, f"Phiếu {fmt(number)} nhập bù quá hạn "
                       f"{params.get('backup_entry_hours', at=restored_at)} giờ sau khi có kết nối",
                       shift=shift, employee=user, order=order,
                       detail=f"Có mạng lại {timezone.localtime(restored_at):%H:%M}, nhập bù "
                              f"{timezone.localtime():%H:%M %d/%m}")
        return {"ok": True, "slip": slip.pk, "order_id": order.pk, "code": order.code, "linked": linked,
                "filled": filled, "late": late, "pending": False,
                "message": (f"Phiếu {fmt(number)} liên kết đơn {order.code}; bổ sung: {', '.join(filled) or 'không'}."
                            if linked else f"Phiếu {fmt(number)} đã tạo đơn {order.code}.")}

    return run_once(operation_key, "backup_slip", clean, action, actor=user)


def _pay(order, user, method, shift, operation_key):
    payment = Payment.objects.create(store=order.store, table=order.table, method=method, amount=order.total,
                                     cashier=user, shift=shift, operation_key=f"{operation_key[:52]}-pdp-tt")
    order.payment, order.status, order.shift = payment, Order.Status.PAID, order.shift or shift
    order.save(update_fields=["payment", "status", "shift", "updated_at"])
    record(Action.CREATE, actor=user, obj=payment, object_type="orders.Payment",
           after={"ban": order.table.code, "so_tien": payment.amount, "phuong_thuc": payment.get_method_display(),
                  "don": [order.code], "nguon": "nhập bù phiếu dự phòng"})
    return payment


def _complete_existing(order, user, clean, shift, operation_key):
    """Chỉ bổ sung phần còn thiếu của đơn đã lưu trực tuyến (AC-12)."""
    if order.pending_request() is not None:
        raise ValidationError(f"Đơn {order.code} đang có yêu cầu điều chỉnh chờ duyệt; xử lý trước khi nhập bù.")
    filled = []
    now = timezone.now()
    for line in order.lines.select_for_update().all():
        pending = line.pending_quantity
        if line.status == OrderLine.Status.WAITING and pending:
            stock.consume(line.usage_for(pending), actor=user, store=order.store, source_type="dong_mon",
                          source_id=line.pk, note=f"Nhập bù phiếu dự phòng, đơn {order.code}")
            line.done_quantity += pending
            line.status, line.done_at = OrderLine.Status.DONE, now
            line._progress_update = True
            line.save(update_fields=["done_quantity", "status", "done_at", "updated_at"])
            filled.append(f"pha chế {pending} ly {line.item_name}")
        if line.status == OrderLine.Status.DONE:
            line.status, line.served_at, line.served_by = OrderLine.Status.SERVED, now, user
            line._progress_update = True
            line.save(update_fields=["status", "served_at", "served_by", "updated_at"])
            filled.append(f"phục vụ {line.item_name}")
    order.refresh_status()
    if order.payment_id is None and order.status != Order.Status.CANCELLED:
        _pay(order, user, clean["method"], order.shift or shift, operation_key)
        filled.append("thanh toán")
    return filled


def _lines_at(clean, sold_at, missing, overrides=None):
    """Giá theo lịch sử giá và định mức theo phiên bản có hiệu lực tại thời điểm bán (BRU-39)."""
    return build_lines(clean, at=sold_at, allow_unsellable=True, missing=missing, overrides=overrides)[1]


def _hold(user, rng, number, code, sold_at, restored_at, clean, missing, operation_key):
    """Thiếu lịch sử giá hoặc định mức: không đoán, giữ phiếu chờ Chủ quán xác nhận (có nhật ký)."""
    slip = BackupSlip.objects.create(
        store=rng.store, range=rng, number=number, status=BackupSlip.Status.PENDING, operation_code=code,
        sold_at=sold_at, restored_at=restored_at, payload=clean, missing=missing, entered_by=user,
        operation_key=operation_key)
    record(Action.CREATE, actor=user, obj=slip, object_type="orders.BackupSlip",
           after={"so_phieu": fmt(number), "trang_thai": slip.get_status_display(),
                  "thieu": [m["text"] for m in missing]})
    return {"ok": True, "slip": slip.pk, "pending": True, "late": False,
            "message": f"Phiếu {fmt(number)} chờ Chủ quán xác nhận: " + "; ".join(m["text"] for m in missing) + "."}


def confirm_slip(user, operation_key, slip_id, prices=None, versions=None, note=""):
    """Chủ quán xác nhận giá hoặc phiên bản định mức còn thiếu rồi mới ghi đơn, trừ kho, thanh toán."""
    if not user.is_owner:
        raise ValidationError("Chỉ Chủ quán xác nhận giá và định mức cho phiếu nhập bù.")
    payload = {"slip": int(slip_id), "prices": {str(k): v for k, v in (prices or {}).items() if v not in ("", None)},
               "versions": {str(k): v for k, v in (versions or {}).items() if v not in ("", None)},
               "note": str(note or "")[:255]}

    def action():
        slip = BackupSlip.objects.select_for_update().select_related("range__shift").get(pk=payload["slip"])
        if slip.status != BackupSlip.Status.PENDING:
            return {"slip": slip.pk, "order_id": slip.order_id, "message": f"{slip} đã được xử lý trước đó."}
        shift = slip.range.shift
        if shift.status != shift.Status.OPEN:
            raise ValidationError(f"{shift} đã kết; không ghi thêm doanh thu vào ca đã kết.")
        overrides = {}
        for key, value in payload["prices"].items():
            overrides.setdefault(int(key), {})["price"] = numbers.vnd(value, f"Đơn giá dòng {key}")
        for key, value in payload["versions"].items():
            overrides.setdefault(int(key), {})["version"] = int(value)
        missing = []
        lines = _lines_at(slip.payload, slip.sold_at, missing, overrides)
        if missing:
            raise ValidationError("Còn thiếu: " + "; ".join(m["text"] for m in missing) + ".")
        clean = slip.payload
        order = _create_from_slip(user, clean.get("operation_code") or f"pdp-{slip.number}-{slip.operation_key[:40]}",
                                  clean, shift, slip.sold_at, slip.number, slip.operation_key, lines)
        slip.status, slip.order, slip.confirmed_by, slip.confirmed_at = (BackupSlip.Status.ENTERED, order, user,
                                                                         timezone.now())
        slip.confirmation = {"gia": payload["prices"], "dinh_muc": payload["versions"], "ghi_chu": payload["note"]}
        slip.save(update_fields=["status", "order", "confirmed_by", "confirmed_at", "confirmation", "updated_at"])
        record(Action.STATUS_CHANGE, actor=user, obj=slip, object_type="orders.BackupSlip",
               before={"trang_thai": BackupSlip.Status.PENDING.label},
               after={"trang_thai": slip.get_status_display(), "don": order.code, "gia_xac_nhan": payload["prices"],
                      "dinh_muc_xac_nhan": payload["versions"]}, reason=payload["note"] or "Xác nhận dữ liệu lịch sử")
        return {"slip": slip.pk, "order_id": order.pk, "message": f"Đã ghi {slip} thành đơn {order.code}."}

    return run_once(operation_key, "backup_confirm", payload, action, actor=user)


def _create_from_slip(user, order_key, clean, shift, sold_at, number, operation_key, lines):
    from .services import _next_code

    table = Table.objects.get(pk=clean["table"])
    order = Order.objects.create(
        store=table.store, code=_next_code(table.store), table=table, created_by=user, operation_key=order_key,
        shift=shift, note=f"Nhập bù phiếu dự phòng {fmt(number)}", status=Order.Status.SERVED,
        total=sum(l["unit_price"] * l["quantity"] for l in lines))
    for position, line in enumerate(lines, start=1):
        order_line = OrderLine.objects.create(
            order=order, position=position, item=line["item"], size=line["size"], item_name=line["item"].name,
            size_name=line["size"].name, unit_price=line["unit_price"], quantity=line["quantity"],
            done_quantity=line["quantity"], note=line["note"], recipe_version=line["version"],
            usage_per_unit=line["usage"], status=OrderLine.Status.SERVED, done_at=sold_at, served_at=sold_at,
            served_by=user)
        OrderLineOption.objects.bulk_create([OrderLineOption(line=order_line, option=o, name=o.name,
                                                             extra_price=o.extra_price) for o in line["options"]])
        # Ly đã pha khi mất mạng: trừ tồn vật lý theo định mức đã chụp, không qua giữ chỗ.
        for ingredient_id, amount in line["usage"].items():
            stock.move(int(ingredient_id), -(Decimal(amount) * line["quantity"]), kind=StockMovement.Kind.CONSUME,
                       actor=user, store=order.store, source_type="phieu_du_phong", source_id=fmt(number),
                       note=f"Đơn {order.code}: {line['quantity']} × {line['item'].name} {line['size'].name}")
    record(Action.CREATE, actor=user, obj=order, object_type="orders.Order",
           after={"code": order.code, "table": table.code, "total": order.total, "phieu_du_phong": fmt(number),
                  "lines": [f"{l['quantity']} × {l['item'].name} {l['size'].name}" for l in lines]},
           reason="Nhập bù phiếu dự phòng")
    _pay(order, user, clean["method"], shift, operation_key)
    return order


# ---------------- Khai báo hủy, khai báo số cuối đã dùng ----------------

@transaction.atomic
def void_slip(user, number, reason):
    from apps.control.models import ExceptionCase

    number = _number(number)
    if not str(reason or "").strip():
        raise ValidationError("Ghi lý do hủy phiếu.")
    rng = _range_for(number)
    if rng is None:
        raise ValidationError(f"Số phiếu {fmt(number)} không thuộc dãy nào đã cấp.")
    if BackupSlip.objects.filter(number=number).exists():
        raise ValidationError(f"Phiếu {fmt(number)} đã được xử lý.")
    slip = BackupSlip.objects.create(store=rng.store, range=rng, number=number, status=BackupSlip.Status.VOIDED,
                                     void_reason=reason.strip(), entered_by=user,
                                     operation_key=f"huy-{rng.pk}-{number}")
    record(Action.CREATE, actor=user, obj=slip, object_type="orders.BackupSlip",
           after={"so_phieu": fmt(number), "trang_thai": slip.get_status_display()}, reason=reason)
    _exception(ExceptionCase.Kind.BACKUP_VOIDED, f"Phiếu dự phòng {fmt(number)} bị khai báo hủy",
               shift=rng.shift, employee=user, detail=reason.strip())
    return slip


@transaction.atomic
def declare_last_used(user, range_id, last_used):
    rng = BackupSlipRange.objects.select_for_update().get(pk=range_id)
    value = int(str(last_used).strip() or 0)
    if value and not rng.first_number <= value <= rng.last_number:
        raise ValidationError(f"Số cuối đã dùng phải nằm trong dãy {rng} hoặc ghi 0 nếu không dùng phiếu nào.")
    rng.last_used_number, rng.declared_by, rng.declared_at = value, user, timezone.now()
    rng.save(update_fields=["last_used_number", "declared_by", "declared_at", "updated_at"])
    record(Action.UPDATE, actor=user, obj=rng, object_type="orders.BackupSlipRange",
           after={"so_cuoi_da_dung": fmt(value) if value else "không dùng"})
    return rng


def unprocessed_numbers(rng):
    """Số đã dùng (đến số cuối khai báo hoặc số lớn nhất đã xử lý) mà chưa nhập bù hay khai báo hủy (AC-13)."""
    done = set(rng.slips.values_list("number", flat=True))
    upto = max([rng.last_used_number or 0, *done]) if done or rng.last_used_number else 0
    return [n for n in range(rng.first_number, upto + 1) if n not in done]


def close_blockers(shift):
    blockers = []
    for slip in BackupSlip.objects.filter(range__shift=shift, status=BackupSlip.Status.PENDING):
        blockers.append(f"{slip} chờ Chủ quán xác nhận giá hoặc định mức trước khi kết ca.")
    for rng in shift.backup_ranges.all():
        if rng.last_used_number is None:
            blockers.append(f"Khai báo số phiếu dự phòng cuối cùng đã dùng của dãy {rng} (ghi 0 nếu không dùng).")
        missing = unprocessed_numbers(rng)
        if missing:
            blockers.append(f"Phiếu dự phòng {', '.join(fmt(n) for n in missing)} chưa nhập bù hoặc khai báo hủy.")
    return blockers
