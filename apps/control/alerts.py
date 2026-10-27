"""Trung tâm cảnh báo và phân công xử lý (FR-51, BRU-36, Bảng 5.4, NFR-23).

Mỗi loại cảnh báo có một hàm thu thập các đối tượng đang thỏa điều kiện kích hoạt. Tác vụ định kỳ
`sync(now)` so với các cảnh báo đang mở:
- đối tượng mới thỏa điều kiện: tạo cảnh báo, giao người xử lý chính, đặt thời hạn;
- điều kiện không còn: tự đóng kèm ghi chú tự động;
- quá hạn: chuyển cấp lên Chủ quán, hoặc nhắc lại nếu Chủ quán là người xử lý chính.
Mỗi đối tượng có tối đa một cảnh báo đang mở cho cùng một loại. Đóng tay phải có ghi chú; đối tượng
đã được đóng tay thì không tự mở lại. Vì vậy khóa đối tượng phải phân biệt từng lần phát sinh: cảnh báo Cần đặt hàng
khóa theo nguyên liệu và đợt rủi ro (mục 8.4 thiết kế mua nguyên liệu), nên khi tồn đã lên lại rồi xuống, đợt mới có
cảnh báo mới dù cảnh báo đợt cũ đã đóng tay.
Cảnh báo mức Thông tin (Sắp hết, khung giờ quá tải) không tạo ở đây; chúng hiện ở bảng điều khiển và báo cáo.
"""

from datetime import datetime, time, timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Role
from apps.audit.models import Action
from apps.audit.services import record
from apps.core import params
from apps.core.models import Store

from .models import Alert, ExceptionCase

OWNER, BARISTA = Role.CHU_QUAN, Role.PHA_CHE


def _end_of_day(day):
    return timezone.make_aware(datetime.combine(day, time.max))


def _out_of_stock(now):
    from apps.inventory.models import QuickReport
    from apps.inventory.operations import in_opening_hours

    for r in QuickReport.objects.filter(level=QuickReport.Level.OUT, acknowledged_at__isnull=True).select_related("ingredient"):
        if not in_opening_hours(r.created_at):
            continue
        yield {"subject": f"bao-het-{r.pk}", "title": f"{r.ingredient.name} đã hết",
               "detail": f"Báo bởi {r.reporter} lúc {timezone.localtime(r.created_at):%H:%M}. Báo nhân viên ngừng nhận "
                         f"món bị ảnh hưởng hoặc mua bổ sung, ghi kết quả.",
               "assignee": None, "role": OWNER, "severity": Alert.Severity.URGENT,
               "due": r.created_at + timedelta(minutes=params.get("alert_out_of_stock_minutes")),
               "link": "/kho/", "escalate": True}


def _backup_pending(now):
    from apps.orders import backup
    from apps.orders.models import BackupSlip, BackupSlipRange

    for slip in BackupSlip.objects.filter(status=BackupSlip.Status.PENDING):
        yield {"subject": f"pdp-xn-{slip.pk}", "title": f"{slip} chờ Chủ quán xác nhận giá hoặc định mức",
               "detail": "; ".join(m["text"] for m in slip.missing), "assignee": None, "role": OWNER,
               "severity": Alert.Severity.IMPORTANT, "due": slip.created_at + timedelta(hours=params.get("backup_entry_hours")),
               "link": "/du-phong/", "escalate": False}

    for rng in BackupSlipRange.objects.select_related("shift"):
        missing = backup.unprocessed_numbers(rng)
        if missing:
            yield {"subject": f"pdp-{rng.pk}", "title": f"Phiếu dự phòng chưa nhập bù: {', '.join(backup.fmt(n) for n in missing)}",
                   "detail": "Nhập bù hoặc khai báo phiếu hủy có lý do.", "assignee": None, "role": OWNER,
                   "severity": Alert.Severity.IMPORTANT,
                   "due": now + timedelta(hours=params.get("backup_entry_hours")), "link": "/du-phong/", "escalate": True}


def _late_data(now):
    from apps.shifts.models import Shift
    from apps.shifts.services import data_status

    for shift in Shift.objects.filter(ends_at__gte=now - timedelta(days=30), ends_at__lt=now).select_related("approver"):
        status = data_status(shift, now)
        if status["overdue"]:
            hours = params.get("shift_report_hours", at=shift.ends_at)
            yield {"subject": f"ca-{shift.pk}", "title": f"Dữ liệu ca trễ hạn: {shift}",
                   "detail": "; ".join(status["issues"]) + ". Gửi báo cáo cuối ca hoặc hoàn tất dữ liệu ca.",
                   "assignee": None, "role": OWNER, "severity": Alert.Severity.IMPORTANT,
                   "due": status["deadline"] + timedelta(hours=hours), "link": f"/ca/{shift.pk}/", "escalate": True}


