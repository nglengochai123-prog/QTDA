"""Bán thành phẩm: kế hoạch mẻ theo ngày và loại bán thành phẩm do Chủ quán quản lý (Hai, 28/11/2026)."""

from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from apps.accounts.permissions import Cap, capability_required
from apps.audit.models import Action
from apps.audit.services import record
from apps.core.dates import parse_day
from apps.core.models import Store

from .models import Ingredient, IngredientKind, SemiRecipe, SemiRecipeLine, SemiTask, Unit
from .semi_today import today_status


def _decimal(value, label):
    try:
        number = Decimal(str(value or "").strip().replace(",", "."))
    except InvalidOperation:
        raise ValidationError(f"{label} không hợp lệ.")
    if number <= 0:
        raise ValidationError(f"{label} phải lớn hơn 0.")
    return number


def _semi_products():
    return (Ingredient.objects.filter(is_active=True, kind=IngredientKind.SEMI, semi_recipe__isnull=False)
            .select_related("semi_recipe").order_by("name"))


@capability_required(Cap.MASTER_INVENTORY)
@require_http_methods(["GET", "POST"])
def plan(request):
    """Chủ quán thêm, sửa, bỏ việc làm mẻ của một ngày; chép kế hoạch từ ngày trước."""
    today = timezone.localdate()
    day = parse_day(request.GET.get("ngay") or request.POST.get("ngay")) or today
    back = f"{request.path}?ngay={day:%Y-%m-%d}"
    if request.method == "POST":
        action = request.POST.get("action")
        try:
            with transaction.atomic():
                if day < today:
                    raise ValidationError("Ngày đã qua: không sửa kế hoạch nữa.")
                if action == "add":
                    product = _semi_products().filter(pk=request.POST.get("product")).first()
                    if product is None:
                        raise ValidationError("Chọn bán thành phẩm.")
                    batches = _decimal(request.POST.get("batches") or "1", "Số mẻ")
                    task, created = SemiTask.objects.update_or_create(
                        day=day, product=product,
                        defaults={"batches": batches, "note": request.POST.get("note", "")[:255],
                                  "created_by": request.user, "store": Store.get_default()})
                    record(Action.CREATE if created else Action.UPDATE, request=request, obj=task,
                           after={"ngay": f"{day:%d/%m/%Y}", "ban_thanh_pham": product.name, "so_me": str(batches)})
                    messages.success(request, f"Đã {'thêm' if created else 'sửa'}: {product.name} {batches.normalize():f} mẻ.")
                elif action == "delete":
                    task = SemiTask.objects.filter(pk=request.POST.get("task"), day=day).select_related("product").first()
                    if task is not None:
                        record(Action.DELETE, request=request, obj=task,
                               before={"ngay": f"{day:%d/%m/%Y}", "ban_thanh_pham": task.product.name,
                                       "so_me": str(task.batches)})
                        task.delete()
                        messages.success(request, f"Đã bỏ {task.product.name} khỏi kế hoạch ngày {day:%d/%m}.")
                elif action == "copy":
                    source = (SemiTask.objects.filter(day__lt=day).order_by("-day").values_list("day", flat=True).first())
                    if source is None or SemiTask.objects.filter(day=day).exists():
                        raise ValidationError("Ngày này đã có kế hoạch, hoặc chưa có ngày nào trước đó để chép.")
                    rows = list(SemiTask.objects.filter(day=source, product__is_active=True))
                    for t in rows:
                        SemiTask.objects.create(store=t.store, day=day, product=t.product, batches=t.batches,
                                                note=t.note, created_by=request.user)
                    record(Action.CREATE, request=request, object_type="inventory.SemiTask",
                           after={"ngay": f"{day:%d/%m/%Y}", "chep_tu": f"{source:%d/%m/%Y}", "so_viec": len(rows)})
                    messages.success(request, f"Đã chép {len(rows)} việc từ ngày {source:%d/%m}.")
        except ValidationError as error:
            for m in error.messages:
                messages.error(request, m)
        return redirect(back)
    tasks = list(SemiTask.objects.filter(day=day).select_related("product", "created_by"))
    status = {r["ingredient"].pk: r for r in today_status(day)} if day <= today else {}
    for t in tasks:
        t.status = status.get(t.product_id)
    days = [today + timedelta(days=k) for k in range(-1, 6)]
    return render(request, "inventory/semi_plan.html", {
        "day": day, "today": today, "tasks": tasks, "products": _semi_products(), "days": days,
        "editable": day >= today, "has_previous": SemiTask.objects.filter(day__lt=day).exists(),
    })


@capability_required(Cap.MASTER_INVENTORY)
@require_http_methods(["GET", "POST"])
def types(request):
    """Danh sách loại bán thành phẩm và thêm loại mới trong một bước: tên, đơn vị, hạn dùng, một mẻ dùng gì ra bao nhiêu."""
    if request.method == "POST":
        p = request.POST
        try:
            name = (p.get("name") or "").strip()
            if not name:
                raise ValidationError("Nhập tên bán thành phẩm.")
            if Ingredient.objects.filter(name__iexact=name).exists():
                raise ValidationError(f"Đã có nguyên liệu tên {name}.")
            unit = p.get("unit")
            if unit not in Unit.values:
                raise ValidationError("Chọn đơn vị tính.")
            output = _decimal(p.get("output"), "Lượng thu được mỗi mẻ")
            shelf = int(p.get("shelf") or 0)
            lines = []
            for i in range(1, 5):
                ing = p.get(f"ing_{i}")
                if not ing:
                    continue
                raw = Ingredient.objects.filter(pk=ing, is_active=True).first()
                if raw is None:
                    raise ValidationError(f"Dòng {i}: chọn nguyên liệu.")
                lines.append((raw, _decimal(p.get(f"qty_{i}"), f"Dòng {i}: lượng")))
            if not lines:
                raise ValidationError("Khai ít nhất một nguyên liệu cho một mẻ.")
            with transaction.atomic():
                store = Store.get_default()
                product = Ingredient.objects.create(store=store, name=name, unit=unit, kind=IngredientKind.SEMI,
                                                    pack_size=output, lead_time_days=0, shelf_life_days=shelf or None)
                recipe = SemiRecipe.objects.create(store=store, product=product, batch_output=output,
                                                   yield_measured=bool(p.get("measured")))
                for raw, qty in lines:
                    SemiRecipeLine.objects.create(recipe=recipe, ingredient=raw, quantity=qty)
                record(Action.CREATE, request=request, obj=product, object_type="inventory.Ingredient",
                       after={"ban_thanh_pham": name, "don_vi": unit, "moi_me_thu": str(output),
                              "han_dung_ngay": shelf, "thanh_phan": {r.name: str(q) for r, q in lines}})
            messages.success(request, f"Đã thêm bán thành phẩm {name}. Đưa vào kế hoạch mẻ để pha chế làm hằng ngày.")
            return redirect("inventory:semi_types")
        except (ValidationError, IntegrityError, ValueError) as error:
            for m in getattr(error, "messages", [str(error)]):
                messages.error(request, m)
    products = (Ingredient.objects.filter(kind=IngredientKind.SEMI).select_related("semi_recipe")
                .prefetch_related("semi_recipe__lines__ingredient").order_by("-is_active", "name"))
    return render(request, "inventory/semi_types.html", {
        "products": products, "units": Unit.choices,
        "raws": Ingredient.objects.filter(is_active=True).order_by("name"), "rows": range(1, 5),
    })
