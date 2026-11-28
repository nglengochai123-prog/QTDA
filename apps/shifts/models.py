"""Ca làm việc (bản tối thiểu cho FR-11, FR-59, BRU-09).

Mỗi ca có người duyệt đang trong ca, người duyệt dự phòng và người được ủy quyền xác nhận
thanh toán theo món thực nhận, do Chủ quán chỉ định. Quỹ tiền ca, kết ca và đối soát
(FR-07, FR-08) sẽ mở rộng model này ở Phần 2.
"""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from apps.core.models import StoreScopedModel


class ShiftQuerySet(models.QuerySet):
    def current(self, at=None):
        at = at or timezone.now()
        return (self.filter(status=Shift.Status.OPEN, starts_at__lte=at, ends_at__gt=at)
                .select_related("approver", "backup_approver", "payment_authorizer")
                .order_by("-starts_at").first())

    def operating(self, at=None):
        """Ca đang giữ quỹ lúc `at`: ca trong khung giờ; nếu không có thì ca đã bắt đầu, quá giờ kết thúc dự kiến
        nhưng chưa kết (khách trả tiền muộn sau 22 giờ vẫn vào quỹ ca đó, BRU-01, BRU-06)."""
        at = at or timezone.now()
        # Quá giờ kết thúc hơn OVERRUN_HOURS mà chưa kết (quên kết ca hôm trước) thì không còn giữ quỹ: tiền và đơn
        # lúc này không dồn vào ca cũ; thu ngân mở ca theo giờ hiện tại, ca cũ kết và điều chỉnh sau (Hai, 28/11/2026).
        from datetime import timedelta

        return self.current(at) or (self.filter(status=Shift.Status.OPEN, starts_at__lte=at,
                                                ends_at__gt=at - timedelta(hours=Shift.OVERRUN_HOURS))
                                    .select_related("approver", "backup_approver", "payment_authorizer")
                                    .order_by("-starts_at").first())

    def stale(self, at=None):
        """Ca đã bắt đầu (có tiền đầu ca hoặc có đơn) mà quá giờ kết thúc hơn OVERRUN_HOURS vẫn chưa kết."""
        from datetime import timedelta

        from django.db.models import Q

        at = at or timezone.now()
        return (self.filter(status=Shift.Status.OPEN, ends_at__lte=at - timedelta(hours=Shift.OVERRUN_HOURS))
                .filter(Q(cash_entries__kind="dau_ca") | Q(orders__isnull=False)).distinct().order_by("starts_at"))

    def operating_locked(self, at=None):
        """Như `operating`, nhưng khóa dòng ca rồi đọc lại trạng thái; gọi trong giao dịch trước khi ghi đơn, tiền
        hoặc hoàn tiền vào ca. Kết ca cũng khóa dòng này, nên nếu ca vừa kết xong thì ở đây thấy ca đã kết và chọn
        lại, thay vì ghi vào ca đã chốt số (QA BUG-02). Trên SQLite cả tệp đã bị khóa khi ghi nên không cần thêm."""
        for _ in range(3):
            shift = self.operating(at)
            if shift is None:
                return None
            locked = (self.model.objects.select_for_update(of=("self",)).filter(pk=shift.pk, status=Shift.Status.OPEN)
                      .select_related("approver", "backup_approver", "payment_authorizer").first())
            if locked is not None:
                return locked
        return None


def require_opening_cash(shift):
    """Thu tiền mặt chỉ khi ca đã xác nhận tiền đầu ca (quyết định của Chủ quán 28/11/2026): có số đầu ca thì
    tiền trong két mới đối soát được ngay từ khoản thu đầu tiên. Chuyển khoản không cần."""
    if not shift.cash_entries.filter(kind="dau_ca").exists():
        raise ValidationError(f"{shift} chưa xác nhận tiền đầu ca. Vào Ca của tôi, ghi tiền đầu ca (két trống thì "
                              "ghi 0) rồi mới thu tiền mặt.")


