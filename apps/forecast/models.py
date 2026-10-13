"""Dữ liệu của phần dự báo nhu cầu và hỗ trợ quyết định đặt hàng (FR-28, FR-29, FR-31, khung lý thuyết dự án)."""

from django.conf import settings
from django.db import models

from apps.core.models import StoreScopedModel, TimeStampedModel


class DayType(models.TextChoices):
    WEEKDAY = "ngay_thuong", "Ngày thường (thứ Hai đến thứ Sáu)"
    WEEKEND = "cuoi_tuan", "Cuối tuần (thứ Bảy, Chủ nhật)"


class ExpertJudgement(StoreScopedModel):
    """Nhận định của Chủ quán về số ly bán của một món-kích cỡ trong một loại ngày (mục 2.1 khung lý thuyết).

    Chỉ thêm, không sửa: nhận định mới thay nhận định cũ cùng món-kích cỡ và loại ngày, bản cũ giữ để truy vết.
    """

    size = models.ForeignKey("catalog.ItemSize", verbose_name="Món và kích cỡ", on_delete=models.PROTECT,
                             related_name="judgements")
    day_type = models.CharField("Loại ngày", max_length=20, choices=DayType.choices)
    typical = models.DecimalField("Số ly điển hình một ngày", max_digits=8, decimal_places=1)
    low = models.DecimalField("Ngày bán ít (khoảng 1 trong 10 ngày thấp hơn)", max_digits=8, decimal_places=1)
    high = models.DecimalField("Ngày bán nhiều (khoảng 1 trong 10 ngày cao hơn)", max_digits=8, decimal_places=1)
    basis = models.TextField("Căn cứ của nhận định", help_text="Ví dụ: lượng nhập hàng 4 tuần gần đây, sổ bán tay.")
    context = models.CharField("Bối cảnh áp dụng", max_length=200, blank=True,
                               help_text="Ví dụ: mùa khai giảng, sau khi đổi giá.")
    based_on_system_history = models.BooleanField(
        "Nhận định dựa trên chính số bán đã có trong hệ thống", default=False,
        help_text="Nếu có, hệ thống không dùng nhận định này làm bằng chứng độc lập (tránh tính một thông tin hai lần).")
    provided_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="Người cung cấp", on_delete=models.PROTECT,
                                    related_name="+")
    superseded_at = models.DateTimeField("Bị thay lúc", null=True, blank=True)

    class Meta:
        verbose_name = "Nhận định của Chủ quán"
        verbose_name_plural = "Nhận định của Chủ quán"
        ordering = ["size__item__name", "size__sort_order", "day_type", "-created_at"]

    def __str__(self):
        return f"{self.size.item.name} {self.size.name} · {self.get_day_type_display().split(' (')[0]}"

    def clean(self):
        from django.core.exceptions import ValidationError

        if self.low is not None and self.high is not None and self.typical is not None:
            if not (self.low <= self.typical <= self.high):
                raise ValidationError("Số ly điển hình phải nằm giữa ngày bán ít và ngày bán nhiều.")
            if self.low < 0:
                raise ValidationError("Số ly không âm.")


class ForecastRelease(TimeStampedModel):
    """Một lần phát hành dự báo; giữ nguyên để sau này đánh giá đúng khả năng dự báo tại thời điểm phát hành (mục 6.1)."""

    issued_at = models.DateTimeField("Phát hành lúc", db_index=True)
    first_day = models.DateField("Ngày đầu tiên được dự báo")
    horizon_days = models.PositiveSmallIntegerField("Số ngày dự báo")
    model_version = models.CharField("Phiên bản mô hình", max_length=40)
    data_version = models.CharField("Phiên bản dữ liệu (mã băm các ngày đủ điều kiện)", max_length=64)
    parameters = models.JSONField("Tham số dùng khi phát hành", default=dict)
    issued_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="Người chạy", on_delete=models.PROTECT,
                                  null=True, blank=True, related_name="+")

    class Meta:
        verbose_name = "Lần phát hành dự báo"
        verbose_name_plural = "Lần phát hành dự báo"
        ordering = ["-issued_at"]

    def __str__(self):
        return f"Dự báo phát hành {self.issued_at:%H:%M %d/%m/%Y}"


