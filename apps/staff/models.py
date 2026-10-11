"""Hồ sơ nhân viên (FR-34, BRU-38)."""

from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models, transaction

from apps.accounts.models import Role, User
from apps.core.models import StoreScopedModel

phone_validator = RegexValidator(r"^0\d{9,10}$", "Số điện thoại gồm 10 hoặc 11 chữ số, bắt đầu bằng 0.")


class EmploymentStatus(models.TextChoices):
    WORKING = "dang_lam", "Đang làm việc"
    LEFT = "nghi_viec", "Nghỉ việc"


class Employee(StoreScopedModel):
    full_name = models.CharField("Họ tên", max_length=120)
    phone = models.CharField("Số điện thoại", max_length=11, unique=True, validators=[phone_validator])
    roles = models.JSONField("Vai trò đảm nhận được", default=list)
    hourly_wage = models.PositiveIntegerField("Đơn giá lương giờ (đồng)", default=0)
    status = models.CharField("Trạng thái", max_length=20, choices=EmploymentStatus.choices,
                              default=EmploymentStatus.WORKING)
    user = models.OneToOneField(User, verbose_name="Tài khoản liên kết", on_delete=models.PROTECT,
                                related_name="employee")

    class Meta:
        verbose_name = "Hồ sơ nhân viên"
        verbose_name_plural = "Hồ sơ nhân viên"
        ordering = ["full_name"]

    def __str__(self):
        return self.full_name

    @property
    def is_working(self):
        return self.status == EmploymentStatus.WORKING

    def role_labels(self):
        return ", ".join(label for value, label in Role.choices if value in (self.roles or []))
    role_labels.short_description = "Vai trò"

    def clean(self):
        valid = set(Role.values)
        if not self.roles:
            raise ValidationError({"roles": "Chọn ít nhất một vai trò."})
        if not set(self.roles) <= valid:
            raise ValidationError({"roles": "Vai trò không hợp lệ."})

    @transaction.atomic
    def save(self, *args, **kwargs):
        if self.store_id is None and self.user_id:
            self.store = self.user.store
        super().save(*args, **kwargs)
        # BRU-38: nghỉ việc thì khóa tài khoản ngay; quay lại thì mở.
        should_be_active = self.is_working
        if self.user.is_active != should_be_active:
            self.user.is_active = should_be_active
            self.user.save(update_fields=["is_active", "is_staff"])

    @classmethod
    @transaction.atomic
    def create_with_account(cls, *, full_name, phone, roles, hourly_wage=0, username=None,
                            status=EmploymentStatus.WORKING):
        """Tạo hồ sơ cùng tài khoản riêng (mỗi nhân viên một tài khoản, BRU-38).

        Tài khoản chưa có mật khẩu dùng được; Chủ quán đặt mật khẩu ở trang Tài khoản.
        """
        employee = cls(full_name=full_name, phone=phone, roles=list(roles),
                       hourly_wage=hourly_wage, status=status)
        employee.full_clean(exclude=["user", "store"])
        employee.attach_new_account(username)
        employee.save()
        return employee

    def attach_new_account(self, username=None):
        parts = self.full_name.strip().split()
        user = User(
            username=username or self.phone,
            first_name=" ".join(parts[:-1]),
            last_name=parts[-1] if parts else "",
            role=self.roles[0],
        )
        user.set_unusable_password()
        user.save()
        self.user = user
        self.store = user.store
