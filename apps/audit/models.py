"""Nhật ký thao tác chỉ thêm mới (FR-61, BRU-40, NFR-08).

Không sửa, không xóa được ở ba lớp: model, QuerySet và trigger trong cơ sở dữ liệu.
"""

from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models


class ImmutableRecordError(Exception):
    """Bị ném khi có thao tác sửa hoặc xóa bản ghi chỉ thêm mới."""


class AppendOnlyQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ImmutableRecordError("Nhật ký thao tác không được sửa.")

    def delete(self):
        raise ImmutableRecordError("Nhật ký thao tác không được xóa.")


class Action(models.TextChoices):
    LOGIN = "login", "Đăng nhập"
    LOGOUT = "logout", "Đăng xuất"
    LOGIN_FAILED = "login_failed", "Đăng nhập thất bại"
    ACCOUNT_LOCKED = "account_locked", "Tạm khóa tài khoản do sai mật khẩu"
    ACCESS_DENIED = "access_denied", "Từ chối truy cập"
    CREATE = "create", "Tạo dữ liệu"
    UPDATE = "update", "Sửa dữ liệu"
    DELETE = "delete", "Xóa dữ liệu"
    PUBLISH_RECIPE = "publish_recipe", "Áp dụng phiên bản định mức"
    STATUS_CHANGE = "status_change", "Đổi trạng thái"


class AuditLog(models.Model):
    created_at = models.DateTimeField("Thời điểm", auto_now_add=True, db_index=True)
    store_code = models.CharField("Mã cửa hàng", max_length=20, db_index=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Người thực hiện",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    actor_label = models.CharField("Tên người thực hiện", max_length=150, blank=True)
    action = models.CharField("Thao tác", max_length=30, choices=Action.choices, db_index=True)
    object_type = models.CharField("Loại dữ liệu", max_length=100, blank=True, db_index=True)
    object_id = models.CharField("Mã bản ghi", max_length=64, blank=True)
    object_repr = models.CharField("Bản ghi", max_length=255, blank=True)
    before = models.JSONField("Trước", null=True, blank=True, encoder=DjangoJSONEncoder)
    after = models.JSONField("Sau", null=True, blank=True, encoder=DjangoJSONEncoder)
    reason = models.TextField("Lý do", blank=True)
    ip_address = models.GenericIPAddressField("Địa chỉ IP", null=True, blank=True)
    path = models.CharField("Đường dẫn", max_length=255, blank=True)

    objects = AppendOnlyQuerySet.as_manager()

    class Meta:
        verbose_name = "Nhật ký thao tác"
        verbose_name_plural = "Nhật ký thao tác"
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"{self.created_at:%d/%m/%Y %H:%M} · {self.actor_label} · {self.get_action_display()}"

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise ImmutableRecordError("Nhật ký thao tác không được sửa.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ImmutableRecordError("Nhật ký thao tác không được xóa.")
