"""Danh mục bàn, nhóm món, món, kích cỡ, giá và tùy chọn (FR-60, BRU-20, BRU-39).

Giá lưu tại kích cỡ và tùy chọn. Dòng đơn (làm ở phần sau) sẽ chép giá lúc tạo đơn,
nên đổi giá chỉ áp dụng cho đơn tạo sau thời điểm đổi (AC-114).
"""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from apps.core.models import StoreScopedModel, TimeStampedModel


class Table(StoreScopedModel):
    code = models.CharField("Số bàn", max_length=20)
    area = models.CharField("Khu vực", max_length=60, blank=True)
    seats = models.PositiveSmallIntegerField("Số chỗ", default=4)
    is_active = models.BooleanField("Đang dùng", default=True)
    sort_order = models.PositiveSmallIntegerField("Thứ tự", default=0)

    class Meta:
        verbose_name = "Bàn"
        verbose_name_plural = "Bàn"
        ordering = ["sort_order", "code"]
        constraints = [models.UniqueConstraint(fields=["store", "code"], name="uniq_table_code_per_store")]

    def __str__(self):
        return f"Bàn {self.code}"


class MenuGroup(StoreScopedModel):
    name = models.CharField("Tên nhóm", max_length=80)
    load_factor = models.DecimalField(
        "Hệ số tải", max_digits=4, decimal_places=2, default=Decimal("1.00"),
        validators=[MinValueValidator(Decimal("0.10"))],
        help_text="Khối lượng công việc tương đối của một món trong nhóm, dùng để đo tải.",
    )
    is_active = models.BooleanField("Đang dùng", default=True)
    sort_order = models.PositiveSmallIntegerField("Thứ tự", default=0)

    class Meta:
        verbose_name = "Nhóm món"
        verbose_name_plural = "Nhóm món"
        ordering = ["sort_order", "name"]
        constraints = [models.UniqueConstraint(fields=["store", "name"], name="uniq_menugroup_name_per_store")]

    def __str__(self):
        return self.name


class OptionGroup(StoreScopedModel):
    class Selection(models.TextChoices):
        SINGLE = "single", "Chọn một"
        MULTIPLE = "multiple", "Chọn nhiều"

    name = models.CharField("Tên nhóm tùy chọn", max_length=80, help_text="Ví dụ: Đường, Đá, Topping.")
    selection = models.CharField("Cách chọn", max_length=10, choices=Selection.choices, default=Selection.SINGLE)
    is_required = models.BooleanField("Bắt buộc chọn", default=False)

    class Meta:
        verbose_name = "Nhóm tùy chọn"
        verbose_name_plural = "Nhóm tùy chọn"
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["store", "name"], name="uniq_optiongroup_name_per_store")]

    def __str__(self):
        return self.name


class Option(TimeStampedModel):
    group = models.ForeignKey(OptionGroup, verbose_name="Nhóm", on_delete=models.CASCADE, related_name="options")
    name = models.CharField("Tùy chọn", max_length=80)
    extra_price = models.PositiveIntegerField("Giá cộng thêm (đồng)", default=0)
    no_ingredients = models.BooleanField(
        "Không dùng nguyên liệu", default=False,
        help_text="Đánh dấu khi tùy chọn không tiêu hao nguyên liệu theo dõi (ví dụ: Ít đá).",
    )
    is_active = models.BooleanField("Đang dùng", default=True)
    sort_order = models.PositiveSmallIntegerField("Thứ tự", default=0)

    class Meta:
        verbose_name = "Tùy chọn"
        verbose_name_plural = "Tùy chọn"
        ordering = ["group", "sort_order", "name"]
        constraints = [models.UniqueConstraint(fields=["group", "name"], name="uniq_option_name_per_group")]

    def __str__(self):
        return f"{self.group.name}: {self.name}"

    def save(self, *args, **kwargs):
        changed = self.pk is None or Option.objects.filter(pk=self.pk).exclude(extra_price=self.extra_price).exists()
        super().save(*args, **kwargs)
        if changed:
            PriceRecord.objects.create(option=self, price=self.extra_price)


class MenuItemQuerySet(models.QuerySet):
    def sellable(self):
        """Món được hiện trên màn hình tạo đơn."""
        return self.filter(status=MenuItem.Status.ON_SALE, group__is_active=True)


