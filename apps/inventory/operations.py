"""Nguyên vật liệu vận hành: báo nhanh, phiếu nhập, khoản phải trả, kiểm kê, hao hụt, thiếu nguyên liệu,
đặt hàng (FR-23 đến FR-27, FR-30, BRU-19, BRU-23, BRU-25, BRU-26, BRU-33)."""

from datetime import date, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.audit.models import Action
from apps.audit.services import record
from apps.core import numbers, params, uploads
from apps.core.idempotency import run_once

from . import consumption, stock
from .models import (Ingredient, Payable, PurchaseOrder, QuickReport, Receipt, ReceiptLine, ShortageCase,
                     StockCount, StockLot, StockMovement, Supplier, SupplierPayment, Waste)


MAX_NUMBER = numbers.MAX_NUMBER
_vnd = numbers.vnd
_dec = numbers.qty


def _plan_changed(ingredient_id):
    """Đơn đặt thay đổi: tính lại kế hoạch mua của nguyên liệu sau khi giao dịch ghi xong (mục 8.4)."""
    from apps.forecast.planning import schedule_recompute

    schedule_recompute(ingredient_id)


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
        if level == QuickReport.Level.OUT:
            from apps.accounts.models import User
            from apps.core.push import notify_later

            # Hết hàng giữa giờ bán thì Chủ quán cần biết ngay để mua thêm hoặc báo ngừng món.
            notify_later([u.pk for u in User.objects.filter(is_active=True) if u.is_owner and u.pk != user.pk],
                         f"Đã hết {ingredient.name}", f"{user} báo lúc {timezone.localtime():%H:%M}.", "/kho/")
            if in_opening_hours():
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

def create_purchase_order(user, supplier_id, ingredient_id, quantity, expected_date, note="", *, operation_key,
                          status=PurchaseOrder.Status.ORDERED, order_by=None, on_created=None, extra_payload=None):
    """Ghi một lần đặt. `on_created(po)` chạy trong cùng thao tác chạy một lần, nên gửi lại cùng mã chỉ trả về đơn đã
    tạo, không lưu thêm bản ghi kèm theo (ví dụ đề xuất đặt hàng)."""
    payload = {"supplier": int(supplier_id), "ingredient": int(ingredient_id), "quantity": str(quantity),
               "date": str(expected_date), "note": note, **(extra_payload or {})}
    if status != PurchaseOrder.Status.ORDERED:
        payload["status"] = status

    def action():
        supplier = Supplier.objects.get(pk=payload["supplier"])
        ingredient = Ingredient.objects.get(pk=payload["ingredient"])
        po = PurchaseOrder.objects.create(store=ingredient.store, supplier=supplier, ingredient=ingredient,
                                          quantity=_dec(quantity, "Số lượng"), expected_date=expected_date, note=note,
                                          created_by=user, status=status, order_by=order_by,
                                          ordered_at=timezone.now() if status == PurchaseOrder.Status.ORDERED else None)
        record(Action.CREATE, actor=user, obj=po, object_type="inventory.PurchaseOrder",
               after={"nha_cung_cap": supplier.name, "nguyen_lieu": ingredient.name, "so_luong": str(po.quantity),
                      "ngay_giao": expected_date, "trang_thai": po.get_status_display()})
        if on_created is not None:
            on_created(po)
        _plan_changed(ingredient.pk)
        return {"po": po.pk}

    result, _ = run_once(operation_key, "purchase_order", payload, action, actor=user)
    return PurchaseOrder.objects.get(pk=result["po"])


