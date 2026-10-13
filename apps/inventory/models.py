"""Nhà cung cấp, nguyên vật liệu (FR-20) và định mức món có phiên bản (FR-21, BRU-39).

Tồn vật lý và tồn có thể dùng (FR-22, BRU-18) sẽ thêm ở phần tạo đơn và pha chế.
"""

from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models, transaction
from django.db.models import Max, Q
from django.utils import timezone

from apps.catalog.models import ItemSize, MenuItem, Option
from apps.core.models import StoreScopedModel, TimeStampedModel


class Supplier(StoreScopedModel):
    name = models.CharField("Tên nhà cung cấp", max_length=120)
    phone = models.CharField("Số điện thoại", max_length=20, blank=True)
    note = models.TextField("Ghi chú", blank=True)
    is_active = models.BooleanField("Đang giao dịch", default=True)

    class Meta:
        verbose_name = "Nhà cung cấp"
        verbose_name_plural = "Nhà cung cấp"
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["store", "name"], name="uniq_supplier_name_per_store")]

    def __str__(self):
        return self.name


class Unit(models.TextChoices):
    GRAM = "g", "gram"
    ML = "ml", "ml"
    PIECE = "cai", "cái"
    FRUIT = "qua", "quả"
    PACK = "goi", "gói"


class PolicyGroup(models.TextChoices):
    PERISHABLE = "A", "Nhóm A, dễ hỏng: kiểm tra mỗi tối"
    STABLE = "B", "Nhóm B, ổn định: kiểm tra mỗi tuần"


class Weekday(models.IntegerChoices):
    MON = 0, "Thứ Hai"
    TUE = 1, "Thứ Ba"
    WED = 2, "Thứ Tư"
    THU = 3, "Thứ Năm"
    FRI = 4, "Thứ Sáu"
    SAT = 5, "Thứ Bảy"
    SUN = 6, "Chủ nhật"


