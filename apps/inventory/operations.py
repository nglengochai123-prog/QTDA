"""Nguyên vật liệu vận hành: báo nhanh, phiếu nhập, khoản phải trả, kiểm kê, hao hụt, thiếu nguyên liệu,
đặt hàng (FR-23 đến FR-27, FR-30, BRU-19, BRU-23, BRU-25, BRU-26, BRU-33)."""

from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.audit.models import Action
from apps.audit.services import record
from apps.core import params
from apps.core.idempotency import run_once

from . import consumption, stock
from .models import (Ingredient, Payable, PurchaseOrder, QuickReport, Receipt, ReceiptLine, ShortageCase,
                     StockCount, StockMovement, Supplier, SupplierPayment, Waste)


def _dec(value, label, allow_zero=False):
    try:
        number = Decimal(str(value).replace(",", ".").strip())
    except (InvalidOperation, TypeError):
        raise ValidationError(f"{label} không hợp lệ.")
    if number < 0 or (number == 0 and not allow_zero):
        raise ValidationError(f"{label} phải lớn hơn 0.")
    return number


def in_opening_hours(at=None):
    hour = timezone.localtime(at or timezone.now()).hour
    return params.get("open_hour") <= hour < params.get("close_hour")


# ---------------- Trường hợp thiếu nguyên liệu (FR-27, BRU-26) ----------------

def record_shortage(ingredient, source, source_ref="", at=None):
    """Ghi một trường hợp thiếu; mỗi nguyên liệu tối đa một trường hợp mỗi ngày (AC-61, AC-63)."""
    day = timezone.localdate(at or timezone.now())
    if ShortageCase.objects.filter(ingredient=ingredient, day=day).exists():
        return None
    try:
        with transaction.atomic():
            return ShortageCase.objects.create(store=ingredient.store, ingredient=ingredient, day=day, source=source,
                                               source_ref=source_ref[:100])
    except IntegrityError:
        return None


# ---------------- Báo nhanh (FR-23) ----------------

def quick_report(user, operation_key, ingredient_id, level, estimated_left=None):
    payload = {"ingredient": int(ingredient_id), "level": level, "left": str(estimated_left or "")}

    def action():
        ingredient = Ingredient.objects.get(pk=payload["ingredient"], is_active=True)
        if level not in QuickReport.Level.values:
            raise ValidationError("Chọn Sắp hết hoặc Đã hết.")
        left = _dec(estimated_left, "Lượng còn lại", allow_zero=True) if estimated_left not in (None, "") else None
        report = QuickReport.objects.create(store=ingredient.store, ingredient=ingredient, level=level,
                                            estimated_left=left, reporter=user)
        record(Action.CREATE, actor=user, obj=report, object_type="inventory.QuickReport",
               after={"nguyen_lieu": ingredient.name, "muc": report.get_level_display(), "con_lai": str(left or "")})
        shortage = None
        if level == QuickReport.Level.OUT and in_opening_hours():
            shortage = record_shortage(ingredient, ShortageCase.Source.REPORTED_OUT, f"Báo nhanh #{report.pk}")
        return {"report": report.pk, "shortage_recorded": shortage is not None}

    return run_once(operation_key, "quick_report", payload, action, actor=user)


@transaction.atomic
def acknowledge(user, report_id, note=""):
    report = QuickReport.objects.select_for_update().get(pk=report_id)
    if report.acknowledged_at is None:
        report.acknowledged_by, report.acknowledged_at, report.note = user, timezone.now(), note[:255]
        report.save(update_fields=["acknowledged_by", "acknowledged_at", "note", "updated_at"])
    return report


def open_quick_reports():
    return QuickReport.objects.filter(acknowledged_at__isnull=True).select_related("ingredient", "reporter")


# ---------------- Đặt hàng (FR-30, BRU-23) ----------------

