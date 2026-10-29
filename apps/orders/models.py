"""Đơn hàng và dòng món (FR-01, FR-02, FR-03, FR-10, BRU-39).

Đơn được tạo ở trạng thái Đã gửi pha chế và bị khóa ngay: dòng món không sửa trực tiếp được;
thay đổi về sau đi qua yêu cầu điều chỉnh có phê duyệt (FR-11, phần sau).
"""

from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from apps.catalog.models import ItemSize, MenuItem, Option, Table
from apps.core.models import StoreScopedModel, TimeStampedModel
from apps.inventory.models import RecipeVersion


class Order(StoreScopedModel):
    class Status(models.TextChoices):
        # Vòng đời theo BRU-02: Đã gửi pha chế → Đã pha chế → Đã phục vụ → Đã thanh toán; Đã hủy chỉ qua phê duyệt.
        SENT = "da_gui", "Đã gửi pha chế"
        PREPARED = "da_pha", "Đã pha chế"
        SERVED = "da_phuc_vu", "Đã phục vụ"
        PAID = "da_thanh_toan", "Đã thanh toán"
        CANCELLED = "da_huy", "Đã hủy"

    code = models.CharField("Mã đơn", max_length=20, unique=True)
    table = models.ForeignKey(Table, verbose_name="Bàn", on_delete=models.PROTECT, related_name="orders")
    status = models.CharField("Trạng thái", max_length=20, choices=Status.choices, default=Status.SENT)
    note = models.CharField("Ghi chú đơn", max_length=255, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="Người tạo", on_delete=models.PROTECT,
                                   related_name="+")
    operation_key = models.CharField("Mã nghiệp vụ", max_length=64, unique=True)
    total = models.PositiveIntegerField("Tổng tiền (đồng)", default=0)
    shift = models.ForeignKey("shifts.Shift", verbose_name="Ca", on_delete=models.PROTECT, null=True, blank=True,
                              related_name="orders")
    payment = models.ForeignKey("orders.Payment", verbose_name="Thanh toán", on_delete=models.PROTECT,
                                null=True, blank=True, related_name="orders")
    # Đơn thu trước khi pha chế: tiền đã thu lúc tạo đơn (payment) nhưng đơn còn mở cho đến khi thu ngân giao nước và
    # hoàn tất. Hai mốc dưới chỉ ghi khi hoàn tất đơn thu trước; đơn trả sau đóng bằng thanh toán như cũ.
    completed_at = models.DateTimeField("Hoàn tất lúc", null=True, blank=True)
    completed_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="Người hoàn tất",
                                     on_delete=models.PROTECT, null=True, blank=True, related_name="+")

    class Meta:
        verbose_name = "Đơn hàng"
        verbose_name_plural = "Đơn hàng"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Đơn {self.code} · {self.table}"

    @property
    def is_locked(self):
        return True  # Đơn luôn khóa sau khi gửi (FR-10).

    def derived_status(self):
        """Trạng thái đơn suy ra từ các dòng món (chỉ trước khi thanh toán hoặc hủy)."""
        if self.status in (self.Status.PAID, self.Status.CANCELLED):
            return self.status
        all_statuses = {line.status for line in self.lines.all()}
        statuses = all_statuses - {OrderLine.Status.CANCELLED}
        if not statuses:
            return self.Status.CANCELLED if all_statuses else self.status
        if statuses == {OrderLine.Status.SERVED}:
            return self.Status.SERVED
        if statuses <= {OrderLine.Status.DONE, OrderLine.Status.SERVED}:
            return self.Status.PREPARED
        return self.Status.SENT

    def refresh_status(self):
        new = self.derived_status()
        if new != self.status:
            self.status = new
            self.save(update_fields=["status", "updated_at"])
        return self.status

    def recompute_total(self):
        self.total = sum(line.unit_price * line.billable_quantity for line in self.lines.all())
        self.save(update_fields=["total", "updated_at"])
        return self.total

    def pending_request(self):
        return self.adjustment_requests.filter(status=AdjustmentRequest.Status.PENDING).first()

    @property
    def is_prepaid(self):
        """Đơn đã thu tiền ngay lúc tạo, trước khi pha chế."""
        return self.payment_id is not None and self.payment.kind == Payment.Kind.PREPAID

    @property
    def is_open(self):
        return self.status not in (self.Status.PAID, self.Status.CANCELLED)

    def payment_label(self):
        """Tình trạng tiền, tách khỏi tiến độ pha chế để màn hình hiện riêng hai thứ."""
        if self.payment_id is None:
            return "Đã hủy" if self.status == self.Status.CANCELLED else "Chưa thu tiền"
        if self.is_prepaid:
            return "Đã thu trước" if self.is_open else "Đã thu trước, đã hoàn tất"
        return "Đã thanh toán"

    def progress(self):
        """Tiến độ theo số ly: (đã pha, phải pha, đã mang ra), không tính ly đã hủy."""
        lines = [l for l in self.lines.all() if l.status != OrderLine.Status.CANCELLED]
        made = sum(l.quantity - l.cancelled_quantity for l in lines)
        done = sum(l.done_quantity for l in lines)
        served = sum(l.quantity - l.cancelled_quantity for l in lines if l.status == OrderLine.Status.SERVED)
        return {"done": done, "total": made, "served": served, "waiting": made - done, "to_deliver": made - served}

    def progress_label(self):
        if self.status == self.Status.CANCELLED:
            return "Đã hủy"
        if self.status == self.Status.PAID:
            return "Đã giao, hoàn tất" if self.is_prepaid else "Đã phục vụ"
        p = self.progress()
        if p["waiting"] and p["done"]:
            return f"Đang pha, xong {p['done']}/{p['total']} ly"
        if p["waiting"]:
            return "Chờ pha chế"
        if p["to_deliver"]:
            return "Đã pha xong, chờ giao" if self.is_prepaid else "Đã pha xong, chờ mang ra"
        return "Đã mang ra, chờ hoàn tất" if self.is_prepaid else "Đã phục vụ"