def _discrepancy(now):
    from apps.shifts.models import Discrepancy

    for d in Discrepancy.objects.current().filter(over_threshold=True, decision="").select_related("shift", "manager"):
        if not d.explanation:
            yield {"subject": f"cl-{d.pk}", "title": f"Chênh lệch vượt ngưỡng chờ giải trình: {d}",
                   "detail": "Người lập báo cáo cuối ca hoặc Chủ quán ghi giải trình, sau đó Chủ quán chọn Chấp nhận hoặc Không chấp nhận.",
                   "assignee": None, "role": OWNER, "severity": Alert.Severity.IMPORTANT,
                   "due": d.created_at + timedelta(hours=params.get("discrepancy_explain_hours")),
                   "link": f"/ca/{d.shift_id}/", "escalate": True}
        else:
            yield {"subject": f"cl-{d.pk}", "title": f"Chênh lệch chờ Chủ quán quyết định: {d}",
                   "detail": f"Giải trình: {d.explanation}", "assignee": None, "role": OWNER,
                   "severity": Alert.Severity.IMPORTANT,
                   "due": d.explained_at + timedelta(days=params.get("discrepancy_decide_days")),
                   "link": "/ca/tinh-trang/", "escalate": False}


def _exceptions(now):
    for exc in ExceptionCase.objects.filter(status=ExceptionCase.Status.OPEN).select_related("order", "ingredient"):
        if exc.kind == ExceptionCase.Kind.CONSUMPTION_OVER:
            yield {"subject": f"nl-{exc.pk}", "title": f"Kiểm tra chênh lệch tiêu hao: {exc.ingredient}",
                   "detail": exc.detail, "assignee": None, "role": OWNER, "severity": Alert.Severity.IMPORTANT,
                   "due": exc.created_at + timedelta(hours=params.get("consumption_check_hours")),
                   "link": f"/kiem-soat/ngoai-le/{exc.pk}/", "escalate": True}
        else:
            # Ghi rõ đơn và nội dung (ví dụ "Đơn 2710-001 · Hủy hóa đơn đã thanh toán 50.000 đ · duyệt bởi Lâm");
            # quy tắc chỉ ghi thêm khi khác tên loại đã có ở tiêu đề.
            parts = [exc.rule if exc.rule != exc.get_kind_display() else "",
                     f"Đơn {exc.order.code}" if exc.order_id else "",
                     (exc.detail.strip().splitlines() or [""])[-1]]  # ngoại lệ gộp nhiều lần: lấy lần mới nhất
            yield {"subject": f"nl-{exc.pk}", "title": f"Ngoại lệ chờ xem xét: {exc.get_kind_display()}",
                   "detail": " · ".join(p for p in parts if p) or exc.rule, "assignee": None, "role": OWNER,
                   "severity": Alert.Severity.IMPORTANT,
                   "due": exc.created_at + timedelta(days=params.get("review_reminder_days")),
                   "link": f"/kiem-soat/ngoai-le/{exc.pk}/", "escalate": False}


def _inventory_owner(now):
    from apps.inventory.models import Payable, PurchaseOrder, StockCount
    from apps.inventory.stock import fmt_vn

    for po in PurchaseOrder.objects.exclude(status=PurchaseOrder.Status.DELIVERED).select_related("ingredient", "supplier"):
        if po.current_status == PurchaseOrder.Status.LATE:
            yield {"subject": f"giao-cham-{po.pk}", "title": f"Giao chậm: {po}",
                   "detail": "Liên hệ nhà cung cấp, cập nhật ngày giao mới hoặc đặt nơi khác.", "assignee": None,
                   "role": OWNER, "severity": Alert.Severity.IMPORTANT,
                   "due": _end_of_day(po.expected_date) + timedelta(days=params.get("purchase_late_days")),
                   "link": "/kho/dat-hang/", "escalate": False, "kind": Alert.Kind.PURCHASE_LATE}
    for c in StockCount.objects.filter(status=StockCount.Status.PENDING).select_related("ingredient"):
        yield {"subject": f"kiem-ke-{c.pk}", "title": f"Chênh lệch kiểm kê chờ xác nhận: {c.ingredient.name} lệch {fmt_vn(c.percent, 1)}%",
               "detail": c.reason, "assignee": None, "role": OWNER, "severity": Alert.Severity.IMPORTANT,
               "due": c.created_at + timedelta(days=params.get("count_confirm_days")), "link": "/kho/kiem-ke/",
               "escalate": False, "kind": Alert.Kind.COUNT_PENDING}
    for p in Payable.objects.filter(due_date__lte=timezone.localdate(now)).select_related("supplier", "receipt"):
        if not p.is_paid:
            yield {"subject": f"phai-tra-{p.pk}", "title": f"Khoản phải trả đến hạn: {p.supplier} · phiếu {p.receipt.code}",
                   "detail": f"Còn {p.remaining():,} đ.".replace(",", "."), "assignee": None, "role": OWNER,
                   "severity": Alert.Severity.IMPORTANT, "due": _end_of_day(p.due_date), "link": "/kho/phai-tra/",
                   "escalate": False, "kind": Alert.Kind.PAYABLE_DUE}