class Ingredient(StoreScopedModel):
    name = models.CharField("Tên nguyên vật liệu", max_length=120)
    unit = models.CharField("Đơn vị tính", max_length=10, choices=Unit.choices)
    pack_size = models.DecimalField("Quy cách đóng gói", max_digits=12, decimal_places=2,
                                    validators=[MinValueValidator(Decimal("0.01"))],
                                    help_text="Lượng trong một đơn vị mua, theo đơn vị tính. Ví dụ hộp 1.000 ml.")
    pack_label = models.CharField("Tên quy cách", max_length=40, blank=True, help_text="Ví dụ: hộp, bao, chai.")
    main_supplier = models.ForeignKey(Supplier, verbose_name="Nhà cung cấp chính", on_delete=models.PROTECT,
                                      null=True, blank=True, related_name="ingredients")
    lead_time_days = models.PositiveSmallIntegerField("Thời gian giao hàng (ngày)")
    order_cycle_days = models.PositiveSmallIntegerField("Chu kỳ đặt hàng (ngày)", null=True, blank=True)
    shelf_life_days = models.PositiveSmallIntegerField("Thời hạn sử dụng (ngày)", null=True, blank=True)
    storage_capacity = models.DecimalField("Sức chứa bảo quản", max_digits=12, decimal_places=2,
                                           null=True, blank=True, help_text="Theo đơn vị tính.")
    safety_stock = models.DecimalField("Mức tồn an toàn", max_digits=12, decimal_places=2, default=0)
    safety_stock_is_provisional = models.BooleanField(
        "Mức tồn an toàn tạm thời", default=True,
        help_text="Giữ nhãn Tạm thời cho đến khi có dữ liệu để đề xuất (BRU-22, AC-45).",
    )
    is_critical = models.BooleanField("Nhóm trọng yếu", default=False)
    count_accumulated_threshold = models.DecimalField(
        "Ngưỡng thiếu kiểm kê tích lũy tháng", max_digits=12, decimal_places=2, null=True, blank=True,
        help_text="Theo đơn vị tính. Để trống thì dùng 1 quy cách đóng gói (BRU-25).")
    is_active = models.BooleanField("Đang sử dụng", default=True)
    # Chính sách mua (thiết kế mua nguyên liệu mục 7.4). Để trống thì dùng mặc định theo nhóm và tham số chung.
    policy_group = models.CharField(
        "Nhóm chính sách", max_length=1, choices=PolicyGroup.choices, blank=True,
        help_text="Để trống: hạn dùng từ 14 ngày trở xuống là nhóm A, còn lại nhóm B.")
    service_level = models.PositiveSmallIntegerField(
        "Mức phục vụ chu kỳ (%)", null=True, blank=True,
        validators=[MinValueValidator(50), MaxValueValidator(99)],
        help_text="Để trống: 95% nếu trọng yếu, 90% nếu không.")
    review_period_days = models.PositiveSmallIntegerField(
        "Chu kỳ kiểm tra R (ngày)", null=True, blank=True, validators=[MinValueValidator(1)],
        help_text="Để trống: nhóm A mỗi ngày (1), nhóm B mỗi tuần (7).")
    target_cycle_days = models.PositiveSmallIntegerField(
        "Khoảng cách mua mong muốn T (ngày)", null=True, blank=True, validators=[MinValueValidator(1)],
        help_text="Không nhỏ hơn R. Để trống: nhóm A 2 ngày, nhóm B bằng R.")
    review_weekday = models.PositiveSmallIntegerField(
        "Ngày kiểm tra trong tuần", null=True, blank=True, choices=Weekday.choices,
        help_text="Dùng khi chu kỳ là bội của 7 ngày và chưa khai ngày kiểm tra gốc. Để trống: tối Chủ nhật.")
    review_anchor = models.DateField(
        "Ngày kiểm tra gốc", null=True, blank=True,
        help_text="Lịch kiểm tra định kỳ là ngày này cộng các bội của R. Nên khai khi R không phải 1 hay 7 ngày.")
    moq_packs = models.PositiveSmallIntegerField("Lượng đặt tối thiểu (số gói)", default=1,
                                                 validators=[MinValueValidator(1)])
    exposure_days = models.PositiveSmallIntegerField(
        "Số ngày phơi nhiễm", default=1,
        help_text="Số ngày bán trọn vẹn có thể trôi qua từ lúc đặt tới lúc hàng dùng được, trường hợp xấu.")
    weekly_low = models.DecimalField("Tuần dùng ít (theo đơn vị tính)", max_digits=12, decimal_places=2, null=True,
                                     blank=True, help_text="Khoảng 1 trong 20 tuần thấp hơn.")
    weekly_typical = models.DecimalField("Tuần thường lệ (theo đơn vị tính)", max_digits=12, decimal_places=2,
                                         null=True, blank=True,
                                         help_text="Ước tính của Chủ quán, dùng khi chưa đủ dữ liệu.")
    weekly_high = models.DecimalField("Tuần dùng nhiều (theo đơn vị tính)", max_digits=12, decimal_places=2, null=True,
                                      blank=True, help_text="Khoảng 1 trong 20 tuần cao hơn.")
    weekly_estimate_at = models.DateTimeField(
        "Ước tính tuần có hiệu lực từ", null=True, blank=True, editable=False,
        help_text="Tự ghi khi đổi ước tính; đánh giá dự báo quá khứ không dùng ước tính trước thời điểm này.")

    class Meta:
        verbose_name = "Nguyên vật liệu"
        verbose_name_plural = "Nguyên vật liệu"
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["store", "name"], name="uniq_ingredient_name_per_store")]

    def __str__(self):
        return f"{self.name} ({self.get_unit_display()})"

    def save(self, *args, **kwargs):
        estimate = (self.weekly_low, self.weekly_typical, self.weekly_high)
        stored = (Ingredient.objects.filter(pk=self.pk).values_list("weekly_low", "weekly_typical", "weekly_high")
                  .first() if self.pk else None)
        if any(v is not None for v in estimate) and (stored is None or tuple(
                None if v is None else Decimal(str(v)) for v in estimate) != tuple(stored)):
            self.weekly_estimate_at = timezone.now()
        super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        if self.weekly_typical is not None and None not in (self.weekly_low, self.weekly_high):
            if not (self.weekly_low <= self.weekly_typical <= self.weekly_high):
                raise ValidationError("Tuần thường lệ phải nằm giữa tuần dùng ít và tuần dùng nhiều.")
        if self.review_period_days and self.target_cycle_days and self.target_cycle_days < self.review_period_days:
            raise ValidationError({"target_cycle_days": "T không được nhỏ hơn chu kỳ kiểm tra R."})


class RecipeVersionQuerySet(models.QuerySet):
    def published(self):
        return self.filter(status=RecipeVersion.Status.PUBLISHED)

    def current_for(self, item, at=None):
        at = at or timezone.now()
        return (self.published().filter(item=item, effective_from__lte=at)
                .order_by("-effective_from", "-number").first())