class Shift(StoreScopedModel):
    class Status(models.TextChoices):
        OPEN = "dang_mo", "Đang mở"
        CLOSED = "da_ket", "Đã kết ca"

    name = models.CharField("Tên ca", max_length=40, help_text="Ví dụ: Ca sáng, Ca chiều, Ca tối.")
    starts_at = models.DateTimeField("Bắt đầu")
    ends_at = models.DateTimeField("Kết thúc")
    approver = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="Chủ quán phụ trách ca",
                                 on_delete=models.PROTECT, related_name="+")
    backup_approver = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="Người duyệt dự phòng",
                                        on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    payment_authorizer = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="Người được ủy quyền thanh toán theo món thực nhận",
        on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    status = models.CharField("Trạng thái", max_length=10, choices=Status.choices, default=Status.OPEN)
    closed_at = models.DateTimeField("Kết ca lúc", null=True, blank=True)
    closed_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="Người kết ca", on_delete=models.PROTECT,
                                  null=True, blank=True, related_name="+")
    # Doanh thu chốt khi kết ca, làm căn cứ đối soát (BRU-06).
    closed_cash_revenue = models.BigIntegerField("Doanh thu tiền mặt đã chốt", null=True, blank=True)
    closed_transfer_revenue = models.BigIntegerField("Doanh thu chuyển khoản đã chốt", null=True, blank=True)
    # Ca quỹ tạo từ lịch làm tuần đã công bố, hoặc thu ngân mở theo lịch; trống là ca Chủ quán tạo tay.
    work_shift = models.OneToOneField("schedule.WorkShift", verbose_name="Ca trong lịch", on_delete=models.SET_NULL,
                                      null=True, blank=True, related_name="cash_shift")

    objects = ShiftQuerySet.as_manager()

    class Meta:
        verbose_name = "Ca làm việc"
        verbose_name_plural = "Ca làm việc"
        ordering = ["-starts_at"]

    def __str__(self):
        local = timezone.localtime(self.starts_at)
        return f"{self.name} {local:%d/%m/%Y}"

    @property
    def started(self):
        """Ca đã thực sự mở: đã xác nhận tiền đầu ca hoặc đã có đơn. Ca quỹ tạo sẵn khi công bố lịch mang trạng thái
        Đang mở từ trước giờ làm, nên không dùng trạng thái để nói "đang có ca"."""
        return self.cash_entries.filter(kind=CashEntry.Kind.OPENING).exists() or self.orders.exists()

    def clean(self):
        if self.starts_at and self.ends_at and self.ends_at <= self.starts_at:
            raise ValidationError({"ends_at": "Giờ kết thúc phải sau giờ bắt đầu."})
        if self.starts_at and self.ends_at and (self.ends_at - self.starts_at).total_seconds() > 24 * 3600:
            raise ValidationError({"ends_at": "Một ca dài quá 24 giờ; kiểm tra lại ngày kết thúc."})

    OVERRUN_HOURS = 2

    @property
    def overrun(self):
        """Ca còn mở đã quá giờ kết thúc dự kiến hơn 2 giờ: thường là quên kết ca. Từ 28/11/2026 tiền thu lúc này
        không vào ca này nữa (xem `operating`); ca chỉ còn chờ kết và điều chỉnh. Khách trả muộn ít phút sau giờ đóng
        cửa thì vẫn vào ca (BRU-06)."""
        return (self.status == self.Status.OPEN
                and (timezone.now() - self.ends_at).total_seconds() > self.OVERRUN_HOURS * 3600)

    @property
    def authorizer(self):
        """Người được ủy quyền còn dùng được: người đã nghỉ việc (tài khoản khóa) hay không còn vai trò thu tiền thì coi
        như chưa có, Chủ quán làm thay."""
        from apps.accounts.permissions import Cap, user_can

        person = self.payment_authorizer if self.payment_authorizer_id else None
        return person if person is not None and person.is_active and user_can(person, Cap.PAYMENT) else None

    @property
    def missing_roles(self):
        """Nhắc Chủ quán khi ca chưa đủ người theo BRU-09 (AC-113)."""
        missing = []
        if self.authorizer is None:
            missing.append("người được ủy quyền thanh toán theo món thực nhận")
        return missing



