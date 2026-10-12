"""Các loại dữ liệu nền quản lý trên trang riêng của ứng dụng."""

from datetime import timedelta

from django import forms
from django.contrib.auth import password_validation
from django.contrib.humanize.templatetags.humanize import intcomma
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.accounts.permissions import Cap
from apps.audit.models import Action
from apps.audit.services import record
from apps.catalog.models import ItemSize, MenuGroup, MenuItem, Option, OptionGroup, Table
from apps.inventory.models import Ingredient, RecipeLine, RecipeVersion, StockMovement, Supplier
from apps.orders.models import AdjustmentReason
from apps.shifts.models import Shift
from apps.staff.forms import EmployeeForm
from apps.staff.models import Employee, EmploymentStatus

from .framework import ActionDef, Done, Inline, Resource, register

YES_NO = [("1", "Có"), ("0", "Không")]


def _local(dt):
    return timezone.localtime(dt).strftime("%H:%M %d/%m/%Y") if dt else ""


# ---------- Ca làm việc ----------

def _shift_form(form, obj, request):
    people = User.objects.filter(is_active=True).order_by("first_name", "last_name")
    for name in ("approver", "backup_approver", "payment_authorizer"):
        if name in form.fields:
            form.fields[name].queryset = people
    if obj is None and not form.is_bound:
        last = Shift.objects.order_by("-starts_at").first()
        if last is not None:  # gợi ý người duyệt theo ca gần nhất để thêm ca nhanh
            form.initial.setdefault("approver", last.approver_id)
            form.initial.setdefault("backup_approver", last.backup_approver_id)
            form.initial.setdefault("payment_authorizer", last.payment_authorizer_id)
            # Gợi ý ca kế tiếp cùng giờ với ca gần nhất (không sớm hơn hôm nay).
            start, end = timezone.localtime(last.starts_at), timezone.localtime(last.ends_at)
            day = max(start.date() + timedelta(days=1), timezone.localdate())
            shift_by = timedelta(days=(day - start.date()).days)
            form.initial.setdefault("name", last.name)
            form.initial.setdefault("starts_at", (start + shift_by).strftime("%Y-%m-%dT%H:%M"))
            form.initial.setdefault("ends_at", (end + shift_by).strftime("%Y-%m-%dT%H:%M"))


register(Resource(
    key="ca", title="Ca làm việc", singular="Ca", model=Shift,
    fields=["name", "starts_at", "ends_at", "approver", "backup_approver", "payment_authorizer"],
    columns=[("Ca", "name"), ("Bắt đầu", lambda s: _local(s.starts_at)), ("Kết thúc", lambda s: _local(s.ends_at)),
             ("Quản lý ca", "approver"), ("Duyệt dự phòng", lambda s: s.backup_approver or "Chưa có"),
             ("Trạng thái", "status")],
    search=("name",), filters=[("trang-thai", "Trạng thái", "status", Shift.Status.choices)],
    queryset=lambda: Shift.objects.select_related("approver", "backup_approver").order_by("-starts_at"),
    editable=lambda s: s.status == Shift.Status.OPEN, prepare_form=_shift_form,
))


# ---------- Nhân viên và tài khoản ----------

def _save_employee(request, form, created):
    employee = form.save(commit=False)
    if created:
        employee.attach_new_account(form.cleaned_data.get("username"))
    employee.save()
    return employee


def _set_password(request, employee, data):
    if data["password1"] != data["password2"]:
        raise ValidationError("Hai lần nhập mật khẩu không khớp.")
    password_validation.validate_password(data["password1"], employee.user)
    employee.user.set_password(data["password1"])
    employee.user.save(update_fields=["password"])
    employee.user.reset_failed_logins()
    record(Action.UPDATE, request=request, obj=employee.user, after={"mat_khau": "đã đặt lại"})
    return f"Đã đặt mật khẩu cho {employee.user.username}."


def _unlock(request, employee, data):
    employee.user.reset_failed_logins()
    record(Action.UPDATE, request=request, obj=employee.user, after={"tam_khoa": "đã mở"})
    return f"Đã mở khóa tài khoản {employee.user.username}."