def delivery_date(raw):
    """Ngày giao dự kiến gõ ở màn Đặt hàng: không trước hôm nay, không quá một năm (thường là gõ nhầm năm)."""
    try:
        day = date.fromisoformat(str(raw or ""))
    except ValueError:
        raise ValidationError("Chọn ngày giao dự kiến.")
    today = timezone.localdate()
    if day < today:
        raise ValidationError("Ngày giao không được trước hôm nay.")
    if day > today + timedelta(days=365):
        raise ValidationError(f"Ngày giao {day:%d/%m/%Y} cách hôm nay hơn một năm; kiểm tra lại năm.")
    return day


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
    if po.status in (PurchaseOrder.Status.DELIVERED, PurchaseOrder.Status.CANCELLED):
        raise ValidationError(f"Lần đặt này {po.get_status_display().lower()}; không đổi ngày giao.")
    if new_date < timezone.localdate():
        raise ValidationError("Ngày giao mới không được trước hôm nay.")
    before = po.expected_date
    po.expected_date = new_date
    po.settle_status()
    po.save(update_fields=["expected_date", "status", "updated_at"])
    record(Action.UPDATE, actor=user, obj=po, object_type="inventory.PurchaseOrder",
           before={"ngay_giao": before}, after={"ngay_giao": new_date, "trang_thai": po.get_status_display()})
    _plan_changed(po.ingredient_id)
    return po


@transaction.atomic
def mark_ordered(user, po_id, expected_date=None):
    """Đã báo nhà cung cấp: đơn Nháp chuyển sang Đã đặt, ghi thời điểm và ngày giao theo xác nhận (mục 9.2).

    Hệ thống không tự gửi gì cho nhà cung cấp; thao tác này chỉ ghi lại việc Chủ quán đã tự báo."""
    po = PurchaseOrder.objects.select_for_update().get(pk=po_id)
    if po.status != PurchaseOrder.Status.DRAFT:
        if po.status == PurchaseOrder.Status.ORDERED and po.ordered_at:
            return po  # gửi lại cùng thao tác
        raise ValidationError("Chỉ đơn Nháp mới chuyển sang Đã đặt.")
    before = {"trang_thai": po.get_status_display(), "ngay_giao": po.expected_date}
    po.status, po.ordered_at = PurchaseOrder.Status.ORDERED, timezone.now()
    if expected_date:
        po.expected_date = expected_date
    po.settle_status()
    po.save(update_fields=["status", "ordered_at", "expected_date", "updated_at"])
    record(Action.STATUS_CHANGE, actor=user, obj=po, object_type="inventory.PurchaseOrder", before=before,
           after={"trang_thai": po.get_status_display(), "ngay_giao": po.expected_date},
           reason="Chủ quán đã báo nhà cung cấp")
    _plan_changed(po.ingredient_id)
    return po