def create_purchase_order(user, supplier_id, ingredient_id, quantity, expected_date, note="", *, operation_key):
    payload = {"supplier": int(supplier_id), "ingredient": int(ingredient_id), "quantity": str(quantity),
               "date": str(expected_date), "note": note}

    def action():
        supplier = Supplier.objects.get(pk=payload["supplier"])
        ingredient = Ingredient.objects.get(pk=payload["ingredient"])
        po = PurchaseOrder.objects.create(store=ingredient.store, supplier=supplier, ingredient=ingredient,
                                          quantity=_dec(quantity, "Số lượng"), expected_date=expected_date, note=note,
                                          created_by=user)
        record(Action.CREATE, actor=user, obj=po, object_type="inventory.PurchaseOrder",
               after={"nha_cung_cap": supplier.name, "nguyen_lieu": ingredient.name, "so_luong": str(po.quantity),
                      "ngay_giao": expected_date})
        return {"po": po.pk}

    result, _ = run_once(operation_key, "purchase_order", payload, action, actor=user)
    return PurchaseOrder.objects.get(pk=result["po"])


def refresh_late(today=None):
    """Ghi trạng thái Giao chậm và nhật ký cho lần đặt quá ngày giao (AC-68). Chỉ tác vụ định kỳ gọi."""
    today = today or timezone.localdate()
    late = []
    for po in PurchaseOrder.objects.filter(status__in=[PurchaseOrder.Status.ORDERED, PurchaseOrder.Status.PARTIAL],
                                           expected_date__lt=today):
        po.status = PurchaseOrder.Status.LATE
        po.save(update_fields=["status", "updated_at"])
        record(Action.STATUS_CHANGE, obj=po, object_type="inventory.PurchaseOrder", actor_label="hệ thống",
               after={"trang_thai": "Giao chậm"}, reason="Quá ngày giao dự kiến chưa có phiếu nhập đủ")
        late.append(po)
    return late


@transaction.atomic
def reschedule(user, po_id, new_date):
    po = PurchaseOrder.objects.select_for_update().get(pk=po_id)
    before = po.expected_date
    po.expected_date = new_date
    po.settle_status()
    po.save(update_fields=["expected_date", "status", "updated_at"])
    record(Action.UPDATE, actor=user, obj=po, object_type="inventory.PurchaseOrder",
           before={"ngay_giao": before}, after={"ngay_giao": new_date, "trang_thai": po.get_status_display()})
    return po


# ---------------- Phiếu nhập và khoản phải trả (FR-24, BRU-33) ----------------

def _next_receipt_code():
    today = timezone.localdate()
    count = Receipt.objects.filter(created_at__date=today).count()
    while True:
        count += 1
        code = f"PN{today:%d%m}-{count:02d}"
        if not Receipt.objects.filter(code=code).exists():
            return code


