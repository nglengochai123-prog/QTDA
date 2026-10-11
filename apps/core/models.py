from django.conf import settings
from django.db import models


class TimeStampedModel(models.Model):
    """Lớp nền cho mọi bảng nghiệp vụ: thời điểm tạo và cập nhật."""

    created_at = models.DateTimeField("Tạo lúc", auto_now_add=True)
    updated_at = models.DateTimeField("Cập nhật lúc", auto_now=True)

    class Meta:
        abstract = True


class Store(TimeStampedModel):
    """Cửa hàng. Hiện chỉ có một quán, nhưng mọi bảng chính gắn mã cửa hàng (NFR-18)."""

    code = models.CharField("Mã cửa hàng", max_length=20, unique=True)
    name = models.CharField("Tên cửa hàng", max_length=120)
    address = models.CharField("Địa chỉ", max_length=255, blank=True)
    is_active = models.BooleanField("Đang hoạt động", default=True)

    class Meta:
        verbose_name = "Cửa hàng"
        verbose_name_plural = "Cửa hàng"
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} - {self.name}"

    @classmethod
    def get_default(cls):
        store, _ = cls.objects.get_or_create(
            code=settings.LAM_STORE_CODE,
            defaults={"name": settings.LAM_STORE_NAME},
        )
        return store


class StoreScopedModel(TimeStampedModel):
    """Lớp nền cho các bảng dữ liệu chính thuộc về một cửa hàng."""

    store = models.ForeignKey(
        Store,
        verbose_name="Cửa hàng",
        on_delete=models.PROTECT,
        related_name="+",
    )

    class Meta:
        abstract = True


class OperationRecord(models.Model):
    """Mã nghiệp vụ của mỗi yêu cầu thay đổi dữ liệu (NFR-04).

    Gửi lại cùng mã và cùng nội dung thì trả kết quả cũ; cùng mã khác nội dung thì bị từ chối.
    Bản ghi được tạo trong cùng giao dịch với dữ liệu nghiệp vụ.
    """

    key = models.CharField("Mã nghiệp vụ", max_length=64, unique=True)
    kind = models.CharField("Loại thao tác", max_length=40)
    payload_hash = models.CharField("Dấu nội dung", max_length=64)
    result = models.JSONField("Kết quả", default=dict)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="Người gửi", on_delete=models.PROTECT,
                              null=True, blank=True, related_name="+")
    created_at = models.DateTimeField("Thời điểm", auto_now_add=True)

    class Meta:
        verbose_name = "Mã nghiệp vụ"
        verbose_name_plural = "Mã nghiệp vụ"

    def __str__(self):
        return f"{self.kind} {self.key}"


class ParameterValue(models.Model):
    """Một lần đặt giá trị tham số kèm thời điểm hiệu lực (NFR-14).

    Không sửa, không xóa: đổi giá trị là thêm một dòng mới, nên luôn biết tại một thời điểm
    bất kỳ tham số nào đang áp dụng và báo cáo đã khóa không bị tính lại.
    """

    key = models.CharField("Tham số", max_length=60)
    value = models.BigIntegerField("Giá trị")
    effective_from = models.DateTimeField("Hiệu lực từ")
    set_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="Người đặt", on_delete=models.PROTECT,
                               null=True, blank=True, related_name="+")
    reason = models.CharField("Lý do", max_length=255, blank=True)
    created_at = models.DateTimeField("Ghi lúc", auto_now_add=True)

    class Meta:
        verbose_name = "Giá trị tham số"
        verbose_name_plural = "Lịch sử tham số"
        ordering = ["key", "-effective_from", "-id"]
        indexes = [models.Index(fields=["key", "effective_from"])]

    def __str__(self):
        from .params import DEFAULTS

        return f"{DEFAULTS.get(self.key, (None, '', self.key))[2]} = {self.value}"

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValueError("Giá trị tham số đã ghi không được sửa; hãy thêm giá trị mới.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("Không xóa lịch sử tham số.")
