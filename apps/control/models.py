"""Ngoại lệ, xem xét ngoại lệ và vụ việc tổn thất (FR-15, FR-17, FR-18, BRU-12, BRU-14, BRU-15, BRU-16)."""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.core.models import StoreScopedModel, TimeStampedModel


class ExceptionCase(StoreScopedModel):
    class Kind(models.TextChoices):
        REJECTED_ADJUSTMENT = "dc_bi_tu_choi", "Yêu cầu điều chỉnh sau pha chế bị từ chối"
        PAID_CANCELLED = "huy_sau_tt", "Hóa đơn đã thanh toán bị hủy"
        ADJUST_COUNT = "nhieu_dieu_chinh", "Số yêu cầu điều chỉnh sau pha chế vượt mức"
        POST_PREP_VALUE = "gia_tri_huy", "Giá trị hủy sau pha chế của ca vượt mức"
        RECEIVED_ITEMS_PAYMENT = "tt_mon_thuc_nhan", "Thanh toán theo món thực nhận"
        ACCUMULATED_MANAGER = "tich_luy_qlc", "Chênh lệch tích lũy của người phụ trách ca"
        ACCUMULATED_STORE = "tich_luy_quan", "Chênh lệch tích lũy của toàn quán"
        COUNT_ACCUMULATED = "kiem_ke_tich_luy", "Chênh lệch kiểm kê tích lũy"
        BACKUP_VOIDED = "pdp_huy", "Phiếu dự phòng bị hủy"
        BACKUP_LATE = "pdp_qua_han", "Nhập bù phiếu dự phòng quá hạn"
        BACKUP_DUPLICATE = "pdp_trung", "Số phiếu dự phòng trùng"
        BACKUP_OUT_OF_RANGE = "pdp_ngoai_day", "Số phiếu dự phòng ngoài dãy đã cấp"
        CONSUMPTION_OVER = "tieu_hao_vuot", "Tiêu hao nguyên liệu trọng yếu vượt mức"

    class Severity(models.TextChoices):
        IMPORTANT = "quan_trong", "Quan trọng"
        URGENT = "khan", "Khẩn"

    class Status(models.TextChoices):
        OPEN = "cho_xem_xet", "Chờ xem xét"
        CLOSED = "da_dong", "Đã đóng"

    kind = models.CharField("Loại", max_length=30, choices=Kind.choices)
    severity = models.CharField("Mức độ", max_length=20, choices=Severity.choices, default=Severity.IMPORTANT)
    rule = models.CharField("Quy tắc kích hoạt", max_length=255)
    employee = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="Nhân viên", on_delete=models.PROTECT,
                                 null=True, blank=True, related_name="+")
    shift = models.ForeignKey("shifts.Shift", verbose_name="Ca", on_delete=models.PROTECT, null=True, blank=True,
                              related_name="+")
    period = models.CharField("Tháng", max_length=7, blank=True, help_text="YYYY-MM với ngoại lệ tích lũy.")
    ingredient = models.ForeignKey("inventory.Ingredient", verbose_name="Nguyên vật liệu", on_delete=models.PROTECT,
                                   null=True, blank=True, related_name="+")
    order = models.ForeignKey("orders.Order", verbose_name="Đơn", on_delete=models.PROTECT, null=True, blank=True,
                              related_name="+")
    requests = models.ManyToManyField("orders.AdjustmentRequest", verbose_name="Yêu cầu điều chỉnh liên quan",
                                      blank=True, related_name="exceptions")
    shifts = models.ManyToManyField("shifts.Shift", verbose_name="Các ca liên quan", blank=True, related_name="+")
    amount = models.BigIntegerField("Giá trị liên quan (đồng)", default=0)
    detail = models.TextField("Chi tiết", blank=True)
    status = models.CharField("Trạng thái", max_length=20, choices=Status.choices, default=Status.OPEN)
    loss_case = models.ForeignKey("LossCase", verbose_name="Vụ việc tổn thất", on_delete=models.PROTECT,
                                  null=True, blank=True, related_name="exceptions")

    class Meta:
        verbose_name = "Ngoại lệ"
        verbose_name_plural = "Ngoại lệ"
        ordering = ["-created_at"]

    def __str__(self):
        who = f" · {self.employee}" if self.employee_id else ""
        return f"{self.get_kind_display()}{who}"

    def effective_review(self):
        return self.reviews.filter(superseded_by__isnull=True).order_by("-created_at").first()