def create_receipt(user, operation_key, supplier_id, lines, payment_type, *, invoice_photo=None, due_days=7,
                   paid_source=SupplierPayment.Source.TRANSFER):
    """lines: [{"ingredient": id, "quantity": x, "unit_price": đồng, "purchase_order": id|None}]"""
    payload = {"supplier": int(supplier_id), "lines": lines, "payment": payment_type, "due": int(due_days or 0),
               "source": paid_source, "photo": getattr(invoice_photo, "name", "")}

    def action():
        from apps.shifts.models import CashEntry, ExpenseCategory, Shift

        supplier = Supplier.objects.get(pk=payload["supplier"])
        if payment_type not in Receipt.PaymentType.values:
            raise ValidationError("Chọn Trả ngay hoặc Trả sau.")
        if not lines:
            raise ValidationError("Phiếu nhập chưa có dòng nào.")
        parsed = []
        for raw in lines:
            ingredient = Ingredient.objects.get(pk=raw["ingredient"])
            qty = _dec(raw.get("quantity"), f"Số lượng {ingredient.name}")
            price = int(_dec(raw.get("unit_price"), f"Đơn giá {ingredient.name}", allow_zero=True))
            po = None
            if raw.get("purchase_order"):
                po = PurchaseOrder.objects.select_for_update().get(pk=raw["purchase_order"], ingredient=ingredient)
            parsed.append((ingredient, qty, price, po))
        total = sum(int((q * p).to_integral_value()) for _, q, p, _ in parsed)
        if not invoice_photo:
            # FR-24 và AC-55: phiếu nhập phải có ảnh hóa đơn khi lưu, không phụ thuộc giá trị.
            raise ValidationError("Chụp ảnh hóa đơn hoặc phiếu giao hàng trước khi lưu phiếu nhập.")
        receipt = Receipt.objects.create(store=supplier.store, code=_next_receipt_code(), supplier=supplier,
                                         payment_type=payment_type, total=total, invoice_photo=invoice_photo or "",
                                         created_by=user, operation_key=operation_key)
        for ingredient, qty, price, po in parsed:
            ReceiptLine.objects.create(receipt=receipt, ingredient=ingredient, quantity=qty, unit_price=price,
                                       purchase_order=po)
            stock.move(ingredient.pk, qty, kind=StockMovement.Kind.RECEIPT, actor=user, store=supplier.store,
                       source_type="phieu_nhap", source_id=receipt.code, note=supplier.name)
            if po is not None:
                po.received_quantity += qty
                po.settle_status()
                po.save(update_fields=["received_quantity", "status", "updated_at"])  # AC-52, AC-69
        today = timezone.localdate()
        payable = Payable.objects.create(store=supplier.store, receipt=receipt, supplier=supplier, amount=total,
                                         due_date=today + timedelta(days=payload["due"] if payment_type == "tra_sau" else 0))
        if payment_type == Receipt.PaymentType.NOW and total:
            SupplierPayment.objects.create(payable=payable, amount=total, paid_on=today, source=paid_source, actor=user)
            if paid_source == SupplierPayment.Source.SHIFT_CASH:
                shift = Shift.objects.current()
                if shift is None:
                    raise ValidationError("Không có ca đang mở để chi tiền mặt quỹ ca.")
                CashEntry.objects.create(store=shift.store, shift=shift, kind=CashEntry.Kind.EXPENSE, amount=total,
                                         category=ExpenseCategory.MATERIALS, note=f"Phiếu nhập {receipt.code}",
                                         actor=user, operation_key=f"{operation_key[:56]}-quyca")
        record(Action.CREATE, actor=user, obj=receipt, object_type="inventory.Receipt",
               after={"ma": receipt.code, "nha_cung_cap": supplier.name, "gia_tri": total,
                      "thanh_toan": receipt.get_payment_type_display(),
                      "dong": [f"{q} {i.get_unit_display()} {i.name} × {p}" for i, q, p, _ in parsed]})
        return {"receipt": receipt.pk, "code": receipt.code, "total": total}

    return run_once(operation_key, "receipt", payload, action, actor=user)


def pay_supplier(user, payable_id, amount, source, paid_on=None, *, operation_key):
    """Chủ quán ghi thanh toán khoản phải trả; trả một phần thì phần còn lại vẫn phải trả (AC-54)."""
    if not user.is_owner:
        raise ValidationError("Chỉ Chủ quán ghi thanh toán khoản phải trả.")
    payload = {"payable": int(payable_id), "amount": str(amount), "source": source, "paid_on": str(paid_on or "")}

    def action():
        payable = Payable.objects.select_for_update().get(pk=payload["payable"])
        value = int(_dec(amount, "Số tiền"))
        if value > payable.remaining():
            raise ValidationError(f"Số tiền vượt phần còn phải trả ({payable.remaining():,} đ).".replace(",", "."))
        if source not in SupplierPayment.Source.values:
            raise ValidationError("Chọn nguồn tiền.")
        payment = SupplierPayment.objects.create(payable=payable, amount=value,
                                                 paid_on=paid_on or timezone.localdate(), source=source, actor=user)
        record(Action.CREATE, actor=user, obj=payable, object_type="inventory.Payable",
               after={"da_tra": value, "con_lai": payable.remaining(), "nguon": payment.get_source_display()})
        return {"payment": payment.pk}

    result, _ = run_once(operation_key, "supplier_payment", payload, action, actor=user)
    return SupplierPayment.objects.get(pk=result["payment"])


