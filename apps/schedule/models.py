"""Đăng ký ca và lịch làm việc (FR-38, FR-39, BRU-28 đến BRU-30)."""

from datetime import datetime, time, timedelta

from django.conf import settings
from django.db import models

from apps.core.models import StoreScopedModel, TimeStampedModel


class WorkShift(StoreScopedModel):
    """Một ca làm việc trong lịch tuần (khác ca quỹ tiền của phần Ca và nhân sự)."""

    date = models.DateField("Ngày")
    name = models.CharField("Tên ca", max_length=40, help_text="Ví dụ: Ca sáng, Ca chiều, Ca tối.")
    start = models.TimeField("Bắt đầu")
    end = models.TimeField("Kết thúc")

    class Meta:
        verbose_name = "Ca làm việc trong lịch"
        verbose_name_plural = "Ca làm việc trong lịch"
        ordering = ["date", "start", "name"]
        constraints = [models.UniqueConstraint(fields=["date", "name"], name="uniq_workshift_name_per_day")]

    def __str__(self):
        return f"{self.name} {self.date:%d/%m} {self.start:%H:%M}–{self.end:%H:%M}"

    def _minutes(self):
        """(phút bắt đầu, phút kết thúc) trong ngày; ca kết thúc lúc 0 giờ là hết ngày (24 giờ)."""
        a = self.start.hour * 60 + self.start.minute
        b = self.end.hour * 60 + self.end.minute
        return a, (b if b > a else 24 * 60)

    @property
    def hours(self):
        a, b = self._minutes()
        return (b - a) / 60

    @property
    def end_datetime(self):
        """Lúc kết thúc ca (naive); ca kết thúc lúc 0 giờ thì là 0 giờ ngày hôm sau."""
        a, b = self._minutes()
        return datetime.combine(self.date, time.min) + timedelta(minutes=b)

    def overlaps(self, other):
        (a, b), (c, d) = self._minutes(), other._minutes()
        return self.date == other.date and a < d and c < b


class RoleNeed(models.Model):
    """Số người cần của một vị trí trong ca: số áp dụng do Chủ quán đặt, số gợi ý của hệ thống giữ để đối chiếu."""

    shift = models.ForeignKey(WorkShift, on_delete=models.CASCADE, related_name="needs")
    role = models.CharField("Vị trí", max_length=20)
    needed = models.PositiveSmallIntegerField("Số người cần")
    suggested = models.PositiveSmallIntegerField("Số người hệ thống gợi ý", null=True, blank=True)
    basis = models.JSONField("Căn cứ gợi ý", default=dict, blank=True)
    reason = models.CharField("Lý do khác gợi ý", max_length=255, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["shift", "role"], name="uniq_need_per_shift_role")]


class Registration(TimeStampedModel):
    """Nhân viên đăng ký làm một vị trí trong một ca (BRU-29: chỉ vị trí mình đảm nhận được)."""

    shift = models.ForeignKey(WorkShift, on_delete=models.CASCADE, related_name="registrations")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    role = models.CharField("Vị trí", max_length=20)
    cancelled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["shift", "user"], condition=models.Q(cancelled_at__isnull=True),
                                               name="one_active_registration_per_shift")]


class Assignment(TimeStampedModel):
    """Một người được xếp vào một vị trí của ca; xếp lại hay bỏ ra đều giữ dấu vết."""

    class Source(models.TextChoices):
        SUGGESTED = "goi_y", "Theo gợi ý"
        OWNER = "chu_quan", "Chủ quán xếp"

    shift = models.ForeignKey(WorkShift, on_delete=models.CASCADE, related_name="assignments")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    role = models.CharField("Vị trí", max_length=20)
    source = models.CharField(max_length=10, choices=Source.choices)
    assigned_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    removed_at = models.DateTimeField(null=True, blank=True)
    remove_reason = models.CharField(max_length=255, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["shift", "user"], condition=models.Q(removed_at__isnull=True),
                                               name="one_active_assignment_per_shift")]


class WeekPublish(TimeStampedModel):
    """Lần công bố lịch một tuần (AC-88); giữ các chỗ còn thiếu lúc công bố."""

    week_start = models.DateField("Tuần bắt đầu (thứ Hai)")
    published_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    gaps = models.JSONField("Chỗ còn thiếu lúc công bố", default=list)

    class Meta:
        ordering = ["-created_at"]
