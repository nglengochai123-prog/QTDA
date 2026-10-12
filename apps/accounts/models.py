from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone

from apps.core.models import Store


class Role(models.TextChoices):
    """Năm vai trò theo Bảng 5.3 của BRD."""

    CHU_QUAN = "chu_quan", "Chủ quán"
    QUAN_LY_CA = "quan_ly_ca", "Quản lý ca (đã bỏ)"
    THU_NGAN = "thu_ngan", "Thu ngân"
    PHUC_VU = "phuc_vu", "Phục vụ"
    PHA_CHE = "pha_che", "Pha chế"


# Vai trò còn dùng: bỏ Quản lý ca theo quyết định của Chủ quán ngày 12/10/2026; giá trị cũ giữ cho dữ liệu lịch sử.
ACTIVE_ROLES = [(v, l) for v, l in Role.choices if v != Role.QUAN_LY_CA]


class User(AbstractUser):
    role = models.CharField("Vai trò chính", max_length=20, choices=Role.choices, default=Role.PHUC_VU)
    store = models.ForeignKey(
        Store,
        verbose_name="Cửa hàng",
        on_delete=models.PROTECT,
        related_name="users",
        null=True,
        blank=True,
    )
    failed_login_count = models.PositiveSmallIntegerField("Số lần sai mật khẩu liên tiếp", default=0)
    locked_until = models.DateTimeField("Tạm khóa đến", null=True, blank=True)

    class Meta:
        verbose_name = "Tài khoản"
        verbose_name_plural = "Tài khoản"

    def __str__(self):
        return self.get_full_name() or self.username

    @property
    def given_name(self):
        """Tên gọi theo thói quen Việt: chữ cuối của họ tên (Nguyễn Văn An → An)."""
        full = self.get_full_name().split()
        return full[-1] if full else self.username

    def get_short_name(self):
        return self.given_name

    # --- Vai trò ---------------------------------------------------------------

    @property
    def roles(self):
        """Tập vai trò của tài khoản: vai trò chính và các vai trò ghi trong hồ sơ nhân viên."""
        if self.is_superuser:
            return {Role.CHU_QUAN}
        result = {self.role}
        employee = getattr(self, "employee", None)
        if employee is not None and employee.is_working:
            result.update(employee.roles or [])
        return result

    @property
    def is_owner(self):
        return self.is_authenticated and Role.CHU_QUAN in self.roles

    def has_role(self, *roles):
        return self.is_authenticated and self.is_active and bool(self.roles.intersection(roles))

    def role_labels(self):
        return [label for value, label in Role.choices if value in self.roles]

    # --- Tạm khóa khi sai mật khẩu nhiều lần ------------------------------------

    @property
    def is_temporarily_locked(self):
        return self.locked_until is not None and self.locked_until > timezone.now()

    def register_failed_login(self):
        """Tăng số lần sai; đủ ngưỡng thì tạm khóa. Trả về True nếu vừa bị khóa."""
        self.failed_login_count += 1
        just_locked = False
        if self.failed_login_count >= settings.LOGIN_MAX_FAILED_ATTEMPTS:
            self.locked_until = timezone.now() + timedelta(minutes=settings.LOGIN_LOCK_MINUTES)
            self.failed_login_count = 0
            just_locked = True
        User.objects.filter(pk=self.pk).update(
            failed_login_count=self.failed_login_count, locked_until=self.locked_until
        )
        return just_locked

    def reset_failed_logins(self):
        if self.failed_login_count or self.locked_until:
            self.failed_login_count = 0
            self.locked_until = None
            User.objects.filter(pk=self.pk).update(failed_login_count=0, locked_until=None)

    def save(self, *args, **kwargs):
        if self.store_id is None:
            self.store = Store.get_default()
        # Chỉ Chủ quán vào được trang quản trị dữ liệu nền.
        self.is_staff = self.is_superuser or self.role == Role.CHU_QUAN
        super().save(*args, **kwargs)