class ExpenseCategory(models.TextChoices):
    """Danh mục chi theo BRU-33. Chi nguyên vật liệu chỉ ghi qua phiếu nhập (Phần 3)."""

    MATERIALS = "nguyen_vat_lieu", "Nguyên vật liệu (chỉ ghi qua phiếu nhập)"
    FIXED = "co_dinh", "Chi phí cố định"
    REPAIR = "sua_chua", "Sửa chữa và thiết bị"
    OTHER = "khac", "Khác"


class CashEntry(StoreScopedModel):
    """Bút toán quỹ tiền mặt ca (FR-07, BRU-05). Chỉ thêm mới; sai thì ghi bút toán khác."""

    class Kind(models.TextChoices):
        OPENING = "dau_ca", "Tiền đầu ca"
        EXPENSE = "chi", "Chi tiền mặt"
        HANDOVER = "nop", "Nộp tiền giữa ca"

    shift = models.ForeignKey(Shift, verbose_name="Ca", on_delete=models.PROTECT, related_name="cash_entries")
    kind = models.CharField("Loại", max_length=10, choices=Kind.choices)
    amount = models.PositiveBigIntegerField("Số tiền (đồng)")
    category = models.CharField("Danh mục chi", max_length=20, choices=ExpenseCategory.choices, blank=True)
    note = models.CharField("Nội dung", max_length=255, blank=True)
    receipt = models.FileField("Ảnh chứng từ", upload_to="chung-tu/%Y/%m/", blank=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="Người ghi", on_delete=models.PROTECT,
                              related_name="+")
    receiver = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="Người nhận", on_delete=models.PROTECT,
                                 null=True, blank=True, related_name="+")
    confirmed_at = models.DateTimeField("Người nhận xác nhận lúc", null=True, blank=True)
    operation_key = models.CharField("Mã nghiệp vụ", max_length=64, unique=True)

    class Meta:
        verbose_name = "Bút toán quỹ ca"
        verbose_name_plural = "Bút toán quỹ ca"
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.get_kind_display()} {self.amount:,} đ".replace(",", ".")

    @property
    def is_effective(self):
        """Khoản nộp chỉ có hiệu lực khi người nhận xác nhận (BRU-05, AC-14)."""
        return self.kind != self.Kind.HANDOVER or self.confirmed_at is not None


class Refund(StoreScopedModel):
    """Hoàn tiền cho khách theo yêu cầu hủy hóa đơn đã được duyệt (BRU-05, BRU-10, GD-07).

    Hai bước tách riêng: Chủ quán duyệt hoàn (chưa có tiền ra), rồi người thu tiền xác nhận
    đã hoàn thực tế. Tiền ra chỉ ghi một lần, vào ca đang mở lúc xác nhận đã hoàn.
    """

    class Method(models.TextChoices):
        CASH = "tien_mat", "Tiền mặt"
        TRANSFER = "chuyen_khoan", "Chuyển khoản"

    class Status(models.TextChoices):
        APPROVED = "cho_hoan", "Đã duyệt, chờ hoàn tiền"
        PAID = "da_hoan", "Đã hoàn tiền"

    class Kind(models.TextChoices):
        CANCEL_PAID = "huy_hoa_don", "Hủy hóa đơn đã thanh toán"
        # Đơn thu trước được duyệt giảm món: tổng tiền đơn đã giảm theo, nên báo cáo doanh thu theo món không trừ
        # khoản này lần nữa; quỹ ca vẫn trừ vì tiền thật ra khỏi két.
        PREPAID_DECREASE = "giam_thu_truoc", "Trả lại phần giảm của đơn thu trước"

    shift = models.ForeignKey(Shift, verbose_name="Ca thực hoàn", on_delete=models.PROTECT, null=True, blank=True,
                              related_name="refunds")
    payment = models.ForeignKey("orders.Payment", verbose_name="Thanh toán gốc", on_delete=models.PROTECT,
                                null=True, blank=True, related_name="refunds")
    order_code = models.CharField("Mã đơn", max_length=20)
    method = models.CharField("Phương thức hoàn", max_length=20, choices=Method.choices)
    amount = models.PositiveBigIntegerField("Số tiền (đồng)")
    status = models.CharField("Trạng thái", max_length=10, choices=Status.choices, default=Status.APPROVED)
    kind = models.CharField("Loại hoàn", max_length=20, choices=Kind.choices, default=Kind.CANCEL_PAID)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="Người duyệt", on_delete=models.PROTECT,
                                    related_name="+")
    request_id_ref = models.PositiveBigIntegerField("Mã yêu cầu điều chỉnh", unique=True)
    paid_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="Người hoàn tiền", on_delete=models.PROTECT,
                                null=True, blank=True, related_name="+")
    paid_at = models.DateTimeField("Hoàn tiền lúc", null=True, blank=True)
    paid_note = models.CharField("Ghi chú khi hoàn", max_length=255, blank=True)

    class Meta:
        verbose_name = "Hoàn tiền"
        verbose_name_plural = "Hoàn tiền"

    def __str__(self):
        return f"Hoàn {self.amount:,} đ {self.get_method_display().lower()} · đơn {self.order_code}".replace(",", ".")


