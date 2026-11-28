"""Chi phí hằng tháng không đi qua quỹ ca (Hai, 28/11/2026): mặt bằng, điện nước, internet... để báo cáo Lãi lỗ trừ
đủ chi phí. Khoản chi trả bằng tiền trong két đã ghi ở quỹ ca thì không nhập lại ở đây."""

from django.conf import settings
from django.db import models

from apps.core.models import StoreScopedModel


class MonthlyExpense(StoreScopedModel):
    class Category(models.TextChoices):
        RENT = "mat_bang", "Mặt bằng"
        UTILITIES = "dien_nuoc", "Điện, nước, gas"
        INTERNET = "internet", "Internet, điện thoại, phần mềm"
        DEPRECIATION = "khau_hao", "Khấu hao máy móc, dụng cụ"
        MARKETING = "marketing", "Quảng cáo, khuyến mãi"
        SALARY_EXTRA = "luong_khac", "Lương, thưởng ngoài giờ công"
        OTHER = "khac", "Khác"

    month = models.DateField("Tháng", help_text="Ngày đầu tháng.")
    category = models.CharField("Loại chi phí", max_length=20, choices=Category.choices)
    amount = models.PositiveBigIntegerField("Số tiền (đồng)")
    note = models.CharField("Ghi chú", max_length=255, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="Người ghi", on_delete=models.PROTECT,
                                   related_name="+")

    class Meta:
        verbose_name = "Chi phí tháng"
        verbose_name_plural = "Chi phí tháng"
        ordering = ["month", "category", "pk"]

    def __str__(self):
        return f"{self.get_category_display()} {self.month:%m/%Y}"