class ExceptionReview(TimeStampedModel):
    """Kết quả xem xét (BRU-14). Đã lưu thì không sửa, xóa; đổi bằng bản đính chính."""

    class Result(models.TextChoices):
        VALID = "hop_le", "Hợp lệ"
        WARNING = "nhac_nho", "Nhắc nhở"
        VIOLATION = "vi_pham", "Vi phạm"

    exception = models.ForeignKey(ExceptionCase, verbose_name="Ngoại lệ", on_delete=models.PROTECT,
                                  related_name="reviews")
    result = models.CharField("Kết quả", max_length=20, choices=Result.choices)
    money_loss = models.BooleanField("Có tổn thất tiền", default=False)
    measure = models.TextField("Biện pháp, ghi chú", blank=True)
    reviewer = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="Người xem xét", on_delete=models.PROTECT,
                                 related_name="+")
    corrects = models.ForeignKey("self", verbose_name="Đính chính cho", on_delete=models.PROTECT, null=True,
                                 blank=True, related_name="+")
    superseded_by = models.OneToOneField("self", verbose_name="Đã được đính chính bởi", on_delete=models.PROTECT,
                                         null=True, blank=True, related_name="+")
    correction_reason = models.TextField("Lý do và bằng chứng đính chính", blank=True)

    class Meta:
        verbose_name = "Kết quả xem xét ngoại lệ"
        verbose_name_plural = "Kết quả xem xét ngoại lệ"
        ordering = ["created_at"]

    def save(self, *args, **kwargs):
        if self.pk is not None and not getattr(self, "_superseding", False):
            raise ValidationError("Kết quả xem xét đã lưu không sửa được; hãy lập bản đính chính.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Kết quả xem xét không xóa được.")


class LossCase(StoreScopedModel):
    """Vụ việc tổn thất (BRU-15)."""

    class Status(models.TextChoices):
        OPEN = "dang_mo", "Đang xử lý"
        CONCLUDED = "da_ket_luan", "Đã kết luận"

    code = models.CharField("Mã vụ việc", max_length=20, unique=True)
    title = models.CharField("Tiêu đề", max_length=200)
    status = models.CharField("Trạng thái", max_length=20, choices=Status.choices, default=Status.OPEN)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="Người lập", on_delete=models.PROTECT,
                                   related_name="+")

    class Meta:
        verbose_name = "Vụ việc tổn thất"
        verbose_name_plural = "Vụ việc tổn thất"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.code} · {self.title}"

    def proposed_amount(self):
        """Tổng các khoản mất tiền; bằng chứng cùng một giao dịch chỉ tính một lần (AC-38)."""
        groups, total = {}, 0
        for ev in self.evidence.all():
            if ev.transaction_ref:
                groups[ev.transaction_ref] = max(groups.get(ev.transaction_ref, 0), ev.amount)
            else:
                total += ev.amount
        return total + sum(groups.values())

    def verified_amount(self):
        latest = self.verifications.order_by("-created_at", "-id").first()
        return latest.amount if latest else None

    def recovered_amount(self):
        return sum(r.amount for r in self.recoveries.all())

    def remaining_amount(self):
        verified = self.verified_amount()
        return None if verified is None else verified - self.recovered_amount()


class LossEvidence(TimeStampedModel):
    """Bằng chứng của vụ việc: một ngoại lệ hoặc một khoản chênh lệch tiền, mỗi thứ chỉ thuộc một vụ việc."""

    case = models.ForeignKey(LossCase, verbose_name="Vụ việc", on_delete=models.PROTECT, related_name="evidence")
    exception = models.OneToOneField(ExceptionCase, verbose_name="Ngoại lệ", on_delete=models.PROTECT, null=True,
                                     blank=True, related_name="evidence")
    discrepancy = models.OneToOneField("shifts.Discrepancy", verbose_name="Chênh lệch tiền", on_delete=models.PROTECT,
                                       null=True, blank=True, related_name="evidence")
    amount = models.BigIntegerField("Số tiền mất (đồng)")
    transaction_ref = models.CharField("Cùng giao dịch (mã đơn)", max_length=40, blank=True,
                                       help_text="Các bằng chứng cùng mã giao dịch chỉ tính một lần.")

    class Meta:
        verbose_name = "Bằng chứng vụ việc"
        verbose_name_plural = "Bằng chứng vụ việc"
        constraints = [
            models.CheckConstraint(
                condition=(models.Q(exception__isnull=False, discrepancy__isnull=True)
                           | models.Q(exception__isnull=True, discrepancy__isnull=False)),
                name="evidence_exception_xor_discrepancy"),
        ]


class LossVerification(TimeStampedModel):
    """Giá trị tổn thất đã xác minh; lần sau là bản đính chính có lý do, giữ nguyên lịch sử (BRU-15)."""

    case = models.ForeignKey(LossCase, verbose_name="Vụ việc", on_delete=models.PROTECT, related_name="verifications")
    amount = models.BigIntegerField("Tổn thất đã xác minh (đồng)")
    reason = models.TextField("Lý do, bằng chứng", blank=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="Người xác nhận", on_delete=models.PROTECT,
                              related_name="+")

    class Meta:
        verbose_name = "Xác minh tổn thất"
        verbose_name_plural = "Xác minh tổn thất"


