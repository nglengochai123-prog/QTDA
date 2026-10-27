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

    def effective_roles(self):
        """Vai trò hiện trên hồ sơ: các vai trò đã chọn, cộng Chủ quán nếu tài khoản tạo với vai trò chính Chủ quán."""
        roles = list(self.roles or [])
        if self.user_id and self.user.role == Role.CHU_QUAN and Role.CHU_QUAN not in roles:
            roles.insert(0, Role.CHU_QUAN)
        return roles

    def role_labels(self):
        roles = self.effective_roles()
        return ", ".join(label for value, label in Role.choices if value in roles)
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


class Attendance(StoreScopedModel):
    """Một lượt chấm công: vào ca, ra ca, vai trò làm việc (FR-35, BRU-31)."""

    user = models.ForeignKey(User, verbose_name="Nhân viên", on_delete=models.PROTECT, related_name="attendances")
    role = models.CharField("Vai trò làm việc", max_length=20, choices=Role.choices)
    clock_in = models.DateTimeField("Vào ca lúc")
    clock_out = models.DateTimeField("Ra ca lúc", null=True, blank=True)
    out_supplemented_by = models.ForeignKey(User, verbose_name="Người bổ sung giờ ra", on_delete=models.PROTECT,
                                            null=True, blank=True, related_name="+")
    out_reason = models.CharField("Lý do bổ sung giờ ra", max_length=255, blank=True)

    class Meta:
        verbose_name = "Lượt chấm công"
        verbose_name_plural = "Chấm công"
        ordering = ["-clock_in"]
        constraints = [models.UniqueConstraint(fields=["user"], condition=models.Q(clock_out__isnull=True),
                                               name="one_open_attendance_per_user")]

    def __str__(self):
        return f"{self.user} · {self.get_role_display()} · {self.clock_in:%d/%m}"