def overdue_payables(today=None):
    today = today or timezone.localdate()
    return [p for p in Payable.objects.filter(due_date__lt=today).select_related("supplier", "receipt") if not p.is_paid]


# ---------------- Hao hụt (FR-26, BRU-19) ----------------

def record_waste(user, operation_key, ingredient_id, quantity, reason, note=""):
    payload = {"ingredient": int(ingredient_id), "quantity": str(quantity), "reason": reason, "note": note}

    def action():
        ingredient = Ingredient.objects.get(pk=payload["ingredient"])
        if reason not in Waste.Reason.values:
            raise ValidationError("Chọn lý do hao hụt.")  # AC-59
        qty = _dec(quantity, "Số lượng")
        waste = Waste.objects.create(store=ingredient.store, ingredient=ingredient, quantity=qty, reason=reason,
                                     note=note[:255], actor=user, operation_key=operation_key)
        stock.move(ingredient.pk, -qty, kind=StockMovement.Kind.WASTE, actor=user, store=ingredient.store,
                   source_type="hao_hut", source_id=waste.pk, note=waste.get_reason_display())
        record(Action.CREATE, actor=user, obj=waste, object_type="inventory.Waste",
               after={"nguyen_lieu": ingredient.name, "so_luong": str(qty), "ly_do": waste.get_reason_display()})
        return {"waste": waste.pk}

    return run_once(operation_key, "waste", payload, action, actor=user)


# ---------------- Kiểm kê (FR-25, BRU-25) ----------------

def _apply_count(count, actor):
    # Điều chỉnh theo chênh lệch lúc đếm, giữ nguyên các biến động phát sinh trong lúc chờ xác nhận.
    stock.move(count.ingredient_id, count.difference, kind=StockMovement.Kind.COUNT, actor=actor, store=count.store,
               source_type="kiem_ke", source_id=count.pk, note=count.reason)


def submit_count(user, operation_key, ingredient_id, counted, reason=""):
    payload = {"ingredient": int(ingredient_id), "counted": str(counted), "reason": reason}

    def action():
        ingredient = Ingredient.objects.get(pk=payload["ingredient"])
        value = _dec(counted, "Số lượng đếm được", allow_zero=True)
        row = stock._lock([ingredient.pk])[ingredient.pk]
        diff = value - row.physical
        percent = (abs(diff) / row.physical * 100) if row.physical else (Decimal(100) if diff else Decimal(0))
        limit = params.get("count_threshold_percent")
        over = percent > limit
        if over and not reason.strip():
            raise ValidationError(f"Chênh lệch {percent:.1f}% vượt ngưỡng; ghi lý do để gửi Chủ quán xác nhận.")  # AC-56
        count = StockCount.objects.create(
            store=ingredient.store, ingredient=ingredient, counted=value, physical_at_count=row.physical,
            difference=diff, percent=percent.quantize(Decimal("0.01")), reason=reason[:255],
            status=StockCount.Status.PENDING if over else StockCount.Status.APPLIED, counter=user,
            threshold_percent=limit,
            operation_key=operation_key)
        if not over and diff != 0:
            _apply_count(count, user)  # AC-57
        record(Action.CREATE, actor=user, obj=count, object_type="inventory.StockCount",
               after={"nguyen_lieu": ingredient.name, "dem_duoc": str(value), "ton_vat_ly": str(row.physical),
                      "chenh_lech": str(diff), "ty_le": f"{percent:.2f}%", "trang_thai": count.get_status_display()},
               reason=reason)
        _check_count_accumulated(count)
        _close_recounts(count, user)
        if not over:
            consumption.check_after_count(count, user)  # FR-16
        return {"count": count.pk, "difference": str(diff), "percent": f"{percent:.1f}", "pending": over}

    return run_once(operation_key, "stock_count", payload, action, actor=user)