class LossRecovery(TimeStampedModel):
    case = models.ForeignKey(LossCase, verbose_name="Vụ việc", on_delete=models.PROTECT, related_name="recoveries")
    amount = models.BigIntegerField("Số tiền thu hồi (đồng)")
    note = models.CharField("Ghi chú", max_length=255, blank=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="Người ghi", on_delete=models.PROTECT,
                              related_name="+")

    class Meta:
        verbose_name = "Thu hồi tổn thất"
        verbose_name_plural = "Thu hồi tổn thất"


class Alert(StoreScopedModel):
    """Một cảnh báo trong trung tâm cảnh báo (FR-51, BRU-36, Bảng 5.4)."""

    class Kind(models.TextChoices):
        OUT_OF_STOCK = "da_het", "Nguyên liệu Đã hết trong giờ mở cửa"
        BACKUP_PENDING = "phieu_du_phong", "Phiếu dự phòng chưa nhập bù, thiếu hoặc trùng số"
        LATE_DATA = "du_lieu_tre", "Dữ liệu ca trễ hạn"
        DISCREPANCY = "chenh_lech_tien", "Chênh lệch tiền ca vượt ngưỡng"
        EXCEPTION = "ngoai_le", "Ngoại lệ chờ xem xét"
        PURCHASE_LATE = "giao_cham", "Giao chậm"
        COUNT_PENDING = "kiem_ke", "Chênh lệch kiểm kê vượt ngưỡng"
        PAYABLE_DUE = "phai_tra", "Khoản phải trả đến hạn"
        RECOUNT = "kiem_ke_lai", "Nguyên liệu cần kiểm kê lại"
        LATE_COUNT = "kiem_ke_tre", "Kiểm kê nhóm trọng yếu trễ hạn"
        ORDER_NEEDED = "can_dat_hang", "Cần đặt hàng"

    class Severity(models.TextChoices):
        URGENT = "khan", "Khẩn"
        IMPORTANT = "quan_trong", "Quan trọng"

    class Status(models.TextChoices):
        NEW = "moi", "Mới"
        IN_PROGRESS = "dang_xu_ly", "Đang xử lý"
        CLOSED = "da_dong", "Đã đóng"

    OPEN = [Status.NEW, Status.IN_PROGRESS]

    kind = models.CharField("Loại", max_length=20, choices=Kind.choices)
    subject = models.CharField("Đối tượng", max_length=60)
    title = models.CharField("Tiêu đề", max_length=200)
    detail = models.TextField("Chi tiết", blank=True)
    severity = models.CharField("Mức", max_length=12, choices=Severity.choices)
    status = models.CharField("Trạng thái", max_length=12, choices=Status.choices, default=Status.NEW)
    assignee = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="Người xử lý chính", on_delete=models.PROTECT,
                                 null=True, blank=True, related_name="+")
    assignee_role = models.CharField("Vai trò xử lý chính", max_length=20)
    level = models.PositiveSmallIntegerField("Cấp (0: chính, 1: đã chuyển Chủ quán)", default=0)
    can_escalate = models.BooleanField("Chuyển cấp khi quá hạn", default=True)
    due_at = models.DateTimeField("Thời hạn")
    escalated_at = models.DateTimeField("Chuyển cấp lúc", null=True, blank=True)
    reminded_count = models.PositiveSmallIntegerField("Số lần nhắc lại", default=0)
    link = models.CharField("Màn hình xử lý", max_length=120, blank=True)
    taken_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="Người nhận xử lý", on_delete=models.PROTECT,
                                 null=True, blank=True, related_name="+")
    taken_at = models.DateTimeField("Nhận xử lý lúc", null=True, blank=True)
    closed_at = models.DateTimeField("Đóng lúc", null=True, blank=True)
    closed_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="Người đóng", on_delete=models.PROTECT,
                                  null=True, blank=True, related_name="+")
    close_note = models.CharField("Kết quả xử lý", max_length=255, blank=True)
    auto_closed = models.BooleanField("Tự đóng", default=False)

    class Meta:
        verbose_name = "Cảnh báo"
        verbose_name_plural = "Cảnh báo"
        ordering = ["status", "due_at"]
        constraints = [models.UniqueConstraint(fields=["kind", "subject"], condition=~models.Q(status="da_dong"),
                                               name="one_open_alert_per_subject")]

    def __str__(self):
        return self.title

    def handler_label(self):
        if self.level:
            return "Chủ quán (đã chuyển cấp)"
        if self.assignee_id:
            return str(self.assignee)
        return "Chủ quán" if self.assignee_role == "chu_quan" else "Pha chế"

    @property
    def handling_minutes(self):
        if self.closed_at is None:
            return None
        return (self.closed_at - self.created_at).total_seconds() / 60

    @property
    def is_overdue(self):
        from django.utils import timezone

        return self.status != self.Status.CLOSED and timezone.now() > self.due_at
