from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect
from django.urls import path, reverse

from apps.accounts.permissions import Cap, OwnerOnlyAdminMixin, OwnerOnlyInlineMixin
from apps.audit.admin_mixins import AuditedAdminMixin
from apps.audit.models import Action
from apps.audit.services import record

from .models import Ingredient, RecipeLine, RecipeVersion, Supplier


class InventoryAdmin(OwnerOnlyAdminMixin, AuditedAdminMixin, admin.ModelAdmin):
    owner_capability = Cap.MASTER_INVENTORY
    exclude = ("store",)

    def save_model(self, request, obj, form, change):
        if getattr(obj, "store_id", None) is None:
            obj.store = request.user.store
        super().save_model(request, obj, form, change)


@admin.register(Supplier)
class SupplierAdmin(InventoryAdmin):
    list_display = ("name", "phone", "is_active")
    search_fields = ("name", "phone")


@admin.register(Ingredient)
class IngredientAdmin(InventoryAdmin):
    list_display = ("name", "unit", "pack_size", "main_supplier", "lead_time_days", "safety_stock",
                    "safety_stock_is_provisional", "is_critical", "is_active")
    list_filter = ("is_critical", "is_active", "main_supplier")
    search_fields = ("name",)


class RecipeLineInline(OwnerOnlyInlineMixin, admin.TabularInline):
    owner_capability = Cap.MASTER_INVENTORY
    model = RecipeLine
    extra = 2
    fields = ("size", "option", "ingredient", "quantity")
    autocomplete_fields = ("ingredient",)

    def _version(self, request):
        object_id = request.resolver_match.kwargs.get("object_id")
        return RecipeVersion.objects.filter(pk=object_id).select_related("item").first() if object_id else None

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        version = self._version(request)
        if version is not None:
            if db_field.name == "size":
                kwargs["queryset"] = version.item.sizes.all()
            elif db_field.name == "option":
                from apps.catalog.models import Option

                kwargs["queryset"] = Option.objects.filter(group__in=version.item.option_groups.all())
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def _editable(self, request, obj):
        return obj is not None and not obj.is_published and self._owner(request)

    def has_add_permission(self, request, obj=None):
        return self._editable(request, obj)

    def has_change_permission(self, request, obj=None):
        return self._editable(request, obj)

    def has_delete_permission(self, request, obj=None):
        return self._editable(request, obj)

    def has_view_permission(self, request, obj=None):
        return self._owner(request)


@admin.register(RecipeVersion)
class RecipeVersionAdmin(InventoryAdmin):
    list_display = ("item", "number", "status", "effective_from", "published_by", "note")
    list_filter = ("status",)
    search_fields = ("item__name",)
    readonly_fields = ("number", "status", "effective_from", "published_by")
    inlines = [RecipeLineInline]
    actions = ["publish_versions", "copy_as_draft"]
    change_form_template = "admin/inventory/recipeversion/change_form.html"

    def get_readonly_fields(self, request, obj=None):
        fields = list(super().get_readonly_fields(request, obj))
        if obj is not None:
            fields.append("item")
            if obj.is_published:
                fields.append("note")
        return fields

    def has_delete_permission(self, request, obj=None):
        if obj is not None and obj.is_published:
            return False
        return super().has_delete_permission(request, obj)

    def _publish(self, request, version):
        try:
            version.publish(request.user)
        except ValidationError as error:
            self.message_user(request, f"{version}: {' '.join(error.messages)}", messages.ERROR)
            return False
        record(Action.PUBLISH_RECIPE, request=request, obj=version,
               after={"effective_from": version.effective_from,
                      "lines": [str(line) for line in version.lines.select_related("ingredient", "size", "option")]})
        return True

    @admin.action(description="Áp dụng các bản nháp đã chọn từ bây giờ")
    def publish_versions(self, request, queryset):
        done = sum(self._publish(request, v) for v in queryset.filter(status=RecipeVersion.Status.DRAFT))
        if done:
            self.message_user(request, f"Đã áp dụng {done} phiên bản định mức.", messages.SUCCESS)

    @admin.action(description="Tạo bản nháp mới từ phiên bản đã chọn")
    def copy_as_draft(self, request, queryset):
        for version in queryset:
            if RecipeVersion.objects.filter(item=version.item, status=RecipeVersion.Status.DRAFT).exists():
                self.message_user(request, f"{version.item} đã có một bản nháp; hãy sửa bản đó.", messages.WARNING)
                continue
            draft = version.copy_as_draft()
            record(Action.CREATE, request=request, obj=draft, reason=f"Sao từ phiên bản {version.number}")
        self.message_user(request, "Đã tạo bản nháp.", messages.SUCCESS)

    def has_change_permission(self, request, obj=None):
        if obj is not None and obj.is_published:
            return False  # Bản đã áp dụng chỉ xem; muốn đổi thì tạo bản nháp mới.
        return super().has_change_permission(request, obj)

    def has_view_permission(self, request, obj=None):
        return self._owner(request)

    def get_urls(self):
        urls = [
            path("<int:pk>/ap-dung/", self.admin_site.admin_view(self.publish_view),
                 name="inventory_recipeversion_publish"),
            path("<int:pk>/tao-ban-nhap/", self.admin_site.admin_view(self.copy_view),
                 name="inventory_recipeversion_copy"),
        ]
        return urls + super().get_urls()

    def _get_for_post(self, request, pk):
        if request.method != "POST" or not self._owner(request):
            raise PermissionDenied
        return get_object_or_404(RecipeVersion, pk=pk)

    def publish_view(self, request, pk):
        version = self._get_for_post(request, pk)
        if self._publish(request, version):
            self.message_user(request, f"Đã áp dụng {version}.", messages.SUCCESS)
        return redirect(reverse("admin:inventory_recipeversion_change", args=[version.pk]))

    def copy_view(self, request, pk):
        version = self._get_for_post(request, pk)
        existing = RecipeVersion.objects.filter(item=version.item, status=RecipeVersion.Status.DRAFT).first()
        if existing is not None:
            self.message_user(request, "Món này đã có một bản nháp; hãy sửa bản đó.", messages.WARNING)
            return redirect(reverse("admin:inventory_recipeversion_change", args=[existing.pk]))
        draft = version.copy_as_draft()
        record(Action.CREATE, request=request, obj=draft, reason=f"Sao từ phiên bản {version.number}")
        self.message_user(request, f"Đã tạo {draft}.", messages.SUCCESS)
        return redirect(reverse("admin:inventory_recipeversion_change", args=[draft.pk]))