class ShiftReport(StoreScopedModel):
    """Báo cáo cuối ca (FR-08). Gửi xong thì chạy đối soát ngay (AC-17)."""

    shift = models.OneToOneField(Shift, verbose_name="Ca", on_delete=models.PROTECT, related_name="report")
    counted_cash = models.PositiveBigIntegerField("Tiền mặt đếm thực tế")
    transfer_received = models.PositiveBigIntegerField("Tiền chuyển khoản nhận theo sao kê")
    transfer_refunded = models.PositiveBigIntegerField("Tiền hoàn bằng chuyển khoản theo sao kê", default=0)
    incidents = models.TextField("Sự cố phát sinh", blank=True)
    submitted_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="Người lập", on_delete=models.PROTECT,
                                     related_name="+")

    class Meta:
        verbose_name = "Báo cáo cuối ca"
        verbose_name_plural = "Báo cáo cuối ca"

    def effective(self):
        """Số liệu đang có hiệu lực: bản đính chính đã duyệt mới nhất, nếu không thì bản gửi gốc (GD-11)."""
        latest = self.corrections.filter(status=ShiftReportCorrection.Status.APPROVED).order_by("-decided_at", "-id").first()
        source = latest or self
        return {"counted_cash": source.counted_cash, "transfer_received": source.transfer_received,
                "transfer_refunded": source.transfer_refunded, "correction": latest}


class ShiftReportCorrection(StoreScopedModel):
    """Đính chính báo cáo cuối ca: có lý do, người duyệt và giữ lịch sử; bản gốc không bị sửa (GD-11)."""

    class Status(models.TextChoices):
        PENDING = "cho_duyet", "Chờ duyệt"
        APPROVED = "da_duyet", "Đã duyệt"
        REJECTED = "tu_choi", "Từ chối"

    report = models.ForeignKey(ShiftReport, verbose_name="Báo cáo cuối ca", on_delete=models.PROTECT,
                               related_name="corrections")
    counted_cash = models.PositiveBigIntegerField("Tiền mặt đếm thực tế")
    transfer_received = models.PositiveBigIntegerField("Tiền chuyển khoản nhận theo sao kê")
    transfer_refunded = models.PositiveBigIntegerField("Tiền hoàn bằng chuyển khoản theo sao kê", default=0)
    reason = models.TextField("Lý do đính chính")
    status = models.CharField("Trạng thái", max_length=10, choices=Status.choices, default=Status.PENDING)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="Người đề nghị", on_delete=models.PROTECT,
                                     related_name="+")
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="Người duyệt", on_delete=models.PROTECT,
                                   null=True, blank=True, related_name="+")
    decided_at = models.DateTimeField("Duyệt lúc", null=True, blank=True)
    decision_note = models.CharField("Ghi chú duyệt", max_length=255, blank=True)
    operation_key = models.CharField("Mã nghiệp vụ", max_length=64, unique=True)

    class Meta:
        verbose_name = "Đính chính báo cáo cuối ca"
        verbose_name_plural = "Đính chính báo cáo cuối ca"
        ordering = ["-created_at"]
        constraints = [models.UniqueConstraint(fields=["report"], condition=models.Q(status="cho_duyet"),
                                               name="one_pending_correction_per_report")]

    def __str__(self):
        return f"Đính chính báo cáo {self.report.shift} · {self.get_status_display()}"