def _recount(now):
    from apps.inventory.models import RecountRequest

    for req in RecountRequest.objects.filter(done_at__isnull=True).select_related("ingredient", "shift"):
        due = req.shift.ends_at if req.shift else req.created_at + timedelta(hours=2)
        yield {"subject": f"kk-lai-{req.pk}", "title": f"Kiểm kê lại {req.ingredient.name}",
               "detail": f"{req.requested_by} báo đơn bị từ chối vì thiếu nhưng quầy cho là còn hàng. "
                         f"Kiểm kê lại nguyên liệu này và ghi kết quả.",
               "assignee": None, "role": BARISTA, "severity": Alert.Severity.IMPORTANT, "due": due,
               "link": "/kho/kiem-ke/", "escalate": True, "escalate_to": OWNER, "escalate_user": None}


def _late_count(now):
    from apps.shifts.models import Shift
    from apps.shifts.services import critical_count_status

    seen = set()
    for shift in Shift.objects.filter(ends_at__gte=now - timedelta(days=30), ends_at__lt=now).order_by("-ends_at"):
        day = timezone.localtime(shift.starts_at).date()
        if day in seen:
            continue
        seen.add(day)
        st = critical_count_status(day, now)
        if st["missing"] and now > st["deadline"]:
            yield {"subject": f"kk-tre-{day:%Y%m%d}", "title": f"Thiếu kiểm kê nhóm trọng yếu ngày {day:%d/%m}",
                   "detail": "Chưa kiểm kê: " + ", ".join(st["missing"]) + ". Kiểm kê và ghi kết quả.",
                   "assignee": None, "role": BARISTA, "severity": Alert.Severity.IMPORTANT,
                   "due": st["deadline"] + timedelta(hours=params.get("shift_report_hours")),
                   "link": "/kho/kiem-ke/", "escalate": True}


def _order_needed(now):
    """FR-29, mục 9.3 thiết kế mua nguyên liệu: ngày phải đặt chậm nhất là hôm nay hoặc đã qua; tự đóng khi đã có đơn
    Nháp hoặc đơn đặt che được rủi ro. Đơn Nháp tới ngày phải đặt mà chưa báo nhà cung cấp cũng được nhắc."""
    from apps.forecast.planning import alert_items

    for item in alert_items(timezone.localdate(now)):
        ing = item["ingredient"]
        title = (f"Đơn nháp chưa báo nhà cung cấp: {ing.name}" if item["episode"].startswith("nhap-")
                 else f"Cần đặt hàng: {ing.name}")
        yield {"subject": f"dat-{ing.pk}-{item['episode']}"[:60], "title": title, "detail": item["detail"],
               "assignee": None, "role": OWNER, "severity": Alert.Severity.IMPORTANT,
               "due": _end_of_day(max(item["order_by"], timezone.localdate(now))),
               "link": f"/du-bao/ke-hoach-mua/{ing.pk}/", "escalate": False, "kind": Alert.Kind.ORDER_NEEDED}


