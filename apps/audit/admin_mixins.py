from django.db import transaction

from .models import Action
from .services import changed_fields, record, snapshot


class AuditedAdminMixin:
    """Ghi nhật ký trước/sau cho mọi thay đổi dữ liệu gốc qua trang quản trị."""

    def save_model(self, request, obj, form, change):
        before = None
        if change and obj.pk:
            before = snapshot(type(obj)._default_manager.get(pk=obj.pk))
        with transaction.atomic():
            super().save_model(request, obj, form, change)
            after = snapshot(obj)
            if change:
                before, after = changed_fields(before, after)
            record(Action.UPDATE if change else Action.CREATE, request=request, obj=obj,
                   before=before, after=after)

    def delete_model(self, request, obj):
        before = snapshot(obj)
        with transaction.atomic():
            record(Action.DELETE, request=request, obj=obj, before=before)
            super().delete_model(request, obj)

    def delete_queryset(self, request, queryset):
        for obj in queryset:
            self.delete_model(request, obj)

    def save_formset(self, request, form, formset, change):
        changes = []
        for inline_form in formset.forms:
            if not inline_form.has_changed() or inline_form in getattr(formset, "deleted_forms", []):
                continue
            fields = [f for f in inline_form.changed_data if f not in ("id", "DELETE")]
            before = {f: inline_form.initial.get(f) for f in fields} if inline_form.instance.pk else None
            changes.append((inline_form, fields, before))
        deleted = [snapshot(f.instance) for f in getattr(formset, "deleted_forms", []) if f.instance.pk]
        deleted_objs = [f.instance for f in getattr(formset, "deleted_forms", []) if f.instance.pk]
        with transaction.atomic():
            super().save_formset(request, form, formset, change)
            for inline_form, fields, before in changes:
                obj = inline_form.instance
                after = {f: snapshot(obj).get(f) for f in fields}
                record(Action.UPDATE if before is not None else Action.CREATE,
                       request=request, obj=obj, before=before, after=after)
            for obj, data in zip(deleted_objs, deleted):
                record(Action.DELETE, request=request, obj=obj, before=data,
                       object_type=obj._meta.label)