class OrderLine(TimeStampedModel):
    class Status(models.TextChoices):
        WAITING = "cho_pha", "Chờ pha"
        DONE = "da_pha", "Đã pha chế"
        SERVED = "da_phuc_vu", "Đã phục vụ"
        CANCELLED = "da_huy", "Đã hủy"

    order = models.ForeignKey(Order, verbose_name="Đơn", on_delete=models.PROTECT, related_name="lines")
    position = models.PositiveSmallIntegerField("Thứ tự")
    item = models.ForeignKey(MenuItem, verbose_name="Món", on_delete=models.PROTECT, related_name="+")
    size = models.ForeignKey(ItemSize, verbose_name="Kích cỡ", on_delete=models.PROTECT, related_name="+")
    # Ảnh chụp tại lúc nhận đơn: đổi tên, giá, định mức sau đó không ảnh hưởng dòng này (BRU-39, AC-114).
    item_name = models.CharField("Tên món lúc bán", max_length=120)
    size_name = models.CharField("Kích cỡ lúc bán", max_length=20)
    unit_price = models.PositiveIntegerField("Đơn giá lúc bán (đã gồm tùy chọn)")
    quantity = models.PositiveSmallIntegerField("Số ly")
    done_quantity = models.PositiveSmallIntegerField("Số ly đã pha", default=0)
    cancelled_quantity = models.PositiveSmallIntegerField("Số ly hủy khi chưa pha", default=0)
    voided_done_quantity = models.PositiveSmallIntegerField("Số ly hủy sau pha chế", default=0)
    note = models.CharField("Ghi chú", max_length=255, blank=True)
    recipe_version = models.ForeignKey(RecipeVersion, verbose_name="Phiên bản định mức", on_delete=models.PROTECT,
                                       null=True, blank=True, related_name="+")
    usage_per_unit = models.JSONField("Nguyên liệu cho một ly", default=dict,
                                      help_text="{mã nguyên liệu: lượng} theo phiên bản định mức đã lưu.")
    status = models.CharField("Trạng thái", max_length=20, choices=Status.choices, default=Status.WAITING)
    done_at = models.DateTimeField("Pha xong lúc", null=True, blank=True)
    served_at = models.DateTimeField("Mang ra lúc", null=True, blank=True)
    served_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="Người mang ra", on_delete=models.PROTECT,
                                  null=True, blank=True, related_name="+")

    class Meta:
        verbose_name = "Dòng món"
        verbose_name_plural = "Dòng món"
        ordering = ["order", "position"]
        constraints = [
            models.UniqueConstraint(fields=["order", "position"], name="uniq_line_position"),
            models.CheckConstraint(condition=models.Q(quantity__gte=1), name="line_quantity_positive"),
            models.CheckConstraint(
                condition=models.Q(done_quantity__lte=models.F("quantity") - models.F("cancelled_quantity")),
                name="line_done_within_quantity"),
            models.CheckConstraint(condition=models.Q(voided_done_quantity__lte=models.F("done_quantity")),
                                   name="line_voided_within_done"),
        ]

    def __str__(self):
        return f"{self.quantity} × {self.item_name} {self.size_name}"

    @property
    def pending_quantity(self):
        return self.quantity - self.done_quantity - self.cancelled_quantity

    @property
    def billable_quantity(self):
        """Số ly tính tiền: trừ ly hủy trước và sau pha chế."""
        return self.quantity - self.cancelled_quantity - self.voided_done_quantity

    @property
    def line_total(self):
        return self.unit_price * self.billable_quantity

    def settle_status(self):
        """Cập nhật trạng thái dòng sau khi hủy bớt ly."""
        if self.billable_quantity == 0:
            self.status = self.Status.CANCELLED
        elif self.pending_quantity == 0 and self.status == self.Status.WAITING:
            self.status = self.Status.DONE

    def usage_for(self, cups):
        return {int(k): Decimal(str(v)) * cups for k, v in self.usage_per_unit.items()}

    def option_text(self):
        return ", ".join(o.name for o in self.options.all())

    def save(self, *args, **kwargs):
        # Khóa đơn: chỉ được cập nhật tiến độ pha chế, không đổi món, giá, số lượng.
        if self.pk is not None and not getattr(self, "_progress_update", False):
            raise ValidationError("Đơn đã gửi pha chế bị khóa; thay đổi phải qua yêu cầu điều chỉnh.")
        super().save(*args, **kwargs)