def _lots_expired(now):
    """Lô đã quá hạn mà vẫn còn hàng trong kho: pha chế để riêng và hủy lô (ghi hao hụt Hết hạn) trong ngày.

    Tự đóng khi lô được hủy hoặc dùng hết. Khóa theo lô nên mỗi lô quá hạn có một cảnh báo riêng."""
    from apps.inventory.models import StockLot

    today = timezone.localdate(now)
    for lot in (StockLot.objects.filter(remaining__gt=0, expiry_date__lt=today)
                .select_related("ingredient").order_by("expiry_date")):
        unit = lot.ingredient.get_unit_display()
        yield {"subject": f"lo-qua-han-{lot.pk}", "title": f"Lô {lot.code} ({lot.ingredient.name}) đã quá hạn",
               "detail": f"Hạn {lot.expiry_date:%d/%m/%Y}, còn {lot.remaining.normalize():f} {unit}. Để riêng, không "
                         f"dùng pha chế; hủy lô ở Phiếu lấy hàng để sổ kho khớp thực tế.",
               "assignee": None, "role": BARISTA, "severity": Alert.Severity.IMPORTANT,
               "due": _end_of_day(today), "link": "/kho/lay-hang/", "escalate": True, "escalate_to": OWNER,
               "escalate_user": None}


COLLECTORS = [
    (Alert.Kind.OUT_OF_STOCK, _out_of_stock),
    (Alert.Kind.BACKUP_PENDING, _backup_pending),
    (Alert.Kind.LATE_DATA, _late_data),
    (Alert.Kind.DISCREPANCY, _discrepancy),
    (Alert.Kind.EXCEPTION, _exceptions),
    (None, _inventory_owner),
    (Alert.Kind.ORDER_NEEDED, _order_needed),
    (Alert.Kind.RECOUNT, _recount),
    (Alert.Kind.LATE_COUNT, _late_count),
    (Alert.Kind.LOT_EXPIRED, _lots_expired),
]


@transaction.atomic
def sync(now=None):
    now = now or timezone.now()
    created, closed, escalated = [], [], []
    active = {}
    for kind, collector in COLLECTORS:
        for item in collector(now):
            active[(item.pop("kind", kind), item["subject"])] = item
    escalation = {key: (item.pop("escalate_to", None), item.pop("escalate_user", None)) for key, item in active.items()}
    open_alerts = {(a.kind, a.subject): a for a in Alert.objects.select_for_update().filter(status__in=Alert.OPEN)}
    for key, alert in open_alerts.items():
        if key not in active:
            _close(alert, None, "Tự đóng: điều kiện kích hoạt không còn.", auto=True, now=now)
            closed.append(alert.pk)
    manually_closed = set(Alert.objects.filter(status=Alert.Status.CLOSED, auto_closed=False)
                          .values_list("kind", "subject"))
    for key, item in active.items():
        alert = open_alerts.get(key)
        if alert is None:
            if key in manually_closed:
                continue
            alert = Alert.objects.create(
                store=Store.get_default(), kind=key[0], subject=key[1], title=item["title"][:200],
                detail=item["detail"][:1000], severity=item["severity"], assignee=item["assignee"],
                assignee_role=item["role"], due_at=item["due"], link=item["link"], can_escalate=item["escalate"])
            record(Action.CREATE, obj=alert, object_type="control.Alert", actor_label="hệ thống",
                   after={"loai": alert.get_kind_display(), "giao": alert.handler_label(),
                          "han": timezone.localtime(alert.due_at).isoformat()})
            created.append(alert.pk)
            _push(alert)
            continue
        if alert.level == 0 and not alert.escalated_at and (
                alert.assignee_id != getattr(item["assignee"], "pk", None) or alert.assignee_role != item["role"]):
            # Chuyển bước (ví dụ: đã giải trình, chuyển Chủ quán quyết định).
            alert.assignee, alert.assignee_role, alert.due_at = item["assignee"], item["role"], item["due"]
            alert.title, alert.detail = item["title"][:200], item["detail"][:1000]
            alert.save(update_fields=["assignee", "assignee_role", "due_at", "title", "detail", "updated_at"])
        elif alert.detail != item["detail"][:1000]:  # nội dung đổi (thêm mã đơn, số liệu mới) thì cập nhật cho đúng
            alert.detail = item["detail"][:1000]
            alert.save(update_fields=["detail", "updated_at"])
    for alert in Alert.objects.select_for_update().filter(status__in=Alert.OPEN, due_at__lt=now):
        _escalate(alert, now, *escalation.get((alert.kind, alert.subject), (None, None)))
        escalated.append(alert.pk)
    return {"tao": created, "dong": closed, "chuyen_cap": escalated}