register(Resource(
    key="nhan-vien", title="Nhân viên", singular="Nhân viên", model=Employee, form_class=EmployeeForm,
    fields=["full_name", "phone", "roles", "hourly_wage", "status"],
    create_fields=["full_name", "phone", "roles", "hourly_wage", "status", "username"],
    columns=[("Họ tên", "full_name"), ("Số điện thoại", "phone"), ("Vai trò", "role_labels"),
             ("Lương giờ", lambda e: f"{intcomma(e.hourly_wage)} đ"), ("Tài khoản", lambda e: e.user.username),
             ("Trạng thái", "status")],
    search=("full_name", "phone"), filters=[("trang-thai", "Trạng thái", "status", EmploymentStatus.choices)],
    queryset=lambda: Employee.objects.select_related("user").order_by("full_name"),
    save=_save_employee,
    actions=[
        ActionDef("mat-khau", "Đặt mật khẩu đăng nhập", _set_password, fields={
            "password1": forms.CharField(label="Mật khẩu mới", widget=forms.PasswordInput),
            "password2": forms.CharField(label="Nhập lại", widget=forms.PasswordInput)},
            help="Tài khoản mới chưa có mật khẩu; đặt ở đây rồi báo nhân viên."),
        ActionDef("mo-khoa", "Mở khóa do nhập sai mật khẩu", _unlock,
                  when=lambda e: bool(e.user.locked_until or e.user.failed_login_count)),
    ],
))


# ---------- Thực đơn ----------

register(Resource(
    key="ban", title="Bàn", singular="Bàn", model=Table, fields=["code", "area", "seats", "sort_order", "is_active"],
    columns=[("Số bàn", "code"), ("Khu vực", "area"), ("Số chỗ", "seats"), ("Đang dùng", "is_active")],
    search=("code", "area"), filters=[("dang-dung", "Đang dùng", "is_active", YES_NO)],
))

register(Resource(
    key="nhom-mon", title="Nhóm món", singular="Nhóm món", model=MenuGroup,
    fields=["name", "load_factor", "sort_order", "is_active"],
    columns=[("Tên nhóm", "name"), ("Hệ số tải", "load_factor"), ("Thứ tự", "sort_order"), ("Đang dùng", "is_active")],
    search=("name",),
))


def _item_status(item):
    blockers = item.sale_blockers()
    return "Đủ điều kiện" if not blockers else "Thiếu: " + "; ".join(blockers)


register(Resource(
    key="mon", title="Món và giá", singular="Món", model=MenuItem,
    fields=["name", "group", "status", "no_ingredients", "option_groups", "sort_order"],
    columns=[("Tên món", "name"), ("Nhóm", "group"),
             ("Giá", lambda i: " · ".join(f"{s.name} {intcomma(s.price)} đ" for s in i.active_sizes())),
             ("Trạng thái", "status"), ("Điều kiện mở bán", _item_status)],
    search=("name",), filters=[("trang-thai", "Trạng thái", "status", MenuItem.Status.choices)],
    queryset=lambda: MenuItem.objects.select_related("group").prefetch_related("sizes"),
    inlines=[Inline(ItemSize, ["name", "price", "sort_order", "is_active"], "Kích cỡ và giá bán", extra=2)],
    note="Đổi giá được ghi vào lịch sử giá; đơn và phiếu dự phòng cũ vẫn tính theo giá lúc bán.",
))

register(Resource(
    key="tuy-chon", title="Tùy chọn", singular="Nhóm tùy chọn", model=OptionGroup,
    fields=["name", "selection", "is_required"],
    columns=[("Nhóm tùy chọn", "name"), ("Cách chọn", "selection"), ("Bắt buộc", "is_required"),
             ("Tùy chọn", lambda g: ", ".join(o.name for o in g.options.filter(is_active=True)))],
    search=("name",),
    inlines=[Inline(Option, ["name", "extra_price", "no_ingredients", "sort_order", "is_active"], "Các tùy chọn", extra=2)],
))

register(Resource(
    key="ly-do", title="Lý do điều chỉnh", singular="Lý do", model=AdjustmentReason,
    fields=["name", "sort_order", "is_active"],
    columns=[("Lý do", "name"), ("Thứ tự", "sort_order"), ("Đang dùng", "is_active")],
    note="Lý do đã dùng không xóa được; bỏ chọn Đang dùng để ẩn.",
))


# ---------- Kho: nhà cung cấp, nguyên vật liệu, định mức ----------

register(Resource(
    key="nha-cung-cap", title="Nhà cung cấp", singular="Nhà cung cấp", model=Supplier, cap=Cap.MASTER_INVENTORY,
    fields=["name", "phone", "note", "is_active"],
    columns=[("Tên", "name"), ("Số điện thoại", "phone"), ("Đang giao dịch", "is_active")],
    search=("name", "phone"),
))


