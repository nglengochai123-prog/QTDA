"""Nhận đơn, giữ nguyên liệu và hoàn thành pha chế (FR-01, FR-02, FR-03, BRU-18, BRU-20, BRU-39, NFR-04)."""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.audit.models import Action
from apps.audit.services import record
from apps.catalog.models import MenuItem, Option, Table
from apps.core.idempotency import run_once
from apps.inventory import stock
from apps.inventory.models import RecipeVersion
from apps.inventory.services import ingredient_usage

from .models import BackupSlip, Order, OrderLine, OrderLineOption

MAX_CUPS_PER_LINE = 50


def _int(value, field):
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ValidationError(f"{field} không hợp lệ.")


def build_lines(payload, at=None, allow_unsellable=False, missing=None, overrides=None):
    """Kiểm tra giỏ món từ màn hình tạo đơn và tính giá, định mức theo dữ liệu hiện hành.

    Nhập bù phiếu dự phòng truyền `at` = thời điểm bán: giá theo lịch sử giá và phiên bản định mức
    có hiệu lực lúc đó (BRU-39). Thiếu dữ liệu lịch sử thì ghi vào `missing` thay vì đoán; `overrides`
    là giá hoặc phiên bản định mức đã được Chủ quán xác nhận cho từng dòng.
    """
    overrides = overrides or {}
    table = Table.objects.filter(pk=_int(payload.get("table"), "Bàn"), is_active=True).first()
    if table is None:
        raise ValidationError("Chọn bàn trước khi gửi đơn.")
    raw_lines = payload.get("lines") or []
    if not raw_lines:
        raise ValidationError("Đơn chưa có món nào.")
    lines = []
    for index, raw in enumerate(raw_lines, start=1):
        items = MenuItem.objects.all() if allow_unsellable else MenuItem.objects.sellable()
        item = items.filter(pk=_int(raw.get("item"), "Món")).first()
        if item is None:
            raise ValidationError(f"Dòng {index}: món không còn mở bán.")
        size = item.active_sizes().filter(pk=_int(raw.get("size"), "Kích cỡ")).first()
        if size is None:
            raise ValidationError(f"Dòng {index}: kích cỡ không hợp lệ cho {item.name}.")
        quantity = _int(raw.get("quantity", 1), "Số ly")
        if not 1 <= quantity <= MAX_CUPS_PER_LINE:
            raise ValidationError(f"Dòng {index}: số ly phải từ 1 đến {MAX_CUPS_PER_LINE}.")
        option_ids = sorted({_int(o, "Tùy chọn") for o in raw.get("options") or []})
        option_pool = (Option.objects.filter(group__in=item.option_groups.all()) if allow_unsellable
                       else item.active_options())
        options = list(option_pool.filter(pk__in=option_ids).select_related("group"))
        if len(options) != len(option_ids):
            raise ValidationError(f"Dòng {index}: có tùy chọn không áp dụng cho {item.name}.")
        for group in item.option_groups.all():
            chosen = [o for o in options if o.group_id == group.pk]
            if group.selection == group.Selection.SINGLE and len(chosen) > 1:
                raise ValidationError(f"Dòng {index}: {group.name} chỉ chọn một.")
            if group.is_required and not chosen:
                raise ValidationError(f"Dòng {index}: chưa chọn {group.name}.")
        version = None
        usage = {}
        fixed = overrides.get(index, {})
        if not item.no_ingredients:
            if fixed.get("version"):
                version = RecipeVersion.objects.published().get(pk=fixed["version"], item=item)
            else:
                version = RecipeVersion.objects.current_for(item, at=at)
            if version is None:
                if missing is None:
                    raise ValidationError(f"Dòng {index}: {item.name} chưa có định mức áp dụng.")
                missing.append({"line": index, "kind": "dinh_muc",
                                "text": f"Dòng {index}: {item.name} chưa có phiên bản định mức hiệu lực tại thời điểm bán"})
            else:
                usage = {str(k): str(v) for k, v in ingredient_usage(version, size, options).items()}
        unit_price = size.price + sum(o.extra_price for o in options)
        if fixed.get("price") is not None:
            unit_price = int(fixed["price"])
        elif at is not None:
            from apps.catalog.models import price_at

            historical = price_at(size, options, at)
            if historical is None:
                if missing is None:
                    raise ValidationError(f"Dòng {index}: thiếu lịch sử giá tại thời điểm bán.")
                missing.append({"line": index, "kind": "gia",
                                "text": f"Dòng {index}: {item.name} {size.name} chưa có lịch sử giá tại thời điểm bán"})
            else:
                unit_price = historical
        lines.append({
            "item": item, "size": size, "options": options, "quantity": quantity,
            "note": str(raw.get("note") or "")[:255], "version": version, "usage": usage,
            "unit_price": unit_price,
        })
    return table, lines