class MenuItem(StoreScopedModel):
    class Status(models.TextChoices):
        DRAFT = "nhap", "Đang soạn"
        ON_SALE = "dang_ban", "Đang bán"
        STOPPED = "ngung_ban", "Ngừng bán"

    group = models.ForeignKey(MenuGroup, verbose_name="Nhóm món", on_delete=models.PROTECT, related_name="items")
    name = models.CharField("Tên món", max_length=120)
    status = models.CharField("Trạng thái", max_length=20, choices=Status.choices, default=Status.DRAFT)
    no_ingredients = models.BooleanField(
        "Không dùng nguyên liệu", default=False,
        help_text="Chỉ đánh dấu với món không tiêu hao nguyên liệu (BRU-20).",
    )
    option_groups = models.ManyToManyField(OptionGroup, verbose_name="Nhóm tùy chọn áp dụng", blank=True,
                                           related_name="items")
    sort_order = models.PositiveSmallIntegerField("Thứ tự", default=0)

    objects = MenuItemQuerySet.as_manager()

    class Meta:
        verbose_name = "Món"
        verbose_name_plural = "Món"
        ordering = ["sort_order", "name"]
        constraints = [models.UniqueConstraint(fields=["store", "name"], name="uniq_menuitem_name_per_store")]

    def __str__(self):
        return self.name

    def active_sizes(self):
        return self.sizes.filter(is_active=True)

    def active_options(self):
        if self.pk is None:
            return Option.objects.none()
        return Option.objects.filter(group__in=self.option_groups.all(), is_active=True)

    def sale_blockers(self):
        """Lý do chưa mở bán được; danh sách rỗng là đủ điều kiện (BRU-20, AC-47)."""
        if self.pk is None:
            return ["lưu món và khai báo kích cỡ trước"]
        if not self.active_sizes().exists():
            return ["kích cỡ và giá bán"]
        from apps.inventory.services import recipe_gaps

        no_price = [f"giá bán cỡ {s.name}" for s in self.active_sizes() if not s.price]
        return no_price + recipe_gaps(self)

    def clean(self):
        if self.status == self.Status.ON_SALE:
            blockers = self.sale_blockers()
            if blockers:
                raise ValidationError({"status": "Chưa mở bán được. Còn thiếu: " + "; ".join(blockers) + "."})


class ItemSize(TimeStampedModel):
    item = models.ForeignKey(MenuItem, verbose_name="Món", on_delete=models.CASCADE, related_name="sizes")
    name = models.CharField("Kích cỡ", max_length=20, help_text="Ví dụ: M, L. Món một cỡ thì ghi Chuẩn.")
    price = models.PositiveIntegerField("Giá bán (đồng)")
    is_active = models.BooleanField("Đang bán", default=True)
    sort_order = models.PositiveSmallIntegerField("Thứ tự", default=0)

    class Meta:
        verbose_name = "Kích cỡ và giá"
        verbose_name_plural = "Kích cỡ và giá"
        ordering = ["item", "sort_order", "name"]
        constraints = [models.UniqueConstraint(fields=["item", "name"], name="uniq_size_name_per_item")]

    def __str__(self):
        return f"{self.item.name} {self.name}"

    def save(self, *args, **kwargs):
        changed = self.pk is None or ItemSize.objects.filter(pk=self.pk).exclude(price=self.price).exists()
        super().save(*args, **kwargs)
        if changed:
            PriceRecord.objects.create(size=self, price=self.price)


def _now():
    return timezone.now()


class PriceRecord(models.Model):
    """Lịch sử giá bán của kích cỡ và giá cộng thêm của tùy chọn (BRU-39).

    Mỗi lần tạo hoặc đổi giá thêm một dòng có "hiệu lực từ"; không sửa, không xóa. Dùng để tính
    đúng giá khi nhập bù phiếu dự phòng theo thời điểm bán thực tế.
    """

    size = models.ForeignKey(ItemSize, verbose_name="Kích cỡ", on_delete=models.CASCADE, null=True, blank=True,
                             related_name="price_records")
    option = models.ForeignKey(Option, verbose_name="Tùy chọn", on_delete=models.CASCADE, null=True, blank=True,
                               related_name="price_records")
    price = models.PositiveIntegerField("Giá (đồng)")
    effective_from = models.DateTimeField("Hiệu lực từ", default=_now)

    class Meta:
        verbose_name = "Lịch sử giá"
        verbose_name_plural = "Lịch sử giá"
        ordering = ["-effective_from", "-id"]

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValueError("Lịch sử giá không sửa được.")
        super().save(*args, **kwargs)


def price_at(size, options, at):
    """Đơn giá (kích cỡ + tùy chọn) có hiệu lực tại `at`; None nếu thiếu lịch sử cho bất kỳ phần nào."""
    def one(qs):
        return qs.filter(effective_from__lte=at).order_by("-effective_from", "-id").values_list("price", flat=True).first()

    total = one(PriceRecord.objects.filter(size=size))
    if total is None:
        return None
    for option in options:
        extra = one(PriceRecord.objects.filter(option=option))
        if extra is None:
            return None
        total += extra
    return total