def _opening(request, ingredient, data):
    from apps.inventory import stock

    movement = stock.record_opening(ingredient, data["quantity"], request.user, data.get("note") or "")
    record(Action.CREATE, request=request, obj=movement, object_type="inventory.StockMovement",
           after={"ingredient": ingredient.name, "quantity": movement.quantity, "kind": movement.kind})
    return f"Đã ghi tồn đầu kỳ {ingredient.name}."


register(Resource(
    key="nguyen-lieu", title="Nguyên vật liệu", singular="Nguyên vật liệu", model=Ingredient, cap=Cap.MASTER_INVENTORY,
    fields=["name", "unit", "pack_size", "pack_label", "main_supplier", "lead_time_days", "order_cycle_days",
            "shelf_life_days", "storage_capacity", "safety_stock", "safety_stock_is_provisional", "is_critical",
            "count_accumulated_threshold", "is_active"],
    columns=[("Tên", "name"), ("Đơn vị", "unit"), ("Nhà cung cấp", "main_supplier"),
             ("Tồn an toàn", "safety_stock"), ("Trọng yếu", "is_critical"), ("Đang dùng", "is_active")],
    search=("name",), filters=[("trong-yeu", "Trọng yếu", "is_critical", YES_NO),
                               ("dang-dung", "Đang dùng", "is_active", YES_NO)],
    queryset=lambda: Ingredient.objects.select_related("main_supplier").order_by("name"),
    actions=[ActionDef("ton-dau-ky", "Ghi tồn đầu kỳ", _opening,
                       when=lambda i: not StockMovement.objects.filter(ingredient=i).exists(),
                       fields={"quantity": forms.DecimalField(label="Tồn đầu kỳ", min_value=0, decimal_places=2),
                               "note": forms.CharField(label="Ghi chú", required=False)},
                       help="Chỉ ghi một lần khi bắt đầu dùng hệ thống; sau đó điều chỉnh bằng kiểm kê.")],
))


def _recipe_lines_prepare(form, version):
    form.fields["size"].queryset = version.item.sizes.all()
    form.fields["option"].queryset = Option.objects.filter(group__in=version.item.option_groups.all())
    form.fields["ingredient"].queryset = Ingredient.objects.filter(is_active=True).order_by("name")


def _recipe_form(form, obj, request):
    if obj is not None and "item" in form.fields:
        form.fields["item"].disabled = True


def _publish(request, version, data):
    version.publish(request.user)
    record(Action.PUBLISH_RECIPE, request=request, obj=version,
           after={"effective_from": version.effective_from,
                  "lines": [str(line) for line in version.lines.select_related("ingredient", "size", "option")]})
    return f"Đã áp dụng {version} từ bây giờ."


def _copy(request, version, data):
    existing = RecipeVersion.objects.filter(item=version.item, status=RecipeVersion.Status.DRAFT).first()
    if existing is not None:
        raise ValidationError("Món này đã có một bản nháp; hãy sửa bản đó.")
    draft = version.copy_as_draft()
    record(Action.CREATE, request=request, obj=draft, reason=f"Sao từ phiên bản {version.number}")
    return Done(f"Đã tạo {draft}.", reverse("masterdata:edit", kwargs={"key": "dinh-muc", "pk": draft.pk}))


register(Resource(
    key="dinh-muc", title="Định mức", singular="Định mức", model=RecipeVersion, cap=Cap.MASTER_INVENTORY,
    fields=["item", "note"],
    columns=[("Món", "item"), ("Phiên bản", "number"), ("Trạng thái", "status"),
             ("Hiệu lực từ", lambda v: _local(v.effective_from)), ("Ghi chú", "note")],
    search=("item__name",), filters=[("trang-thai", "Trạng thái", "status", RecipeVersion.Status.choices)],
    queryset=lambda: RecipeVersion.objects.select_related("item").order_by("item__name", "-number"),
    editable=lambda v: not v.is_published, prepare_form=_recipe_form,
    inlines=[Inline(RecipeLine, ["size", "option", "ingredient", "quantity"], "Dòng định mức", extra=3,
                    can_delete=True, prepare=_recipe_lines_prepare, editable=lambda v: not v.is_published)],
    actions=[
        ActionDef("ap-dung", "Áp dụng từ bây giờ", _publish, when=lambda v: not v.is_published, primary=True,
                  help="Sau khi áp dụng, phiên bản này không sửa được; muốn đổi thì tạo bản nháp mới."),
        ActionDef("tao-ban-nhap", "Tạo bản nháp mới từ phiên bản này", _copy, when=lambda v: v.is_published),
    ],
    note="Mỗi dòng chọn đúng một: kích cỡ hoặc tùy chọn.",
))