from django import forms  # noqa: E402

from . import stock as stock_service  # noqa: E402
from .models import IngredientStock, StockMovement  # noqa: E402


class OpeningStockForm(forms.ModelForm):
    class Meta:
        model = StockMovement
        fields = ["ingredient", "quantity", "note"]
        labels = {"quantity": "Tồn đầu kỳ"}
        help_texts = {"quantity": "Theo đơn vị tính của nguyên liệu. Mỗi nguyên liệu chỉ nhập một lần."}


@admin.register(StockMovement)
class StockMovementAdmin(OwnerOnlyAdminMixin, admin.ModelAdmin):
    """Sổ biến động kho: chỉ xem; thêm mới ở đây chỉ dùng để ghi tồn đầu kỳ."""

    owner_capability = Cap.MASTER_INVENTORY
    form = OpeningStockForm
    list_display = ("created_at", "ingredient", "kind", "quantity", "balance_after", "source_type", "source_id",
                    "actor", "note")
    list_filter = ("kind", "ingredient")
    date_hierarchy = "created_at"
    actions = None

    def get_readonly_fields(self, request, obj=None):
        return [f.name for f in StockMovement._meta.fields] if obj else []

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_view_permission(self, request, obj=None):
        return self._owner(request)

    def save_model(self, request, obj, form, change):
        try:
            movement = stock_service.record_opening(obj.ingredient, obj.quantity, request.user, obj.note)
        except ValidationError as error:
            self.message_user(request, " ".join(error.messages), messages.ERROR)
            obj.pk = None
            return
        obj.pk = movement.pk
        record(Action.CREATE, request=request, obj=movement, object_type="inventory.StockMovement",
               after={"ingredient": movement.ingredient.name, "quantity": movement.quantity, "kind": movement.kind})

    def response_add(self, request, obj, post_url_continue=None):
        if obj.pk is None:
            return redirect(reverse("admin:inventory_stockmovement_add"))
        return super().response_add(request, obj, post_url_continue)


@admin.register(IngredientStock)
class IngredientStockAdmin(OwnerOnlyAdminMixin, admin.ModelAdmin):
    owner_capability = Cap.MASTER_INVENTORY
    list_display = ("ingredient", "physical", "reserved", "available_display")
    search_fields = ("ingredient__name",)

    @admin.display(description="Tồn có thể dùng")
    def available_display(self, obj):
        return obj.available

    def has_add_permission(self, request, *args):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_view_permission(self, request, obj=None):
        return self._owner(request)