@transaction.atomic
def cancel_order(user, po_id, reason):
    """Hủy đơn chưa nhận hàng; giữ lại để truy vết, không còn tính là hàng đang về."""
    reason = (reason or "").strip()
    if not reason:
        raise ValidationError("Ghi lý do hủy đơn.")
    po = PurchaseOrder.objects.select_for_update().get(pk=po_id)
    if po.status == PurchaseOrder.Status.CANCELLED:
        return po
    if po.received_quantity > 0 or po.status == PurchaseOrder.Status.DELIVERED:
        raise ValidationError("Đơn đã nhận hàng không hủy được.")
    before = po.get_status_display()
    po.status = PurchaseOrder.Status.CANCELLED
    po.save(update_fields=["status", "updated_at"])
    record(Action.STATUS_CHANGE, actor=user, obj=po, object_type="inventory.PurchaseOrder",
           before={"trang_thai": before}, after={"trang_thai": po.get_status_display()}, reason=reason)
    _plan_changed(po.ingredient_id)
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
    due = 0
    if payment_type == Receipt.PaymentType.LATER:
        try:
            due = numbers.whole(due_days or 0)
        except ValidationError:
            due = -1
        if not 0 <= due <= 365:
            raise ValidationError("Hạn trả sau là số ngày, từ 0 tới 365.")
    payload = {"supplier": int(supplier_id), "lines": lines, "payment": payment_type, "due": due,
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
            price = _vnd(raw.get("unit_price") or 0, f"Đơn giá {ingredient.name}", allow_zero=True)
            po = None
            if raw.get("purchase_order"):
                po = PurchaseOrder.objects.select_for_update().get(pk=raw["purchase_order"], ingredient=ingredient)
                if po.status == PurchaseOrder.Status.CANCELLED:
                    raise ValidationError(f"Lần đặt {ingredient.name} đã hủy; chọn lần đặt khác.")
            expiry = raw.get("expiry_date") or None
            if expiry and isinstance(expiry, str):
                try:
                    expiry = date.fromisoformat(expiry)
                except ValueError:
                    raise ValidationError(f"Hạn sử dụng của {ingredient.name} không hợp lệ.")
            if expiry and expiry < timezone.localdate():
                raise ValidationError(f"Lô {ingredient.name} đã quá hạn ({expiry:%d/%m/%Y}); không nhập hàng quá hạn.")
            stock.check_expiry(expiry, ingredient.name)
            parsed.append((ingredient, qty, price, po, expiry, str(raw.get("supplier_lot") or "").strip()))
        total = sum(int((q * p).to_integral_value()) for _, q, p, _, _, _ in parsed)
        if not invoice_photo:
            # FR-24 và AC-55: phiếu nhập phải có ảnh hóa đơn khi lưu, không phụ thuộc giá trị.
            raise ValidationError("Chụp ảnh hóa đơn hoặc phiếu giao hàng trước khi lưu phiếu nhập.")
        uploads.check_photo(invoice_photo, "Ảnh hóa đơn")
        receipt = Receipt.objects.create(store=supplier.store, code=_next_receipt_code(), supplier=supplier,
                                         payment_type=payment_type, total=total, invoice_photo=invoice_photo or "",
                                         created_by=user, operation_key=operation_key)
        warnings = []
        lot_codes = []
        for n, (ingredient, qty, price, po, expiry, supplier_lot) in enumerate(parsed, start=1):
            last = (ReceiptLine.objects.filter(ingredient=ingredient).order_by("-id")
                    .values_list("unit_price", flat=True).first())
            if last and price and (price > last * 3 or price * 3 < last):  # thường là gõ giá theo kg hay hộp
                warnings.append(f"{ingredient.name}: đơn giá {numbers.fmt(price, 0)} đ/{ingredient.get_unit_display()} "
                                f"khác nhiều so với lần nhập trước ({numbers.fmt(last, 0)} đ); kiểm tra lại.")
            line = ReceiptLine.objects.create(receipt=receipt, ingredient=ingredient, quantity=qty, unit_price=price,
                                              purchase_order=po, expiry_date=expiry)
            movement = stock.move(ingredient.pk, qty, kind=StockMovement.Kind.RECEIPT, actor=user, store=supplier.store,
                                  source_type="phieu_nhap", source_id=receipt.code, note=supplier.name,
                                  lot={"code": f"{receipt.code}/{n}", "supplier_lot": supplier_lot,
                                       "expiry_date": expiry, "unit_cost": price, "receipt_line": line,
                                       "supplier": supplier})
            lot_codes.append(movement.lot_draws.first().lot.code)
            if po is not None:
                if po.status == PurchaseOrder.Status.DRAFT:
                    po.status, po.ordered_at = PurchaseOrder.Status.ORDERED, po.ordered_at or timezone.now()
                po.received_quantity += qty
                po.settle_status()
                po.save(update_fields=["received_quantity", "status", "ordered_at", "updated_at"])  # AC-52, AC-69
                if po.over_received > 0:  # vẫn ghi nhận, nhưng báo để Chủ quán biết (mục 8.1)
                    warnings.append(f"{ingredient.name}: nhận vượt số đặt {stock.fmt_vn(po.over_received)} "
                                    f"{ingredient.get_unit_display()}.")
        today = timezone.localdate()
        payable = Payable.objects.create(store=supplier.store, receipt=receipt, supplier=supplier, amount=total,
                                         due_date=today + timedelta(days=payload["due"] if payment_type == "tra_sau" else 0))
        if payment_type == Receipt.PaymentType.NOW and total:
            SupplierPayment.objects.create(payable=payable, amount=total, paid_on=today, source=paid_source, actor=user)
            if paid_source == SupplierPayment.Source.SHIFT_CASH:
                shift = Shift.objects.operating()
                if shift is None:
                    raise ValidationError("Không có ca đang mở để chi tiền mặt quỹ ca.")
                from apps.shifts.services import check_cash_on_hand

                check_cash_on_hand(shift, total, "trả phiếu nhập")
                CashEntry.objects.create(store=shift.store, shift=shift, kind=CashEntry.Kind.EXPENSE, amount=total,
                                         category=ExpenseCategory.MATERIALS, note=f"Phiếu nhập {receipt.code}",
                                         actor=user, operation_key=f"{operation_key[:56]}-quyca")
        record(Action.CREATE, actor=user, obj=receipt, object_type="inventory.Receipt",
               after={"ma": receipt.code, "nha_cung_cap": supplier.name, "gia_tri": total,
                      "thanh_toan": receipt.get_payment_type_display(),
                      "dong": [f"{q} {i.get_unit_display()} {i.name} × {p}" for i, q, p, _, _, _ in parsed],
                      "lo": lot_codes, "canh_bao": warnings})
        return {"receipt": receipt.pk, "code": receipt.code, "total": total, "warnings": warnings, "lots": lot_codes}

    return run_once(operation_key, "receipt", payload, action, actor=user)


def pay_supplier(user, payable_id, amount, source, paid_on=None, *, operation_key):
    """Chủ quán ghi thanh toán khoản phải trả; trả một phần thì phần còn lại vẫn phải trả (AC-54)."""
    if not user.is_owner:
        raise ValidationError("Chỉ Chủ quán ghi thanh toán khoản phải trả.")
    payload = {"payable": int(payable_id), "amount": str(amount), "source": source, "paid_on": str(paid_on or "")}

    def action():
        from apps.shifts.models import CashEntry, ExpenseCategory, Shift

        payable = Payable.objects.select_for_update().select_related("receipt").get(pk=payload["payable"])
        value = _vnd(amount, "Số tiền")
        if value > payable.remaining():
            raise ValidationError(f"Số tiền vượt phần còn phải trả ({payable.remaining():,} đ).".replace(",", "."))
        if source not in SupplierPayment.Source.values:
            raise ValidationError("Chọn nguồn tiền.")
        payment = SupplierPayment.objects.create(payable=payable, amount=value,
                                                 paid_on=paid_on or timezone.localdate(), source=source, actor=user)
        if source == SupplierPayment.Source.SHIFT_CASH:  # tiền lấy từ két thì quỹ ca phải ghi khoản chi tương ứng
            shift = Shift.objects.operating()
            if shift is None:
                raise ValidationError("Không có ca đang mở để chi tiền mặt quỹ ca; chọn nguồn tiền khác.")
            from apps.shifts.services import check_cash_on_hand

            check_cash_on_hand(shift, value, "trả nhà cung cấp")
            CashEntry.objects.create(store=shift.store, shift=shift, kind=CashEntry.Kind.EXPENSE, amount=value,
                                     category=ExpenseCategory.MATERIALS,
                                     note=f"Trả {payable.supplier} phiếu {payable.receipt.code}",
                                     actor=user, operation_key=f"{operation_key[:56]}-quyca")
        record(Action.CREATE, actor=user, obj=payable, object_type="inventory.Payable",
               after={"da_tra": value, "con_lai": payable.remaining(), "nguon": payment.get_source_display()})
        return {"payment": payment.pk}

    result, _ = run_once(operation_key, "supplier_payment", payload, action, actor=user)
    return SupplierPayment.objects.get(pk=result["payment"])


def overdue_payables(today=None):
    today = today or timezone.localdate()
    return [p for p in Payable.objects.filter(due_date__lt=today).select_related("supplier", "receipt") if not p.is_paid]


# ---------------- Hao hụt (FR-26, BRU-19) ----------------

def record_waste(user, operation_key, ingredient_id, quantity, reason, note="", is_one_off=False, lot_id=None):
    """is_one_off: Chủ quán đánh dấu sự cố đơn lẻ, không tính vào tỷ lệ hao hụt thường lệ khi dự báo.

    lot_id: lô bị hao hụt nếu người ghi biết; không chọn thì trừ theo thứ tự lấy lô, riêng lý do Hết hạn trừ lô
    quá hạn trước."""
    payload = {"ingredient": int(ingredient_id), "quantity": str(quantity), "reason": reason, "note": note}
    if is_one_off:
        payload["one_off"] = True
    if lot_id:
        payload["lot"] = int(lot_id)

    def action():
        ingredient = Ingredient.objects.get(pk=payload["ingredient"])
        if reason not in Waste.Reason.values:
            raise ValidationError("Chọn lý do hao hụt.")  # AC-59
        qty = _dec(quantity, "Số lượng")
        lot = None
        if payload.get("lot"):
            lot = StockLot.objects.filter(pk=payload["lot"], ingredient=ingredient).first()
            if lot is None:
                raise ValidationError("Lô đã chọn không thuộc nguyên liệu này.")
            if qty > lot.remaining:
                raise ValidationError(f"Lô {lot.code} chỉ còn {stock.fmt_vn(lot.remaining)} "
                                      f"{ingredient.get_unit_display()}.")
        physical = stock._lock([ingredient.pk])[ingredient.pk].physical
        if qty > physical:
            # Không xuất hao hụt quá tồn vật lý trên sổ; sổ sai thì kiểm kê trước rồi ghi hao hụt.
            raise ValidationError(f"Hao hụt {stock.fmt_vn(qty)} {ingredient.get_unit_display()} vượt tồn vật lý "
                                  f"{stock.fmt_vn(max(physical, 0))}; kiểm kê lại trước khi ghi hao hụt.")
        waste = Waste.objects.create(store=ingredient.store, ingredient=ingredient, quantity=qty, reason=reason,
                                     note=note[:255], actor=user, operation_key=operation_key,
                                     is_one_off=bool(is_one_off and user.is_owner))
        movement = stock.move(ingredient.pk, -qty, kind=StockMovement.Kind.WASTE, actor=user, store=ingredient.store,
                              source_type="hao_hut", source_id=waste.pk, note=waste.get_reason_display(),
                              prefer_lot=lot.pk if lot else None,
                              expired_first=lot is None and reason == Waste.Reason.EXPIRED)
        lot_codes = [d.lot.code for d in movement.lot_draws.select_related("lot")]
        record(Action.CREATE, actor=user, obj=waste, object_type="inventory.Waste",
               after={"nguyen_lieu": ingredient.name, "so_luong": str(qty), "ly_do": waste.get_reason_display(),
                      "lo": lot_codes})
        return {"waste": waste.pk, "lots": lot_codes}

    return run_once(operation_key, "waste", payload, action, actor=user)


# ---------------- Kiểm kê (FR-25, BRU-25) ----------------

def _apply_count(count, actor):
    # Điều chỉnh theo chênh lệch lúc đếm, giữ nguyên các biến động phát sinh trong lúc chờ xác nhận.
    # Thiếu khi kiểm kê trừ lô quá hạn trước: đó là phần dễ đã bị bỏ đi mà chưa ghi hao hụt.
    stock.move(count.ingredient_id, count.difference, kind=StockMovement.Kind.COUNT, actor=actor, store=count.store,
               source_type="kiem_ke", source_id=count.pk, note=count.reason, expired_first=True)


def submit_count(user, operation_key, ingredient_id, counted, reason=""):
    payload = {"ingredient": int(ingredient_id), "counted": str(counted), "reason": reason}

    def action():
        ingredient = Ingredient.objects.get(pk=payload["ingredient"])
        value = _dec(counted, "Số lượng đếm được", allow_zero=True)
        row = stock._lock([ingredient.pk])[ingredient.pk]
        diff = value - row.physical
        # Tồn sổ sách bằng 0 hoặc âm thì mọi chênh lệch đều coi là 100% (phải qua Chủ quán xác nhận).
        percent = (abs(diff) / row.physical * 100) if row.physical > 0 else (Decimal(100) if diff else Decimal(0))
        limit = params.get("count_threshold_percent")
        over = percent > limit
        if over and not reason.strip():
            raise ValidationError(f"Chênh lệch {stock.fmt_vn(percent, 1)}% vượt ngưỡng; ghi lý do để gửi Chủ quán xác nhận.")  # AC-56
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
    later = later_count(count)
    if approve and later is not None:
        # Lần đếm sau đã tính lại chênh lệch từ tồn lúc đó; điều chỉnh thêm lần cũ là trừ hai lần.
        raise ValidationError(f"{count.ingredient.name} đã được đếm lại lúc {timezone.localtime(later.created_at):%H:%M %d/%m}; "
                              "lần đếm này đã cũ nên chỉ chọn Không xác nhận.")
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


def later_count(count):
    """Lần đếm sau của cùng nguyên liệu (trừ lần Chủ quán không xác nhận), nếu có."""
    return (StockCount.objects.filter(ingredient_id=count.ingredient_id, created_at__gt=count.created_at)
            .exclude(status=StockCount.Status.REJECTED).order_by("created_at").first())


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
                       rule=f"Thiếu kiểm kê tích lũy tháng của {ingredient.name} vượt {stock.fmt_vn(threshold)} "
                            f"{ingredient.get_unit_display()}",
                       detail=f"Tổng thiếu {stock.fmt_vn(total)} {ingredient.get_unit_display()} qua {month.count()} lần "
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
                defaults={"store": ingredient.store, "requested_by": user, "shift": Shift.objects.operating()})
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