class RecipeVersion(StoreScopedModel):
    """Một phiên bản định mức của một món. Đã áp dụng thì không sửa được; muốn đổi thì tạo bản mới."""

    class Status(models.TextChoices):
        DRAFT = "nhap", "Bản nháp"
        PUBLISHED = "ap_dung", "Đã áp dụng"

    item = models.ForeignKey(MenuItem, verbose_name="Món", on_delete=models.PROTECT, related_name="recipe_versions")
    number = models.PositiveIntegerField("Phiên bản", editable=False)
    status = models.CharField("Trạng thái", max_length=10, choices=Status.choices, default=Status.DRAFT,
                              editable=False)
    effective_from = models.DateTimeField("Hiệu lực từ", null=True, blank=True, editable=False)
    published_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="Người áp dụng",
                                     on_delete=models.PROTECT, null=True, blank=True, editable=False,
                                     related_name="+")
    note = models.CharField("Ghi chú thay đổi", max_length=255, blank=True)

    objects = RecipeVersionQuerySet.as_manager()

    class Meta:
        verbose_name = "Định mức món"
        verbose_name_plural = "Định mức món"
        ordering = ["item__name", "-number"]
        constraints = [
            models.UniqueConstraint(fields=["item", "number"], name="uniq_recipe_version_number"),
            models.UniqueConstraint(fields=["item"], condition=Q(status="nhap"), name="one_draft_recipe_per_item"),
        ]

    def __str__(self):
        return f"{self.item.name} · phiên bản {self.number} ({self.get_status_display()})"

    @property
    def is_published(self):
        return self.status == self.Status.PUBLISHED

    def save(self, *args, **kwargs):
        if self.pk is not None:
            stored = RecipeVersion.objects.filter(pk=self.pk).values_list("status", flat=True).first()
            if stored == self.Status.PUBLISHED and not getattr(self, "_publishing", False):
                raise ValidationError("Phiên bản định mức đã áp dụng không sửa được. Hãy tạo phiên bản mới.")
        if self.number is None:
            last = RecipeVersion.objects.filter(item=self.item).aggregate(n=Max("number"))["n"] or 0
            self.number = last + 1
        if self.store_id is None:
            self.store = self.item.store
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.is_published:
            raise ValidationError("Phiên bản định mức đã áp dụng không xóa được.")
        return super().delete(*args, **kwargs)

    @transaction.atomic
    def publish(self, user, effective_from=None):
        """Áp dụng bản nháp. Từ thời điểm hiệu lực, dòng món mới dùng bản này; dòng cũ giữ bản cũ."""
        if self.is_published:
            raise ValidationError("Phiên bản này đã được áp dụng.")
        if not self.lines.exists():
            raise ValidationError("Phiên bản chưa có dòng định mức nào.")
        self.status = self.Status.PUBLISHED
        self.effective_from = effective_from or timezone.now()
        self.published_by = user
        self._publishing = True
        try:
            self.save()
        finally:
            self._publishing = False

    @transaction.atomic
    def copy_as_draft(self):
        """Tạo bản nháp mới từ phiên bản này để sửa."""
        draft = RecipeVersion.objects.create(item=self.item, store=self.store,
                                             note=f"Sửa từ phiên bản {self.number}")
        RecipeLine.objects.bulk_create([
            RecipeLine(version=draft, ingredient=line.ingredient, size=line.size,
                       option=line.option, quantity=line.quantity)
            for line in self.lines.all()
        ])
        return draft