@transaction.atomic
def confirm_count(user, count_id, approve=True):
    if not user.is_owner:
        raise ValidationError("Chỉ Chủ quán xác nhận chênh lệch kiểm kê vượt ngưỡng.")
    count = StockCount.objects.select_for_update().get(pk=count_id)
    if count.status != StockCount.Status.PENDING:
        return count
    count.status = StockCount.Status.APPLIED if approve else StockCount.Status.REJECTED
    count.confirmed_by, count.confirmed_at = user, timezone.now()
    count.save(update_fields=["status", "confirmed_by", "confirmed_at", "updated_at"])
    if approve and count.difference != 0:
        _apply_count(count, user)
    if approve:
        consumption.check_after_count(count, user)  # FR-16
    record(Action.STATUS_CHANGE, actor=user, obj=count, object_type="inventory.StockCount",
           after={"trang_thai": count.get_status_display()})
    return count


def _check_count_accumulated(count):
    """Tổng thiếu kiểm kê trong tháng của một nguyên liệu vượt ngưỡng thì tạo ngoại lệ (AC-58)."""
    from apps.control.models import ExceptionCase
    from apps.control.services import open_exception

    ingredient = count.ingredient
    now = timezone.localtime(count.created_at)
    month = StockCount.objects.filter(ingredient=ingredient, created_at__year=now.year, created_at__month=now.month,
                                      difference__lt=0).exclude(status=StockCount.Status.REJECTED)
    total = -sum(c.difference for c in month)
    threshold = ingredient.count_accumulated_threshold or ingredient.pack_size
    if total > threshold:
        counters = sorted({str(c.counter) for c in month})
        open_exception(ExceptionCase.Kind.COUNT_ACCUMULATED, ingredient=ingredient, period=f"{now:%Y-%m}",
                       store=ingredient.store,
                       rule=f"Thiếu kiểm kê tích lũy tháng của {ingredient.name} vượt {stock.fmt_qty(threshold)} "
                            f"{ingredient.get_unit_display()} (BRU-25)",
                       detail=f"Tổng thiếu {stock.fmt_qty(total)} {ingredient.get_unit_display()} qua {month.count()} lần "
                              f"kiểm kê; người kiểm kê: {', '.join(counters)}.")


def request_recount(user, operation_key, ingredient_ids):
    """Phục vụ đề nghị pha chế kiểm kê nhanh các nguyên liệu bị báo thiếu khi tạo đơn (AC-03, Bảng 5.4)."""
    from apps.shifts.models import Shift

    from .models import RecountRequest

    ids = sorted({int(i) for i in ingredient_ids})

    def action():
        created = []
        for ingredient in Ingredient.objects.filter(pk__in=ids):
            req, new = RecountRequest.objects.get_or_create(
                ingredient=ingredient, done_at__isnull=True,
                defaults={"store": ingredient.store, "requested_by": user, "shift": Shift.objects.current()})
            if new:
                record(Action.CREATE, actor=user, obj=req, object_type="inventory.RecountRequest",
                       after={"nguyen_lieu": ingredient.name})
            created.append(ingredient.name)
        return {"ingredients": created}

    return run_once(operation_key, "recount_request", {"ingredients": ids}, action, actor=user)


def _close_recounts(count, actor):
    from .models import RecountRequest

    for req in RecountRequest.objects.filter(ingredient_id=count.ingredient_id, done_at__isnull=True):
        req.count, req.done_at = count, timezone.now()
        req.save(update_fields=["count", "done_at", "updated_at"])
        record(Action.STATUS_CHANGE, actor=actor, obj=req, object_type="inventory.RecountRequest",
               after={"da_kiem_ke": str(count.counted)})