# ---------------- Lô hàng ----------------

def dispose_lot(user, operation_key, lot_id, note=""):
    """Hủy phần còn lại của một lô (thường là lô quá hạn): ghi hao hụt lý do Hết hạn, trừ đúng lô đó."""
    lot = StockLot.objects.select_related("ingredient").get(pk=lot_id)
    if lot.remaining <= 0:
        raise ValidationError(f"Lô {lot.code} đã dùng hết.")
    expired = lot.expiry_date is not None and lot.expiry_date < timezone.localdate()
    reason = Waste.Reason.EXPIRED if expired else Waste.Reason.DAMAGED
    if not expired and not str(note or "").strip():
        raise ValidationError(f"Lô {lot.code} chưa quá hạn; ghi lý do hủy.")
    return record_waste(user, operation_key, lot.ingredient_id, lot.remaining, reason,
                        note or f"Hủy lô {lot.code} quá hạn {lot.expiry_date:%d/%m/%Y}", lot_id=lot.pk)


@transaction.atomic
def update_lot(user, lot_id, expiry_date=None, supplier_lot=None):
    """Sửa hạn sử dụng hoặc số lô trên bao bì sau khi xem lại hàng thật; ghi nhật ký trước và sau."""
    lot = StockLot.objects.select_for_update().get(pk=lot_id)
    before = {"han": lot.expiry_date, "han_uoc_tinh": lot.expiry_estimated, "so_lo": lot.supplier_lot}
    if isinstance(expiry_date, str):
        try:
            expiry_date = date.fromisoformat(expiry_date) if expiry_date else None
        except ValueError:
            raise ValidationError("Hạn sử dụng không hợp lệ.")
    stock.check_expiry(expiry_date)
    if expiry_date is not None and expiry_date != lot.expiry_date:
        lot.expiry_date, lot.expiry_estimated = expiry_date, False
    if supplier_lot is not None:
        lot.supplier_lot = supplier_lot.strip()[:40]
    lot.save(update_fields=["expiry_date", "expiry_estimated", "supplier_lot", "updated_at"])
    record(Action.UPDATE, actor=user, obj=lot, object_type="inventory.StockLot", before=before,
           after={"han": lot.expiry_date, "han_uoc_tinh": lot.expiry_estimated, "so_lo": lot.supplier_lot})
    return lot