def _escalate(alert, now, escalate_to=None, escalate_user=None):
    if escalate_to and alert.assignee_role != escalate_to and alert.level == 0:
        # Việc giao Pha chế (ví dụ kiểm kê lại) quá hạn thì chuyển Chủ quán.
        alert.assignee_role, alert.assignee, alert.escalated_at = escalate_to, escalate_user, now
        alert.due_at = now + timedelta(hours=1)
        alert.save(update_fields=["assignee_role", "assignee", "escalated_at", "due_at", "updated_at"])
        record(Action.STATUS_CHANGE, obj=alert, object_type="control.Alert", actor_label="hệ thống",
               after={"cap": alert.handler_label()}, reason="Quá hạn: chuyển cấp đến Chủ quán")
        _push(alert)
        return
    if alert.can_escalate and alert.level == 0 and alert.assignee_role != OWNER:
        alert.level, alert.escalated_at = 1, now
        reason = "Quá hạn: chuyển cấp đến Chủ quán"
    else:
        alert.reminded_count += 1
        reason = "Quá hạn: nhắc lại người xử lý"
    alert.due_at = now + timedelta(days=1)  # nhắc lại hằng ngày nếu vẫn chưa xử lý
    alert.save(update_fields=["level", "escalated_at", "reminded_count", "due_at", "updated_at"])
    record(Action.STATUS_CHANGE, obj=alert, object_type="control.Alert", actor_label="hệ thống",
           after={"cap": "Chủ quán" if alert.level else alert.handler_label(), "nhac_lai": alert.reminded_count},
           reason=reason)
    _push(alert)


def _push(alert):
    """Gửi thông báo đẩy khi giao hoặc chuyển cấp; lỗi gửi không làm hỏng việc ghi cảnh báo."""
    try:
        from apps.core.push import notify_alert

        notify_alert(alert)
    except Exception:  # noqa: BLE001
        pass


def _close(alert, user, note, auto=False, now=None):
    now = now or timezone.now()
    alert.status, alert.closed_at, alert.closed_by = Alert.Status.CLOSED, now, user
    alert.close_note, alert.auto_closed = note[:255], auto
    alert.save(update_fields=["status", "closed_at", "closed_by", "close_note", "auto_closed", "updated_at"])
    record(Action.STATUS_CHANGE, actor=user, obj=alert, object_type="control.Alert",
           actor_label=None if user else "hệ thống",
           after={"trang_thai": "Đã đóng", "thoi_gian_xu_ly_phut": round(alert.handling_minutes or 0)}, reason=note)


def visible_to(user):
    """Người xử lý chính, hoặc Chủ quán với mục Chủ quán là người xử lý chính hoặc đã được chuyển cấp (AC-103)."""
    from django.db.models import Q

    q = Q(assignee=user)
    for role in (BARISTA,):
        if user.has_role(role):
            q |= Q(assignee__isnull=True, assignee_role=role)
    if user.is_owner:
        q |= Q(assignee_role=OWNER) | Q(level=1)
    return Alert.objects.filter(q)


@transaction.atomic
def take(user, alert_id):
    alert = visible_to(user).select_for_update().get(pk=alert_id)
    if alert.status == Alert.Status.NEW:
        alert.status, alert.taken_by, alert.taken_at = Alert.Status.IN_PROGRESS, user, timezone.now()
        alert.save(update_fields=["status", "taken_by", "taken_at", "updated_at"])
        record(Action.STATUS_CHANGE, actor=user, obj=alert, object_type="control.Alert", after={"trang_thai": "Đang xử lý"})
    return alert


@transaction.atomic
def close(user, alert_id, note):
    alert = visible_to(user).select_for_update().get(pk=alert_id)
    if alert.status == Alert.Status.CLOSED:
        return alert
    if not str(note or "").strip():
        raise ValidationError("Ghi kết quả xử lý trước khi đóng cảnh báo.")
    _close(alert, user, note.strip())
    return alert


def weekly_stats(now=None):
    """Thống kê tuần theo NFR-23: số cảnh báo đến Chủ quán, số bị chuyển cấp, thời gian xử lý trung bình."""
    now = now or timezone.now()
    week = Alert.objects.filter(created_at__gte=now - timedelta(days=7))
    closed = [a.handling_minutes for a in week.filter(status=Alert.Status.CLOSED) if a.handling_minutes is not None]
    return {"total": week.count(), "to_owner": week.filter(assignee_role=OWNER).count() + week.filter(level=1).count(),
            "escalated": week.filter(level=1).count(),
            "avg_minutes": round(sum(closed) / len(closed)) if closed else None}