def _totals(lines):
    totals = {}
    for line in lines:
        for ingredient_id, amount in line["usage"].items():
            totals[int(ingredient_id)] = totals.get(int(ingredient_id), Decimal(0)) + Decimal(amount) * line["quantity"]
    return totals


def _next_code(store):
    # Khóa dòng cửa hàng để hai đơn gửi cùng lúc (kể cả đơn không dùng nguyên liệu) không nhận cùng một mã.
    type(store).objects.select_for_update().filter(pk=store.pk).first()
    today = timezone.localdate()
    count = Order.objects.filter(store=store, created_at__date=today).count()
    # Mã không ghi năm nên sang năm sau cùng ngày đã có mã của năm trước: đọc một lần các mã đã dùng rồi chọn số kế
    # tiếp còn trống, thay vì hỏi cơ sở dữ liệu từng mã (năm trước 300 đơn thì mỗi đơn mới hỏi 300 lần).
    used = set(Order.objects.filter(code__startswith=f"{today:%d%m}-").values_list("code", flat=True))
    while True:
        count += 1
        code = f"{today:%d%m}-{count:03d}"
        if code not in used:
            return code


def submit_order(user, operation_key, payload):
    """Nhận đơn và giữ nguyên liệu của cả đơn trong một giao dịch. Thiếu thì không nhận gì.

    `payload["payment"]` = {"mode": "truoc", "method", "transfer_confirmed", "cash_received"} thì thu tiền ngay trong
    cùng giao dịch (prepaid.py): lỗi ở bất kỳ bước nào thì không có đơn, không giữ kho, không có tiền.

    Trả (kết quả, là_lần_lặp). Ném stock.InsufficientStock, ValidationError, prepaid.PrepayDenied hoặc
    OperationKeyError.
    """
    from . import prepaid

    clean_payload = {
        "table": payload.get("table"), "note": str(payload.get("note") or "")[:255],
        "lines": [{"item": l.get("item"), "size": l.get("size"), "options": sorted(l.get("options") or []),
                   "quantity": l.get("quantity", 1), "note": l.get("note") or ""} for l in payload.get("lines") or []],
    }
    spec = prepaid.clean_spec(payload.get("payment"))
    if spec is not None:
        clean_payload["payment"] = spec  # cùng mã mà khác cách thanh toán thì bị từ chối, không trả kết quả cũ

    existing = Order.objects.filter(operation_key=operation_key).select_related("table").first()
    if existing is not None and BackupSlip.objects.filter(order=existing).exists():
        # NFR-16: nháp đã chuyển sang phiếu dự phòng và đã nhập bù thì gửi lại không tạo đơn mới.
        return ({"order_id": existing.pk, "code": existing.code, "table": existing.table.code, "total": existing.total,
                 "message": f"Đơn {existing.code} đã được nhập bù từ phiếu dự phòng."}, True)

    def action():
        table, lines = build_lines(clean_payload)
        if spec is not None:
            problem = prepaid.duty_problem(user)
            if problem:
                raise prepaid.PrepayDenied(problem)  # kiểm tra ở máy chủ, không chỉ ẩn nút trên màn hình
            prepaid.check_spec(spec)
        stock.reserve(_totals(lines))
        from apps.shifts.models import Shift

        order = Order.objects.create(
            store=table.store, code=_next_code(table.store), table=table, note=clean_payload["note"],
            created_by=user, operation_key=operation_key, shift=Shift.objects.operating(),
            total=sum(l["unit_price"] * l["quantity"] for l in lines))
        for position, line in enumerate(lines, start=1):
            order_line = OrderLine.objects.create(
                order=order, position=position, item=line["item"], size=line["size"],
                item_name=line["item"].name, size_name=line["size"].name, unit_price=line["unit_price"],
                quantity=line["quantity"], note=line["note"], recipe_version=line["version"],
                usage_per_unit=line["usage"])
            OrderLineOption.objects.bulk_create([
                OrderLineOption(line=order_line, option=o, name=o.name, extra_price=o.extra_price)
                for o in line["options"]])
        record(Action.CREATE, actor=user, obj=order, object_type="orders.Order",
               after={"code": order.code, "table": table.code, "total": order.total,
                      "lines": [f"{l['quantity']} × {l['item'].name} {l['size'].name}" for l in lines],
                      "thanh_toan": "Thu trước" if spec else "Trả sau"},
               reason="Gửi pha chế")
        result = {"order_id": order.pk, "code": order.code, "table": table.code, "total": order.total}
        if spec is not None:
            result["prepaid"] = prepaid.record_prepayment(user, operation_key, order, spec)
        return result

    try:
        return run_once(operation_key, "order_submit", clean_payload, action, actor=user)
    except stock.InsufficientStock as error:
        # AC-04: báo từng dòng còn đáp ứng bao nhiêu ly với tồn có thể dùng hiện tại.
        error.lines = lines_left(clean_payload)
        raise