class OrderLineOption(models.Model):
    line = models.ForeignKey(OrderLine, verbose_name="Dòng món", on_delete=models.PROTECT, related_name="options")
    option = models.ForeignKey(Option, verbose_name="Tùy chọn", on_delete=models.PROTECT, related_name="+")
    name = models.CharField("Tùy chọn lúc bán", max_length=80)
    extra_price = models.PositiveIntegerField("Giá cộng thêm lúc bán")

    class Meta:
        verbose_name = "Tùy chọn của dòng món"
        verbose_name_plural = "Tùy chọn của dòng món"

    def __str__(self):
        return self.name



class AdjustmentReason(StoreScopedModel):
    """Danh mục lý do điều chỉnh (BRU-08, AC-20)."""

    name = models.CharField("Lý do", max_length=80)
    is_active = models.BooleanField("Đang dùng", default=True)
    sort_order = models.PositiveSmallIntegerField("Thứ tự", default=0)

    class Meta:
        verbose_name = "Lý do điều chỉnh"
        verbose_name_plural = "Lý do điều chỉnh"
        ordering = ["sort_order", "name"]

    def __str__(self):
        return self.name


class AdjustmentRequest(StoreScopedModel):
    """Yêu cầu điều chỉnh đơn đã gửi pha chế (FR-10, FR-11, BRU-08, BRU-09)."""

    class Kind(models.TextChoices):
        CANCEL_ITEMS = "huy_mon", "Hủy món hoặc giảm số lượng"
        CHANGE_ITEM = "doi_mon", "Đổi món"
        MOVE_TABLE = "chuyen_ban", "Chuyển bàn hoặc gộp bàn"
        CANCEL_PAID = "huy_hoa_don", "Hủy hóa đơn đã thanh toán"

    class Status(models.TextChoices):
        PENDING = "cho_duyet", "Chờ duyệt"
        APPROVED = "da_duyet", "Đã duyệt"
        REJECTED = "tu_choi", "Từ chối"
        POST_AUDIT = "cho_hau_kiem", "Chờ hậu kiểm"

    class Level(models.IntegerChoices):
        SHIFT = 0, "Người duyệt trong ca"
        BACKUP = 1, "Người duyệt dự phòng"
        OWNER = 2, "Chủ quán"
        EXHAUSTED = 3, "Quá hạn mọi cấp"

    order = models.ForeignKey(Order, verbose_name="Đơn", on_delete=models.PROTECT, related_name="adjustment_requests")
    kind = models.CharField("Loại", max_length=20, choices=Kind.choices)
    line = models.ForeignKey(OrderLine, verbose_name="Dòng món", on_delete=models.PROTECT, null=True, blank=True,
                             related_name="+")
    cups = models.PositiveSmallIntegerField("Số ly", default=0)
    target_table = models.ForeignKey(Table, verbose_name="Bàn mới", on_delete=models.PROTECT, null=True,
                                     blank=True, related_name="+")
    new_line = models.JSONField("Món thay thế", null=True, blank=True)
    new_line_text = models.CharField("Món thay thế (mô tả)", max_length=200, blank=True)
    reason = models.ForeignKey(AdjustmentReason, verbose_name="Lý do", on_delete=models.PROTECT, related_name="+")
    note = models.CharField("Ghi chú", max_length=255, blank=True)
    status = models.CharField("Trạng thái", max_length=20, choices=Status.choices, default=Status.PENDING)
    level = models.PositiveSmallIntegerField("Cấp đang chờ", choices=Level.choices, default=Level.SHIFT)
    level_since = models.DateTimeField("Ở cấp này từ")
    level_minutes = models.PositiveSmallIntegerField("Thời hạn mỗi cấp lúc tạo (phút)", null=True, blank=True)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="Người yêu cầu",
                                     on_delete=models.PROTECT, related_name="+")
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="Người xử lý", on_delete=models.PROTECT,
                                   null=True, blank=True, related_name="+")
    decided_at = models.DateTimeField("Xử lý lúc", null=True, blank=True)
    decision_note = models.CharField("Ghi chú xử lý", max_length=255, blank=True)
    operation_key = models.CharField("Mã nghiệp vụ", max_length=64, unique=True)
    after_prep = models.BooleanField("Gửi sau khi đã có món pha xong", default=False)
    shift = models.ForeignKey("shifts.Shift", verbose_name="Ca", on_delete=models.PROTECT, null=True, blank=True,
                              related_name="+")

    class Meta:
        verbose_name = "Yêu cầu điều chỉnh"
        verbose_name_plural = "Yêu cầu điều chỉnh"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["order"], condition=models.Q(status="cho_duyet"),
                                    name="one_pending_request_per_order"),
        ]

    def __str__(self):
        return f"{self.get_kind_display()} · đơn {self.order.code}"

    def deadline(self):
        """Thời hạn mỗi cấp đã chốt khi tạo yêu cầu; đổi tham số sau đó không ảnh hưởng yêu cầu này."""
        from apps.core import params

        minutes = self.level_minutes
        if minutes is None:
            minutes = params.get("approval_level_minutes", at=self.created_at)
        return timedelta(minutes=minutes)

    def level_steps(self, now=None):
        """Các lần chuyển cấp đến hạn tính từ trạng thái đã lưu: [(cấp mới, ở cấp này từ), ...] (BRU-09)."""
        from apps.shifts.models import Shift

        if self.status != self.Status.PENDING:
            return []
        now = now or timezone.now()
        step = self.deadline()
        shift = self.shift or self.order.shift or Shift.objects.operating()
        has_backup = bool(shift and shift.backup_approver_id)
        level, since, steps = self.level, self.level_since, []
        while level < self.Level.EXHAUSTED and now - since >= step:
            since += step
            level += 1
            if level == self.Level.BACKUP and not has_backup:
                level = self.Level.OWNER  # Ca chưa có người dự phòng: chuyển thẳng Chủ quán.
            steps.append((level, since))
        return steps

    def effective_level(self, now=None):
        """Cấp đang áp dụng lúc đọc, đúng cả khi tác vụ định kỳ chưa kịp ghi chuyển cấp."""
        steps = self.level_steps(now)
        return steps[-1][0] if steps else self.level

    @property
    def current_level(self):
        return self.effective_level()

    def get_current_level_display(self):
        return self.Level(self.current_level).label

    def summary(self):
        if self.kind == self.Kind.CANCEL_ITEMS:
            return f"Hủy {self.cups} × {self.line.item_name} {self.line.size_name}"
        if self.kind == self.Kind.CHANGE_ITEM:
            return f"Đổi {self.cups} × {self.line.item_name} {self.line.size_name} sang {self.new_line_text}"
        if self.kind == self.Kind.MOVE_TABLE:
            return f"Chuyển đơn từ {self.order.table} sang {self.target_table}"
        return f"Hủy hóa đơn đã thanh toán {self.order.total:,} đ".replace(",", ".")