class SeriesForecast(models.Model):
    """Dự báo số ly của một món-kích cỡ trong một lần phát hành."""

    release = models.ForeignKey(ForecastRelease, on_delete=models.CASCADE, related_name="series")
    size = models.ForeignKey("catalog.ItemSize", on_delete=models.PROTECT, related_name="+")
    method = models.CharField("Cách tính đang áp dụng", max_length=20)
    eligible_days = models.PositiveIntegerField("Số ngày đủ điều kiện đã học")
    flagged_days = models.PositiveIntegerField("Số ngày bị loại (thiếu hàng)", default=0)
    prior_days = models.FloatField("Sức nặng nhận định (ngày tương đương)", null=True)
    prior_capped = models.BooleanField(default=False)
    daily = models.JSONField("Từng ngày: kỳ vọng, phân vị 10/50/90 của mô hình và của nhận định", default=list)
    totals = models.JSONField("Tổng nhiều ngày (mô phỏng)", default=dict)
    limitations = models.JSONField("Hạn chế cần công bố", default=list)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["release", "size"], name="uniq_series_per_release")]


class IngredientForecast(models.Model):
    """Nhu cầu nguyên vật liệu quy từ dự báo số ly qua định mức đang áp dụng (mục 6.2)."""

    release = models.ForeignKey(ForecastRelease, on_delete=models.CASCADE, related_name="ingredients")
    ingredient = models.ForeignKey("inventory.Ingredient", on_delete=models.PROTECT, related_name="+")
    daily = models.JSONField("Từng ngày: kỳ vọng và phân vị 10/90", default=list)
    paths_sample = models.JSONField("Tổng tích lũy theo ngày của một mẫu đường mô phỏng", default=list)
    methods = models.JSONField("Cách tính của các món góp phần", default=dict)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["release", "ingredient"], name="uniq_ingredient_per_release")]


class MethodDecision(StoreScopedModel):
    """Chủ quán chọn cách tính dùng cho đặt hàng của một món-kích cỡ (BRU-21, BRU-37, NFR-22).

    Mặc định là Ước tính ban đầu (nhận định Chủ quán). Chỉ chuyển sang mô hình khi Chủ quán xác nhận kèm kết quả
    đánh giá ngoài mẫu; bản ghi giữ lại căn cứ đánh giá lúc quyết định.
    """

    class Method(models.TextChoices):
        OWNER = "uoc_tinh", "Ước tính ban đầu"
        MODEL = "bayes", "Mô hình Bayes động"

    size = models.ForeignKey("catalog.ItemSize", on_delete=models.PROTECT, related_name="+")
    method = models.CharField("Cách tính", max_length=20, choices=Method.choices)
    evidence = models.JSONField("Kết quả đánh giá lúc quyết định", default=dict)
    note = models.CharField("Ghi chú", max_length=255, blank=True)
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")

    class Meta:
        ordering = ["-created_at"]


class OrderSuggestion(StoreScopedModel):
    """Đề xuất số lượng đặt (BRU-24) cùng quyết định cuối cùng của Chủ quán (NFR-22: lưu cả hai).

    Đề xuất từ kế hoạch nguyên liệu (thiết kế mua nguyên liệu mục 9.2) gắn với bản tính `plan`; đề xuất cũ gắn với lần
    phát hành dự báo theo món `release`."""

    class Decision(models.TextChoices):
        ACCEPT = "chap_nhan", "Chấp nhận"
        EDIT = "sua", "Sửa rồi chấp nhận"
        SKIP = "bo_qua", "Bỏ qua"

    release = models.ForeignKey(ForecastRelease, on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    plan = models.ForeignKey("forecast.IngredientPlan", verbose_name="Bản tính", on_delete=models.PROTECT, null=True,
                             blank=True, related_name="decisions")
    decision = models.CharField("Quyết định", max_length=12, choices=Decision.choices, blank=True)
    ingredient = models.ForeignKey("inventory.Ingredient", on_delete=models.PROTECT, related_name="+")
    components = models.JSONField("Các thành phần của phép tính", default=dict)
    suggested_quantity = models.DecimalField("Số lượng đề xuất", max_digits=12, decimal_places=2)
    final_quantity = models.DecimalField("Số lượng thực đặt", max_digits=12, decimal_places=2, null=True, blank=True)
    purchase_order = models.OneToOneField("inventory.PurchaseOrder", on_delete=models.PROTECT, null=True, blank=True,
                                          related_name="suggestion")
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
                                   related_name="+")
    decision_note = models.CharField("Lý do khác đề xuất", max_length=255, blank=True)

    class Meta:
        ordering = ["-created_at"]