class RecipeLine(TimeStampedModel):
    """Lượng nguyên liệu cho một kích cỡ, hoặc lượng cộng thêm khi chọn một tùy chọn."""

    version = models.ForeignKey(RecipeVersion, verbose_name="Phiên bản", on_delete=models.CASCADE,
                                related_name="lines")
    ingredient = models.ForeignKey(Ingredient, verbose_name="Nguyên vật liệu", on_delete=models.PROTECT,
                                   related_name="recipe_lines")
    size = models.ForeignKey(ItemSize, verbose_name="Kích cỡ", on_delete=models.PROTECT, null=True, blank=True,
                             related_name="recipe_lines")
    option = models.ForeignKey(Option, verbose_name="Tùy chọn", on_delete=models.PROTECT, null=True, blank=True,
                               related_name="recipe_lines")
    quantity = models.DecimalField("Lượng", max_digits=10, decimal_places=2,
                                   validators=[MinValueValidator(Decimal("0.01"))])

    class Meta:
        verbose_name = "Dòng định mức"
        verbose_name_plural = "Dòng định mức"
        constraints = [
            models.CheckConstraint(
                condition=(Q(size__isnull=False, option__isnull=True) | Q(size__isnull=True, option__isnull=False)),
                name="recipe_line_size_xor_option",
            ),
        ]

    def __str__(self):
        target = self.size.name if self.size_id else self.option.name if self.option_id else "?"
        return f"{target}: {self.quantity} {self.ingredient.get_unit_display()} {self.ingredient.name}"

    def clean(self):
        if bool(self.size_id) == bool(self.option_id):
            raise ValidationError("Mỗi dòng định mức chọn đúng một: kích cỡ hoặc tùy chọn.")
        item = self.version.item
        if self.size_id and self.size.item_id != item.pk:
            raise ValidationError({"size": "Kích cỡ không thuộc món này."})
        if self.option_id and not item.option_groups.filter(pk=self.option.group_id).exists():
            raise ValidationError({"option": "Tùy chọn không áp dụng cho món này."})

    def _guard(self):
        if self.version.is_published:
            raise ValidationError("Phiên bản định mức đã áp dụng không sửa được. Hãy tạo phiên bản mới.")

    def save(self, *args, **kwargs):
        self._guard()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        self._guard()
        return super().delete(*args, **kwargs)


class IngredientStock(TimeStampedModel):
    """Số dư tồn của một nguyên liệu (BRU-18), cập nhật cùng giao dịch với mỗi biến động.

    Tồn vật lý = tổng các biến động. Tồn đang giữ = lượng cho các món đã gửi pha chế nhưng chưa pha xong.
    Tồn có thể dùng = tồn vật lý - tồn đang giữ.
    """

    ingredient = models.OneToOneField(Ingredient, verbose_name="Nguyên vật liệu", on_delete=models.PROTECT,
                                      related_name="stock")
    physical = models.DecimalField("Tồn vật lý", max_digits=14, decimal_places=2, default=0)
    reserved = models.DecimalField("Đang giữ cho món chờ pha", max_digits=14, decimal_places=2, default=0)

    class Meta:
        verbose_name = "Tồn kho"
        verbose_name_plural = "Tồn kho"
        constraints = [models.CheckConstraint(condition=Q(reserved__gte=0), name="stock_reserved_not_negative")]

    def __str__(self):
        return f"{self.ingredient.name}: {self.physical}"

    @property
    def available(self):
        return self.physical - self.reserved


class StockMovement(StoreScopedModel):
    """Một dòng sổ biến động kho. Chỉ thêm mới; sai thì ghi biến động điều chỉnh, không sửa dòng cũ."""

    class Kind(models.TextChoices):
        OPENING = "ton_dau_ky", "Tồn đầu kỳ"
        CONSUME = "pha_che", "Tiêu hao khi pha chế"
        RECEIPT = "nhap_hang", "Nhập hàng"
        WASTE = "hao_hut", "Hao hụt xuất kho"
        COUNT = "kiem_ke", "Điều chỉnh theo kiểm kê"

    ingredient = models.ForeignKey(Ingredient, verbose_name="Nguyên vật liệu", on_delete=models.PROTECT,
                                   related_name="movements")
    kind = models.CharField("Loại biến động", max_length=20, choices=Kind.choices)
    quantity = models.DecimalField("Số lượng (+ tăng, - giảm)", max_digits=14, decimal_places=2)
    balance_after = models.DecimalField("Tồn vật lý sau biến động", max_digits=14, decimal_places=2)
    source_type = models.CharField("Nguồn nghiệp vụ", max_length=40, blank=True)
    source_id = models.CharField("Mã nguồn", max_length=64, blank=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="Người thực hiện", on_delete=models.PROTECT,
                              related_name="+")
    note = models.CharField("Ghi chú", max_length=255, blank=True)

    class Meta:
        verbose_name = "Biến động kho"
        verbose_name_plural = "Biến động kho"
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["source_type", "source_id"])]

    def __str__(self):
        return f"{self.get_kind_display()} {self.quantity:+} {self.ingredient.get_unit_display()} {self.ingredient.name}"

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise ValidationError("Biến động kho không sửa được. Hãy ghi một biến động điều chỉnh.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Biến động kho không xóa được.")