class PostPrepCancellation(models.Model):
    """Hủy sau pha chế (BRU-19): lượng nguyên liệu đã trừ khi pha được phân loại lại, không trừ tồn lần nữa."""

    created_at = models.DateTimeField("Thời điểm", auto_now_add=True)
    line = models.ForeignKey(OrderLine, verbose_name="Dòng món", on_delete=models.PROTECT, related_name="+")
    cups = models.PositiveSmallIntegerField("Số ly")
    usage = models.JSONField("Nguyên liệu (theo định mức đã lưu)", default=dict)
    reason = models.ForeignKey(AdjustmentReason, verbose_name="Lý do", on_delete=models.PROTECT, related_name="+")
    request = models.ForeignKey(AdjustmentRequest, verbose_name="Yêu cầu", on_delete=models.PROTECT,
                                related_name="post_prep_cancellations")

    class Meta:
        verbose_name = "Hủy sau pha chế"
        verbose_name_plural = "Hủy sau pha chế"


class Payment(StoreScopedModel):
    """Thanh toán theo bàn (FR-04, BRU-04)."""

    class Method(models.TextChoices):
        CASH = "tien_mat", "Tiền mặt"
        TRANSFER = "chuyen_khoan", "Chuyển khoản"

    class Kind(models.TextChoices):
        NORMAL = "thuong", "Thanh toán thường"
        RECEIVED_ITEMS = "mon_thuc_nhan", "Thanh toán theo món thực nhận"
        PREPAID = "tra_truoc", "Thu trước khi pha chế"
        EXTRA = "thu_them", "Thu thêm sau điều chỉnh đơn thu trước"

    class Status(models.TextChoices):
        VALID = "hop_le", "Hợp lệ"
        VOIDED = "da_huy", "Đã hủy theo yêu cầu được duyệt"

    table = models.ForeignKey(Table, verbose_name="Bàn", on_delete=models.PROTECT, related_name="payments")
    method = models.CharField("Phương thức", max_length=20, choices=Method.choices)
    kind = models.CharField("Loại", max_length=20, choices=Kind.choices, default=Kind.NORMAL)
    amount = models.PositiveIntegerField("Số tiền (đồng)")
    cashier = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="Người thu", on_delete=models.PROTECT,
                                related_name="+")
    shift = models.ForeignKey("shifts.Shift", verbose_name="Ca", on_delete=models.PROTECT, null=True, blank=True,
                              related_name="payments")
    status = models.CharField("Trạng thái", max_length=20, choices=Status.choices, default=Status.VALID)
    operation_key = models.CharField("Mã nghiệp vụ", max_length=64, unique=True)
    # Chỉ để in tiền thừa và đối chiếu khi khách trả tiền mặt; doanh thu luôn là `amount`.
    cash_received = models.PositiveIntegerField("Tiền khách đưa (đồng)", null=True, blank=True)

    class Meta:
        verbose_name = "Thanh toán"
        verbose_name_plural = "Thanh toán"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_method_display()} {self.amount:,} đ · {self.table}".replace(",", ".")


    @property
    def change_due(self):
        return self.cash_received - self.amount if self.cash_received is not None else None