def cups_possible(usage, available):
    """Số ly tối đa với lượng nguyên liệu cho một ly `usage` và tồn có thể dùng `available`."""
    if not usage:
        return None
    return max(0, min(int(Decimal(str(available.get(int(i), 0))) // Decimal(str(q))) for i, q in usage.items()))


def lines_left(payload):
    try:
        _, lines = build_lines(payload)
    except ValidationError:
        return []
    available = {k: v[2] for k, v in stock.snapshot_for().items()}
    return [{"name": f"{l['item'].name} {l['size'].name}", "quantity": l["quantity"],
             "left": cups_possible(l["usage"], available)} for l in lines]


def complete_line(user, operation_key, line_id, cups, expected_done):
    """Quầy pha chế xác nhận pha xong `cups` ly của một dòng.

    Trừ tồn vật lý và bỏ phần đang giữ đúng một lần: cùng mã gửi lại trả kết quả cũ; bấm lại
    bằng mã khác nhưng dòng đã thay đổi (expected_done lệch) thì không trừ thêm.
    """
    payload = {"line": int(line_id), "cups": int(cups), "expected_done": int(expected_done)}

    def action():
        line = OrderLine.objects.select_for_update().select_related("order").get(pk=payload["line"])
        if line.done_quantity != payload["expected_done"]:
            return {"line": line.pk, "done": line.done_quantity, "applied": 0,
                    "message": "Dòng này vừa được cập nhật ở nơi khác; không trừ thêm."}
        applied = min(max(payload["cups"], 0), line.pending_quantity)
        if applied == 0:
            return {"line": line.pk, "done": line.done_quantity, "applied": 0, "message": "Dòng này đã pha xong."}
        stock.consume(line.usage_for(applied), actor=user, store=line.order.store,
                      source_type="dong_mon", source_id=line.pk,
                      note=f"Đơn {line.order.code}: {applied} × {line.item_name} {line.size_name}")
        line.done_quantity += applied
        if line.pending_quantity == 0:
            line.status = OrderLine.Status.DONE
            line.done_at = timezone.now()
        line._progress_update = True
        line.save(update_fields=["done_quantity", "status", "done_at", "updated_at"])
        line.order.refresh_status()
        record(Action.STATUS_CHANGE, actor=user, obj=line, object_type="orders.OrderLine",
               before={"done": payload["expected_done"]}, after={"done": line.done_quantity, "so_ly": applied},
               reason=f"Đã pha chế {applied} ly, đơn {line.order.code}")
        return {"line": line.pk, "done": line.done_quantity, "applied": applied, "message": ""}

    return run_once(operation_key, "bar_complete", payload, action, actor=user)


def serve_line(user, operation_key, line_id):
    """Phục vụ xác nhận đã mang món ra bàn (BRU-02: Đã pha chế → Đã phục vụ). Bấm lại không đổi gì."""
    payload = {"line": int(line_id)}

    def action():
        line = OrderLine.objects.select_for_update().select_related("order", "order__table").get(pk=payload["line"])
        if line.status == OrderLine.Status.SERVED:
            return {"line": line.pk, "applied": False, "message": "Món này đã được ghi mang ra."}
        if line.status != OrderLine.Status.DONE:
            raise ValidationError("Món chưa pha xong nên chưa ghi mang ra được.")
        line.status = OrderLine.Status.SERVED
        line.served_at = timezone.now()
        line.served_by = user
        line._progress_update = True
        line.save(update_fields=["status", "served_at", "served_by", "updated_at"])
        line.order.refresh_status()
        record(Action.STATUS_CHANGE, actor=user, obj=line, object_type="orders.OrderLine",
               before={"status": OrderLine.Status.DONE}, after={"status": OrderLine.Status.SERVED},
               reason=f"Đã mang ra bàn {line.order.table.code}, đơn {line.order.code}")
        return {"line": line.pk, "applied": True, "message": ""}

    return run_once(operation_key, "serve_line", payload, action, actor=user)


def ensure_can_pay(order):
    """AC-07: chỉ thanh toán đơn đã phục vụ xong. Phần thanh toán (FR-04) gọi hàm này trước khi ghi tiền."""
    order.refresh_status()
    if order.status != Order.Status.SERVED:
        raise ValidationError(f"Đơn {order.code} đang ở trạng thái {order.get_status_display()}, chưa thanh toán được.")


def ready_lines():
    """Món đã pha xong, chờ phục vụ mang ra (AC-06)."""
    return (OrderLine.objects.filter(status=OrderLine.Status.DONE)
            .select_related("order", "order__table").prefetch_related("options")
            .order_by("done_at"))


def availability(versions=None):
    """Số ly còn đáp ứng theo từng kích cỡ (FR-01), tính từ tồn có thể dùng và định mức hiện hành.

    Trả {size_id: số ly hoặc None nếu món không dùng nguyên liệu}. Chưa tính tùy chọn.
    """
    result = {}
    available = {k: v[2] for k, v in stock.snapshot_for().items()}
    versions = RecipeVersion.objects.current_map() if versions is None else versions
    for item in MenuItem.objects.sellable().prefetch_related("sizes"):
        sizes = [s for s in item.sizes.all() if s.is_active]
        if item.no_ingredients:
            for size in sizes:
                result[size.pk] = None
            continue
        version = versions.get(item.pk)
        for size in sizes:
            usage = ingredient_usage(version, size) if version else {}
            if not usage:
                result[size.pk] = 0
                continue
            result[size.pk] = max(0, min(int(available.get(i, Decimal(0)) // q) for i, q in usage.items()))
    return result


def waiting_lines():
    return (OrderLine.objects.filter(status=OrderLine.Status.WAITING)
            .select_related("order", "order__table").prefetch_related("options")
            .order_by("order__created_at", "position"))