# ---------------- Phần 3: nguyên vật liệu vận hành ----------------

class QuickReport(StoreScopedModel):
    """Báo nhanh nguyên liệu Sắp hết hoặc Đã hết (FR-23)."""

    class Level(models.TextChoices):
        LOW = "sap_het", "Sắp hết"
        OUT = "da_het", "Đã hết"

    ingredient = models.ForeignKey(Ingredient, verbose_name="Nguyên vật liệu", on_delete=models.PROTECT,
                                   related_name="quick_reports")
    level = models.CharField("Mức", max_length=10, choices=Level.choices)
    estimated_left = models.DecimalField("Lượng còn lại ước tính", max_digits=12, decimal_places=2, null=True,
                                         blank=True)
    reporter = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="Người báo", on_delete=models.PROTECT,
                                 related_name="+")
    acknowledged_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="Người xử lý",
                                        on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    acknowledged_at = models.DateTimeField("Xử lý lúc", null=True, blank=True)
    note = models.CharField("Ghi chú xử lý", max_length=255, blank=True)

    class Meta:
        verbose_name = "Báo nhanh nguyên liệu"
        verbose_name_plural = "Báo nhanh nguyên liệu"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.ingredient.name}: {self.get_level_display()}"


class ShortageCase(StoreScopedModel):
    """Trường hợp thiếu nguyên liệu (FR-27, BRU-26): mỗi nguyên liệu tối đa một trường hợp mỗi ngày."""

    class Source(models.TextChoices):
        REPORTED_OUT = "bao_het", "Nhân viên báo Đã hết trong giờ mở cửa"
        ADJUSTMENT = "dieu_chinh", "Đổi hoặc hủy món vì Hết nguyên liệu"
        CUSTOMER_SWITCH = "doi_mon", "Khách đổi món sau cảnh báo không đủ nguyên liệu"

    ingredient = models.ForeignKey(Ingredient, verbose_name="Nguyên vật liệu", on_delete=models.PROTECT,
                                   related_name="shortage_cases")
    day = models.DateField("Ngày")
    source = models.CharField("Nguồn", max_length=20, choices=Source.choices)
    source_ref = models.CharField("Tham chiếu", max_length=100, blank=True)

    class Meta:
        verbose_name = "Trường hợp thiếu nguyên liệu"
        verbose_name_plural = "Trường hợp thiếu nguyên liệu"
        ordering = ["-day", "ingredient__name"]
        constraints = [models.UniqueConstraint(fields=["ingredient", "day"], name="one_shortage_per_ingredient_day")]