class PrepaidCharge(StoreScopedModel):
    """Khoản phải thu thêm khi đơn đã thu trước được duyệt điều chỉnh làm tổng tiền tăng.

    Thanh toán gốc không sửa. Khoản này chờ thu; thu ngân thu xong thì ghi một thanh toán mới loại Thu thêm vào ca
    đang mở lúc thu. Khoản giảm thì ghi hoàn tiền (shifts.Refund) như hủy hóa đơn, cũng hai bước."""

    class Status(models.TextChoices):
        PENDING = "cho_thu", "Chờ thu thêm"
        COLLECTED = "da_thu", "Đã thu thêm"

    order = models.ForeignKey(Order, verbose_name="Đơn", on_delete=models.PROTECT, related_name="prepaid_charges")
    request = models.OneToOneField(AdjustmentRequest, verbose_name="Yêu cầu điều chỉnh", on_delete=models.PROTECT,
                                   related_name="prepaid_charge")
    amount = models.PositiveIntegerField("Số tiền (đồng)")
    status = models.CharField("Trạng thái", max_length=10, choices=Status.choices, default=Status.PENDING)
    payment = models.OneToOneField(Payment, verbose_name="Thanh toán thu thêm", on_delete=models.PROTECT, null=True,
                                   blank=True, related_name="prepaid_charge")
    collected_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="Người thu thêm", on_delete=models.PROTECT,
                                     null=True, blank=True, related_name="+")
    collected_at = models.DateTimeField("Thu thêm lúc", null=True, blank=True)

    class Meta:
        verbose_name = "Khoản thu thêm của đơn thu trước"
        verbose_name_plural = "Khoản thu thêm của đơn thu trước"
        ordering = ["created_at"]

    def __str__(self):
        return f"Thu thêm {self.amount:,} đ · đơn {self.order.code}".replace(",", ".")