class DiscrepancyQuerySet(models.QuerySet):
    def current(self):
        """Chỉ các khoản đang có hiệu lực; khoản bị thay bởi đối soát lại sau đính chính vẫn giữ làm lịch sử."""
        return self.filter(superseded_at__isnull=True)


class Discrepancy(StoreScopedModel):
    """Một khoản chênh lệch khác 0 của ca theo phương thức (BRU-10). Lưu cả khi dưới ngưỡng."""

    class Method(models.TextChoices):
        CASH = "tien_mat", "Tiền mặt"
        TRANSFER_IN = "ck_nhan", "Chuyển khoản nhận"
        TRANSFER_REFUND = "ck_hoan", "Hoàn bằng chuyển khoản"

    class Decision(models.TextChoices):
        NONE = "", "Chưa quyết định"
        ACCEPTED = "chap_nhan", "Chấp nhận giải trình"
        REJECTED = "khong_chap_nhan", "Không chấp nhận"

    shift = models.ForeignKey(Shift, verbose_name="Ca", on_delete=models.PROTECT, related_name="discrepancies")
    method = models.CharField("Phương thức", max_length=20, choices=Method.choices)
    expected = models.BigIntegerField("Phải có")
    actual = models.BigIntegerField("Thực tế")
    difference = models.BigIntegerField("Chênh lệch (thực tế - phải có)")
    manager = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="Người phụ trách ca",
                                on_delete=models.PROTECT, related_name="+")
    over_threshold = models.BooleanField("Vượt ngưỡng", default=False)
    threshold = models.BigIntegerField("Ngưỡng đã áp dụng", null=True, blank=True)
    explanation = models.TextField("Giải trình", blank=True)
    explained_at = models.DateTimeField("Giải trình lúc", null=True, blank=True)
    decision = models.CharField("Quyết định của Chủ quán", max_length=20, choices=Decision.choices, blank=True,
                                default=Decision.NONE)
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="Người quyết định",
                                   on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    decided_at = models.DateTimeField("Quyết định lúc", null=True, blank=True)
    superseded_at = models.DateTimeField("Hết hiệu lực lúc", null=True, blank=True)
    superseded_by = models.ForeignKey("ShiftReportCorrection", verbose_name="Do đính chính", on_delete=models.PROTECT,
                                      null=True, blank=True, related_name="superseded_discrepancies")

    objects = DiscrepancyQuerySet.as_manager()

    class Meta:
        verbose_name = "Chênh lệch ca"
        verbose_name_plural = "Chênh lệch ca"
        ordering = ["-created_at"]
        constraints = [models.UniqueConstraint(fields=["shift", "method"], condition=models.Q(superseded_at__isnull=True),
                                               name="one_current_discrepancy_per_method")]

    def __str__(self):
        from apps.core.numbers import fmt

        return f"{self.shift} · {self.get_method_display()} {'+' if self.difference > 0 else ''}{fmt(self.difference, 0)} đ"

    @property
    def is_shortage(self):
        return self.difference < 0

    @property
    def is_unexplained_shortage(self):
        """Thiếu tiền chưa được giải thích hợp lệ (BRU-11): mọi khoản thiếu trừ khi Chủ quán chấp nhận giải trình."""
        return self.is_shortage and self.decision != self.Decision.ACCEPTED