class PurchaseOrder(StoreScopedModel):
    """Lần đặt hàng (FR-30, BRU-23)."""

    class Status(models.TextChoices):
        DRAFT = "nhap", "Nháp, chưa báo nhà cung cấp"
        ORDERED = "da_dat", "Đã đặt"
        PARTIAL = "giao_mot_phan", "Giao một phần"
        DELIVERED = "da_giao_du", "Đã giao đủ"
        LATE = "giao_cham", "Giao chậm"
        CANCELLED = "da_huy", "Đã hủy"

    supplier = models.ForeignKey(Supplier, verbose_name="Nhà cung cấp", on_delete=models.PROTECT,
                                 related_name="purchase_orders")
    ingredient = models.ForeignKey(Ingredient, verbose_name="Nguyên vật liệu", on_delete=models.PROTECT,
                                   related_name="purchase_orders")
    quantity = models.DecimalField("Số lượng đặt (theo đơn vị tính)", max_digits=12, decimal_places=2,
                                   validators=[MinValueValidator(Decimal("0.01"))])
    received_quantity = models.DecimalField("Đã nhận", max_digits=12, decimal_places=2, default=0)
    expected_date = models.DateField("Ngày giao dự kiến")
    status = models.CharField("Trạng thái", max_length=20, choices=Status.choices, default=Status.ORDERED)
    note = models.CharField("Ghi chú", max_length=255, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="Người ghi", on_delete=models.PROTECT,
                                   related_name="+")
    ordered_at = models.DateTimeField("Báo nhà cung cấp lúc", null=True, blank=True)
    order_by = models.DateField("Phải đặt chậm nhất", null=True, blank=True,
                                help_text="Đơn nháp quá ngày này không còn được tính là hàng đang về.")

    class Meta:
        verbose_name = "Lần đặt hàng"
        verbose_name_plural = "Lần đặt hàng"
        ordering = ["expected_date", "id"]

    def __str__(self):
        return f"Đặt {format(self.quantity.normalize(), 'f')} {self.ingredient.get_unit_display()} {self.ingredient.name} · {self.supplier}"

    @property
    def remaining(self):
        return max(self.quantity - self.received_quantity, Decimal(0))

    @property
    def over_received(self):
        return max(self.received_quantity - self.quantity, Decimal(0))

    def effective_status(self, today=None):
        """Trạng thái tại lúc đọc: quá ngày giao mà chưa đủ là Giao chậm, kể cả khi tác vụ định kỳ chưa ghi."""
        today = today or timezone.localdate()
        if self.status in (self.Status.ORDERED, self.Status.PARTIAL) and self.expected_date < today:
            return self.Status.LATE
        return self.status

    def draft_expired(self, today=None):
        """Đơn nháp quá ngày phải đặt mà chưa báo nhà cung cấp: không che rủi ro nữa (mục 8.1)."""
        today = today or timezone.localdate()
        limit = self.order_by or timezone.localdate(self.created_at)
        return self.status == self.Status.DRAFT and today > limit

    def is_incoming(self, today=None):
        """Nháp còn hạn, Đã đặt, Giao một phần chưa quá ngày giao; Giao chậm, Đã giao đủ, Đã hủy không tính."""
        st = self.effective_status(today)
        if st == self.Status.DRAFT:
            return not self.draft_expired(today) and self.remaining > 0
        return st in (self.Status.ORDERED, self.Status.PARTIAL) and self.remaining > 0

    @property
    def current_status(self):
        return self.effective_status()

    def get_current_status_display(self):
        return self.Status(self.current_status).label

    @property
    def counts_as_incoming(self):
        """Lô giao chậm không tính vào tồn dự kiến cho đến khi có ngày giao mới (AC-68); nháp quá hạn cũng không."""
        return self.is_incoming()

    def settle_status(self, today=None):
        today = today or timezone.localdate()
        if self.status == self.Status.CANCELLED:
            return
        if self.status == self.Status.DRAFT and self.received_quantity == 0:
            return
        if self.remaining == 0:
            self.status = self.Status.DELIVERED
        elif self.expected_date < today:
            self.status = self.Status.LATE
        elif self.received_quantity > 0:
            self.status = self.Status.PARTIAL
        else:
            self.status = self.Status.ORDERED


class Receipt(StoreScopedModel):
    """Phiếu nhập hàng (FR-24, BRU-33)."""

    class PaymentType(models.TextChoices):
        NOW = "tra_ngay", "Trả ngay"
        LATER = "tra_sau", "Trả sau"

    code = models.CharField("Mã phiếu", max_length=20, unique=True)
    supplier = models.ForeignKey(Supplier, verbose_name="Nhà cung cấp", on_delete=models.PROTECT,
                                 related_name="receipts")
    payment_type = models.CharField("Hình thức thanh toán", max_length=10, choices=PaymentType.choices)
    total = models.PositiveBigIntegerField("Giá trị nhập (đồng)", default=0)
    invoice_photo = models.FileField("Ảnh hóa đơn", upload_to="hoa-don-nhap/%Y/%m/", blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="Người lập", on_delete=models.PROTECT,
                                   related_name="+")
    operation_key = models.CharField("Mã nghiệp vụ", max_length=64, unique=True)

    class Meta:
        verbose_name = "Phiếu nhập"
        verbose_name_plural = "Phiếu nhập"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.code} · {self.supplier}"


class ReceiptLine(models.Model):
    receipt = models.ForeignKey(Receipt, verbose_name="Phiếu nhập", on_delete=models.PROTECT, related_name="lines")
    ingredient = models.ForeignKey(Ingredient, verbose_name="Nguyên vật liệu", on_delete=models.PROTECT,
                                   related_name="+")
    quantity = models.DecimalField("Số lượng thực nhận", max_digits=12, decimal_places=2)
    unit_price = models.PositiveBigIntegerField("Đơn giá (đồng theo đơn vị tính)")
    purchase_order = models.ForeignKey(PurchaseOrder, verbose_name="Lần đặt", on_delete=models.PROTECT, null=True,
                                       blank=True, related_name="receipt_lines")
    expiry_date = models.DateField("Hạn sử dụng của lô", null=True, blank=True)

    class Meta:
        verbose_name = "Dòng phiếu nhập"
        verbose_name_plural = "Dòng phiếu nhập"

    @property
    def value(self):
        return int((self.quantity * self.unit_price).to_integral_value())