class BackupSlipRange(StoreScopedModel):
    """Dãy số phiếu dự phòng in sẵn cấp cho một ca, có người nhận (BRU-03)."""

    shift = models.ForeignKey("shifts.Shift", verbose_name="Ca", on_delete=models.PROTECT, related_name="backup_ranges")
    first_number = models.PositiveIntegerField("Số đầu")
    last_number = models.PositiveIntegerField("Số cuối")
    receiver = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="Người nhận", on_delete=models.PROTECT,
                                 related_name="+")
    issued_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="Người cấp", on_delete=models.PROTECT,
                                  related_name="+")
    last_used_number = models.PositiveIntegerField("Số cuối đã dùng (0: không dùng)", null=True, blank=True)
    declared_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="Người khai báo", on_delete=models.PROTECT,
                                    null=True, blank=True, related_name="+")
    declared_at = models.DateTimeField("Khai báo lúc", null=True, blank=True)

    class Meta:
        verbose_name = "Dãy phiếu dự phòng"
        verbose_name_plural = "Dãy phiếu dự phòng"
        ordering = ["first_number"]

    def __str__(self):
        return f"{self.first_number:04d}–{self.last_number:04d}"


class BackupSlip(StoreScopedModel):
    """Một phiếu dự phòng đã xử lý: nhập bù thành một đơn, hoặc khai báo hủy (BRU-03)."""

    class Status(models.TextChoices):
        ENTERED = "da_nhap_bu", "Đã nhập bù"
        PENDING = "cho_xac_nhan", "Chờ Chủ quán xác nhận giá hoặc định mức"
        VOIDED = "da_huy", "Khai báo hủy"

    range = models.ForeignKey(BackupSlipRange, verbose_name="Dãy", on_delete=models.PROTECT, related_name="slips")
    number = models.PositiveIntegerField("Số phiếu", unique=True)
    status = models.CharField("Trạng thái", max_length=12, choices=Status.choices)
    order = models.OneToOneField(Order, verbose_name="Đơn", on_delete=models.PROTECT, null=True, blank=True,
                                 related_name="backup_slip")
    operation_code = models.CharField("Mã nghiệp vụ ghi trên phiếu", max_length=64, blank=True)
    sold_at = models.DateTimeField("Thời điểm bán ghi trên phiếu", null=True, blank=True)
    restored_at = models.DateTimeField("Có kết nối lại lúc", null=True, blank=True)
    late = models.BooleanField("Nhập bù quá hạn", default=False)
    linked_existing = models.BooleanField("Liên kết đơn đã lưu trực tuyến", default=False)
    void_reason = models.CharField("Lý do hủy", max_length=255, blank=True)
    payload = models.JSONField("Nội dung phiếu", default=dict, blank=True)
    missing = models.JSONField("Dữ liệu lịch sử còn thiếu", default=list, blank=True)
    confirmed_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="Người xác nhận", on_delete=models.PROTECT,
                                     null=True, blank=True, related_name="+")
    confirmed_at = models.DateTimeField("Xác nhận lúc", null=True, blank=True)
    confirmation = models.JSONField("Giá và định mức đã xác nhận", default=dict, blank=True)
    entered_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="Người nhập", on_delete=models.PROTECT,
                                   related_name="+")
    operation_key = models.CharField("Mã nghiệp vụ", max_length=64, unique=True)

    class Meta:
        verbose_name = "Phiếu dự phòng"
        verbose_name_plural = "Phiếu dự phòng"
        ordering = ["number"]

    def __str__(self):
        return f"Phiếu {self.number:04d}"