class HistoryBatch(TimeStampedModel):
    """Một lần nhập lịch sử bán từ tệp (mục 6.1: lưu riêng lịch sử thật và dữ liệu mô phỏng với dữ liệu hệ thống)."""

    class Kind(models.TextChoices):
        REAL = "thuc_te", "Lịch sử bán thật của quán"
        SIMULATED = "mo_phong", "Dữ liệu mô phỏng (chỉ để kiểm tra phần mềm)"

    kind = models.CharField("Loại dữ liệu", max_length=10, choices=Kind.choices)
    file_name = models.CharField("Tệp", max_length=200)
    note = models.CharField("Ghi chú", max_length=255, blank=True)
    imported_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    summary = models.JSONField("Tóm tắt", default=dict)
    active = models.BooleanField("Đang dùng", default=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.file_name} ({self.get_kind_display()})"


class HistoricalSale(models.Model):
    """Số ly đã bán của một món-kích cỡ trong một ngày, từ tệp nhập (trước khi dùng hệ thống)."""

    batch = models.ForeignKey(HistoryBatch, on_delete=models.CASCADE, related_name="sales")
    date = models.DateField("Ngày")
    size = models.ForeignKey("catalog.ItemSize", on_delete=models.PROTECT, related_name="+")
    cups = models.PositiveIntegerField("Số ly")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["batch", "date", "size"], name="uniq_hist_sale")]


class HistoricalDay(models.Model):
    """Trạng thái một ngày trong tệp nhập: mở cửa (đủ điều kiện), đóng cửa, hay thiếu hàng."""

    class Status(models.TextChoices):
        OPEN = "mo_cua", "Mở cửa, số liệu đủ"
        CLOSED = "dong_cua", "Đóng cửa"
        SHORT = "thieu_hang", "Thiếu hàng (số bán bị giới hạn)"

    batch = models.ForeignKey(HistoryBatch, on_delete=models.CASCADE, related_name="days")
    date = models.DateField("Ngày")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.OPEN)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["batch", "date"], name="uniq_hist_day")]


class SeriesConfig(models.Model):
    """Cấu hình mô hình của một món-kích cỡ do đánh giá đề xuất (hệ số thích nghi, nhiễu quan sát).

    Chỉ dùng khi phát hành sau khi Chủ quán xác nhận dùng mô hình (mục 6.1: cấu hình chưa có bằng chứng giữ ở trạng
    thái thử nghiệm)."""

    size = models.OneToOneField("catalog.ItemSize", on_delete=models.CASCADE, related_name="+")
    delta_level = models.FloatField()
    obs_var = models.FloatField(default=0.0)
    evidence = models.JSONField(default=dict)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, related_name="+")
    approved_at = models.DateTimeField(null=True)


class IngredientDailyUsage(models.Model):
    """Chuỗi tiêu hao một nguyên liệu trong một ngày (thiết kế mua nguyên liệu mục 5), dựng lại mỗi lần tính toàn bộ.

    `sales` là tiêu hao của ly có tính tiền quy theo định mức hiện hành (U b), `sales_as_sold` theo lượng chụp trên dòng
    đơn lúc bán; `voided` là ly đã pha rồi hủy (U h). Hao hụt vận hành và hao hụt do tồn kho tách riêng. Cờ ngày quyết
    định ngày có được dùng để học và đo sai số hay không.
    """

    class Source(models.TextChoices):
        SYSTEM = "he_thong", "Dữ liệu bán trên hệ thống"
        IMPORTED = "tep", "Lịch sử bán nhập từ tệp"

    ingredient = models.ForeignKey("inventory.Ingredient", on_delete=models.CASCADE, related_name="daily_usage")
    date = models.DateField("Ngày")
    source = models.CharField("Nguồn", max_length=10, choices=Source.choices, default=Source.SYSTEM)
    day_status = models.CharField("Trạng thái ngày", max_length=14)
    sales = models.FloatField("Tiêu hao bán hàng theo định mức hiện hành", default=0)
    sales_as_sold = models.FloatField("Tiêu hao bán hàng theo định mức lúc bán", default=0)
    voided = models.FloatField("Ly đã pha rồi hủy", default=0)
    waste_operational = models.FloatField("Hao hụt vận hành", default=0)
    waste_one_off = models.FloatField("Hao hụt sự cố đơn lẻ", default=0)
    waste_stock = models.FloatField("Hư hỏng và hết hạn", default=0)
    count_adjust = models.FloatField("Điều chỉnh kiểm kê", default=0)
    consumed_ledger = models.FloatField("Tiêu hao pha chế trong sổ kho", default=0)
    own_stockout = models.BooleanField("Hết hàng chính nguyên liệu này", default=False)
    indirect_block = models.BooleanField("Bị chặn gián tiếp do thiếu nguyên liệu khác", default=False)
    eligible = models.BooleanField("Dùng để học và đo sai số", default=False)

    class Meta:
        verbose_name = "Tiêu hao nguyên liệu theo ngày"
        verbose_name_plural = "Tiêu hao nguyên liệu theo ngày"
        ordering = ["ingredient", "date"]
        constraints = [models.UniqueConstraint(fields=["ingredient", "date"], name="uniq_usage_ingredient_day")]