class Payable(StoreScopedModel):
    """Khoản phải trả nhà cung cấp (BRU-33). Trả ngay thì ghi đủ thanh toán ngay khi lập phiếu."""

    receipt = models.OneToOneField(Receipt, verbose_name="Phiếu nhập", on_delete=models.PROTECT, related_name="payable")
    supplier = models.ForeignKey(Supplier, verbose_name="Nhà cung cấp", on_delete=models.PROTECT, related_name="+")
    amount = models.PositiveBigIntegerField("Số tiền")
    due_date = models.DateField("Hạn trả")

    class Meta:
        verbose_name = "Khoản phải trả"
        verbose_name_plural = "Khoản phải trả"
        ordering = ["due_date"]

    def paid(self):
        return sum(p.amount for p in self.payments.all())

    def remaining(self):
        return self.amount - self.paid()

    @property
    def is_paid(self):
        return self.remaining() <= 0


class SupplierPayment(TimeStampedModel):
    """Một lần thực chi cho khoản phải trả (BRU-33)."""

    class Source(models.TextChoices):
        SHIFT_CASH = "quy_ca", "Tiền mặt quỹ ca"
        TRANSFER = "chuyen_khoan", "Chuyển khoản"
        OWNER_CASH = "tien_mat_chu", "Tiền mặt của Chủ quán"

    payable = models.ForeignKey(Payable, verbose_name="Khoản phải trả", on_delete=models.PROTECT, related_name="payments")
    amount = models.PositiveBigIntegerField("Số tiền")
    paid_on = models.DateField("Ngày trả")
    source = models.CharField("Nguồn tiền", max_length=20, choices=Source.choices)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="Người ghi", on_delete=models.PROTECT,
                              related_name="+")

    class Meta:
        verbose_name = "Thanh toán nhà cung cấp"
        verbose_name_plural = "Thanh toán nhà cung cấp"


class StockCount(StoreScopedModel):
    """Kết quả kiểm kê một nguyên liệu (FR-25, BRU-25)."""

    class Status(models.TextChoices):
        APPLIED = "da_ap_dung", "Đã điều chỉnh tồn"
        PENDING = "cho_xac_nhan", "Chờ Chủ quán xác nhận"
        REJECTED = "tu_choi", "Chủ quán không xác nhận"

    ingredient = models.ForeignKey(Ingredient, verbose_name="Nguyên vật liệu", on_delete=models.PROTECT,
                                   related_name="counts")
    counted = models.DecimalField("Tồn thực tế đếm được", max_digits=12, decimal_places=2)
    physical_at_count = models.DecimalField("Tồn vật lý lúc đếm", max_digits=12, decimal_places=2)
    difference = models.DecimalField("Chênh lệch (thực tế - vật lý)", max_digits=12, decimal_places=2)
    percent = models.DecimalField("Tỷ lệ chênh lệch (%)", max_digits=7, decimal_places=2)
    threshold_percent = models.PositiveSmallIntegerField("Ngưỡng đã áp dụng (%)", null=True, blank=True)
    reason = models.CharField("Lý do", max_length=255, blank=True)
    status = models.CharField("Trạng thái", max_length=20, choices=Status.choices)
    counter = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="Người kiểm kê", on_delete=models.PROTECT,
                                related_name="+")
    confirmed_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="Người xác nhận", on_delete=models.PROTECT,
                                     null=True, blank=True, related_name="+")
    confirmed_at = models.DateTimeField("Xác nhận lúc", null=True, blank=True)
    operation_key = models.CharField("Mã nghiệp vụ", max_length=64, unique=True)

    class Meta:
        verbose_name = "Kiểm kê"
        verbose_name_plural = "Kiểm kê"
        ordering = ["-created_at"]


