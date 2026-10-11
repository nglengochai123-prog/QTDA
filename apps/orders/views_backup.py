"""Màn hình phiếu dự phòng và nhập bù (FR-06). Quản lý ca dùng trên máy tính khi có kết nối lại."""

import uuid

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from apps.accounts.models import User
from apps.accounts.permissions import Cap, capability_required
from apps.catalog.models import ItemSize, Table
from apps.core.idempotency import OperationKeyError

from . import backup
from .models import BackupSlipRange, Payment

LINE_ROWS = 4


def _lines(post):
    lines = []
    for i in range(LINE_ROWS):
        pair, qty = post.get(f"item_{i}", ""), post.get(f"qty_{i}", "")
        if not pair:
            continue
        item_id, size_id = pair.split(":")
        lines.append({"item": item_id, "size": size_id, "quantity": qty or 1, "options": []})
    return lines


@capability_required(Cap.BACKUP_TICKETS)
@require_http_methods(["GET", "POST"])
def backup_slips(request):
    from apps.shifts.models import Shift

    if request.method == "POST":
        p = request.POST
        action = p.get("action")
        try:
            if action == "issue":
                rng = backup.issue_range(request.user, p.get("shift"), p.get("first"), p.get("last"), p.get("receiver"))
                messages.success(request, f"Đã cấp dãy {rng} cho {rng.shift}.")
            elif action == "declare":
                rng = backup.declare_last_used(request.user, p.get("range"), p.get("last_used") or 0)
                messages.success(request, f"Đã khai báo số cuối đã dùng của dãy {rng}.")
            elif action == "void":
                slip = backup.void_slip(request.user, p.get("number"), p.get("reason", ""))
                messages.success(request, f"Đã khai báo hủy {slip}; đã tạo ngoại lệ cho Chủ quán xem xét.")
            else:
                result, repeated = backup.enter_slip(request.user, p.get("operation_key", ""), {
                    "number": p.get("number"), "operation_code": p.get("operation_code"),
                    "sold_at": p.get("sold_at"), "restored_at": p.get("restored_at"), "method": p.get("method"),
                    "transfer_confirmed": p.get("transfer_confirmed") == "1", "table": p.get("table"),
                    "lines": _lines(p)})
                (messages.success if result["ok"] else messages.error)(
                    request, result["message"] + (" (Gửi lại: đã ghi từ trước.)" if repeated else "")
                    + (" Nhập bù quá hạn: đã tạo ngoại lệ." if result.get("late") else ""))
        except (ValidationError, OperationKeyError, ValueError) as error:
            for message in (error.messages if isinstance(error, ValidationError) else [str(error)]):
                messages.error(request, message)
        return redirect("orders:backup_slips")

    ranges = (BackupSlipRange.objects.select_related("shift", "receiver").prefetch_related("slips__order")
              .order_by("-shift__starts_at", "first_number")[:20])
    for rng in ranges:
        rng.missing = [backup.fmt(n) for n in backup.unprocessed_numbers(rng)]
    now = timezone.localtime().strftime("%Y-%m-%dT%H:%M")
    return render(request, "orders/backup_slips.html", {
        "ranges": ranges, "shifts": Shift.objects.filter(status=Shift.Status.OPEN).order_by("starts_at"),
        "users": User.objects.filter(is_active=True).order_by("first_name"),
        "tables": Table.objects.filter(is_active=True), "methods": Payment.Method.choices,
        "sizes": ItemSize.objects.select_related("item").filter(item__status="dang_ban").order_by("item__name", "price"),
        "rows": range(LINE_ROWS), "now": now, "operation_key": uuid.uuid4().hex,
    })