class PlanRun(TimeStampedModel):
    """Một lần tính kế hoạch mua: toàn bộ sau khi chốt ngày, theo yêu cầu, hoặc riêng một nguyên liệu sau biến động."""

    class Kind(models.TextChoices):
        FULL = "toan_bo", "Tính toàn bộ sau khi chốt ngày"
        MANUAL = "theo_yeu_cau", "Chủ quán yêu cầu tính lại"
        MOVEMENT = "bien_dong", "Sau biến động tồn"

    kind = models.CharField("Loại", max_length=14, choices=Kind.choices)
    started_at = models.DateTimeField("Bắt đầu lúc", db_index=True)
    triggered_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
                                     related_name="+")
    summary = models.JSONField("Tóm tắt", default=dict)

    class Meta:
        verbose_name = "Lần tính kế hoạch mua"
        verbose_name_plural = "Lần tính kế hoạch mua"
        ordering = ["-started_at"]


class IngredientPlan(TimeStampedModel):
    """Kết quả tính cho một nguyên liệu (mục 9.1): cửa sổ, vị thế tồn, tồn an toàn, s, S, dòng tồn, ngày phải đặt,
    lượng đề xuất và hành động. Khóa chống trùng là nguyên liệu, ngày tính và mã phiên bản dữ liệu (mục 8.4): cùng dữ
    liệu thì trả về đúng bản đã có; dữ liệu đổi thì tạo bản mới và đánh dấu bản cũ đã thay thế.

    Lần tính chỉ đọc dữ liệu và ghi kết quả; không lần tính nào tự tạo đơn đặt hàng hay liên hệ nhà cung cấp."""

    class Action(models.TextChoices):
        BUY = "mua", "Mua"
        TOP_UP = "mua_bo_sung", "Mua bổ sung"
        EXPEDITE = "thuc_giao", "Thúc giao"
        NONE = "khong_can", "Không cần mua"
        NO_DATA = "thieu_du_lieu", "Chưa đủ dữ liệu"

    ingredient = models.ForeignKey("inventory.Ingredient", on_delete=models.PROTECT, related_name="plans")
    run = models.ForeignKey(PlanRun, on_delete=models.PROTECT, null=True, blank=True, related_name="plans")
    calc_date = models.DateField("Ngày tính", db_index=True)
    calculated_at = models.DateTimeField("Tính lúc")
    data_hash = models.CharField("Mã phiên bản dữ liệu", max_length=64)
    data_parts = models.JSONField("Thành phần của mã phiên bản", default=dict)
    forecast_version = models.CharField("Bản dự báo", max_length=64)
    forecast = models.JSONField("Dự báo theo ngày và sai số cửa sổ", default=dict)
    result = models.JSONField("Kết quả tính", default=dict)
    action = models.CharField("Hành động", max_length=14, choices=Action.choices)
    order_by = models.DateField("Ngày phải đặt chậm nhất", null=True, blank=True)
    order_now = models.BooleanField("Đặt ngay", default=False)
    risk_date = models.DateField("Ngày rủi ro", null=True, blank=True)
    stockout_date = models.DateField("Ngày dự kiến hết hàng", null=True, blank=True)
    suggested_quantity = models.DecimalField("Lượng đề xuất", max_digits=14, decimal_places=2, default=0)
    packs = models.PositiveIntegerField("Số gói đề xuất", default=0)
    alert_on = models.BooleanField("Cần cảnh báo Cần đặt hàng", default=False)
    episode_start = models.DateField("Đợt rủi ro bắt đầu", null=True, blank=True)
    episode_key = models.CharField("Mã đợt rủi ro", max_length=30, blank=True)
    is_current = models.BooleanField("Bản đang dùng", default=True)
    superseded_at = models.DateTimeField("Bị thay lúc", null=True, blank=True)

    class Meta:
        verbose_name = "Kế hoạch mua nguyên liệu"
        verbose_name_plural = "Kế hoạch mua nguyên liệu"
        ordering = ["-calculated_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["ingredient", "calc_date", "data_hash"], name="uniq_plan_per_data_version"),
        ]

    def __str__(self):
        return f"{self.ingredient.name} · {self.get_action_display()} · {self.calc_date:%d/%m/%Y}"