class Waste(StoreScopedModel):
    """Hao hụt xuất kho (FR-26, BRU-19): làm giảm tồn vật lý."""

    class Reason(models.TextChoices):
        DAMAGED = "hu_hong", "Hư hỏng"
        EXPIRED = "het_han", "Hết hạn"
        BROKEN = "do_vo", "Đổ vỡ"
        FAILED_PREP = "pha_hong", "Pha hỏng trước khi hoàn thành"
        OTHER = "khac", "Khác"

    ingredient = models.ForeignKey(Ingredient, verbose_name="Nguyên vật liệu", on_delete=models.PROTECT,
                                   related_name="wastes")
    quantity = models.DecimalField("Số lượng", max_digits=12, decimal_places=2,
                                   validators=[MinValueValidator(Decimal("0.01"))])
    reason = models.CharField("Lý do", max_length=20, choices=Reason.choices)
    note = models.CharField("Ghi chú", max_length=255, blank=True)
    is_one_off = models.BooleanField(
        "Sự cố đơn lẻ", default=False,
        help_text="Chủ quán đánh dấu: không tính vào tỷ lệ hao hụt thường lệ khi dự báo nhu cầu.")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="Người ghi", on_delete=models.PROTECT,
                              related_name="+")
    operation_key = models.CharField("Mã nghiệp vụ", max_length=64, unique=True)

    class Meta:
        verbose_name = "Hao hụt xuất kho"
        verbose_name_plural = "Hao hụt xuất kho"
        ordering = ["-created_at"]


class ConsumptionCheck(StoreScopedModel):
    """Kết quả đối chiếu tiêu hao một nguyên liệu trọng yếu giữa hai lần kiểm kê (FR-16, BRU-17)."""

    ingredient = models.ForeignKey(Ingredient, verbose_name="Nguyên vật liệu", on_delete=models.PROTECT,
                                   related_name="consumption_checks")
    from_count = models.ForeignKey(StockCount, verbose_name="Kiểm kê kỳ trước", on_delete=models.PROTECT,
                                   related_name="+")
    to_count = models.OneToOneField(StockCount, verbose_name="Kiểm kê kỳ này", on_delete=models.PROTECT,
                                    related_name="consumption_check")
    opening = models.DecimalField("Tồn kiểm kê kỳ trước", max_digits=14, decimal_places=2)
    receipts = models.DecimalField("Nhập trong kỳ", max_digits=14, decimal_places=2)
    closing = models.DecimalField("Tồn kiểm kê kỳ này", max_digits=14, decimal_places=2)
    waste = models.DecimalField("Hao hụt xuất kho", max_digits=14, decimal_places=2)
    actual = models.DecimalField("Tiêu hao thực tế", max_digits=14, decimal_places=2)
    by_orders = models.DecimalField("Tiêu hao theo đơn", max_digits=14, decimal_places=2)
    excess = models.DecimalField("Vượt (thực tế − theo đơn)", max_digits=14, decimal_places=2)
    percent = models.DecimalField("Tỷ lệ vượt (%)", max_digits=9, decimal_places=2)
    tolerance_percent = models.PositiveSmallIntegerField("Mức cho phép đã áp dụng (%)")
    over = models.BooleanField("Vượt mức cho phép", default=False)

    class Meta:
        verbose_name = "Đối chiếu tiêu hao"
        verbose_name_plural = "Đối chiếu tiêu hao"
        ordering = ["-created_at"]


class RecountRequest(StoreScopedModel):
    """Đề nghị kiểm kê lại một nguyên liệu khi đơn bị từ chối vì thiếu mà quầy cho rằng còn hàng (BRU-20, Bảng 5.4)."""

    ingredient = models.ForeignKey(Ingredient, verbose_name="Nguyên vật liệu", on_delete=models.PROTECT,
                                   related_name="recount_requests")
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="Người đề nghị", on_delete=models.PROTECT,
                                     related_name="+")
    shift = models.ForeignKey("shifts.Shift", verbose_name="Ca", on_delete=models.PROTECT, null=True, blank=True,
                              related_name="+")
    count = models.ForeignKey(StockCount, verbose_name="Lần kiểm kê đáp ứng", on_delete=models.PROTECT, null=True,
                              blank=True, related_name="recount_requests")
    done_at = models.DateTimeField("Đã kiểm kê lúc", null=True, blank=True)

    class Meta:
        verbose_name = "Đề nghị kiểm kê lại"
        verbose_name_plural = "Đề nghị kiểm kê lại"
        ordering = ["-created_at"]
        constraints = [models.UniqueConstraint(fields=["ingredient"], condition=models.Q(done_at__isnull=True),
                                               name="one_open_recount_per_ingredient")]

    def __str__(self):
        return f"Kiểm kê lại {self.ingredient.name}"
