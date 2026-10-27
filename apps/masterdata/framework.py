"""Trang quản trị dữ liệu nền riêng của ứng dụng (thay cho trang quản trị Django).

Mỗi loại dữ liệu khai báo một `Resource`: cột danh sách, ô tìm kiếm, bộ lọc, biểu mẫu, các dòng con
(kích cỡ của món, tùy chọn của nhóm, dòng định mức) và thao tác riêng (áp dụng định mức, đặt mật khẩu...).
Mọi thay đổi đi qua một chỗ để ghi nhật ký trước/sau (FR-61) và chỉ người có quyền mới mở được (Bảng 5.3).
"""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Callable

from django import forms
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import IntegrityError, models, transaction
from django.db.models import Q
from django.forms import BaseInlineFormSet, inlineformset_factory, modelform_factory
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from apps.accounts.permissions import Cap, _deny, user_can
from apps.audit.models import Action
from apps.audit.services import changed_fields, record, snapshot
from apps.core import numbers
from apps.core.paging import paginate


@dataclass
class Inline:
    """Các dòng con sửa cùng trang với bản ghi cha."""

    model: type
    fields: list
    label: str
    fk_name: str = None
    extra: int = 1
    can_delete: bool = False
    # (formset_form, parent) -> None: lọc lựa chọn theo bản ghi cha
    prepare: Callable = None
    # parent -> bool: còn sửa được không (ví dụ định mức đã áp dụng thì chỉ xem)
    editable: Callable = None


@dataclass
class ActionDef:
    """Thao tác riêng trên một bản ghi; có `fields` thì hiện thành biểu mẫu nhỏ ở trang sửa."""

    key: str
    label: str
    handler: Callable  # (request, obj, cleaned_data) -> thông báo thành công; lỗi thì ném ValidationError
    when: Callable = None  # obj -> bool
    fields: dict = field(default_factory=dict)  # tên -> forms.Field
    help: str = ""
    primary: bool = False


@dataclass
class Resource:
    key: str
    title: str
    singular: str
    model: type
    fields: list
    columns: list  # [(tiêu đề, hàm(obj) hoặc tên thuộc tính)]
    cap: str = Cap.MASTER_DATA
    search: tuple = ()
    filters: list = field(default_factory=list)  # [(tham số, nhãn, trường, [(giá trị, nhãn)])]
    form_class: type = None
    widgets: dict = field(default_factory=dict)
    inlines: list = field(default_factory=list)
    actions: list = field(default_factory=list)
    create_fields: list = None  # trường khi tạo mới, nếu khác khi sửa
    editable: Callable = None  # obj -> bool
    queryset: Callable = None
    prepare_form: Callable = None  # (form, obj, request) -> None
    save: Callable = None  # (request, form, created) -> obj
    note: str = ""  # một dòng ngắn dưới tiêu đề khi thật cần

    def get_queryset(self):
        return self.queryset() if self.queryset else self.model._default_manager.all()

    def can_edit(self, obj):
        return obj is None or self.editable is None or self.editable(obj)


REGISTRY = {}


def register(resource):
    REGISTRY[resource.key] = resource
    return resource


def get_resource(request, key):
    resource = REGISTRY.get(key)
    if resource is None:
        raise Http404
    if not user_can(request.user, resource.cap):
        _deny(request, resource.cap)
    return resource


def _style(form):
    for f in form.fields.values():
        # Ô chọn để trống được: thay dòng "---------" mặc định bằng chữ.
        if isinstance(f, forms.ModelChoiceField) and f.empty_label == "---------":
            f.empty_label = "Chưa chọn"
        elif isinstance(f, forms.ChoiceField) and list(f.choices[:1]) == [("", "---------")]:
            f.choices = [("", "Chưa chọn"), *f.choices[1:]]
        widget = f.widget
        if isinstance(widget, (forms.CheckboxInput, forms.CheckboxSelectMultiple, forms.RadioSelect)):
            continue
        widget.attrs.setdefault("class", "input")


def _formfield(db_field, **kwargs):
    if isinstance(db_field, models.DateTimeField):
        kwargs["widget"] = forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M")
        kwargs["input_formats"] = ["%Y-%m-%dT%H:%M"]
    elif isinstance(db_field, models.DateField):
        kwargs["widget"] = forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")
    elif isinstance(db_field, models.ManyToManyField):
        kwargs["widget"] = forms.CheckboxSelectMultiple
    elif isinstance(db_field, models.TextField):
        kwargs["widget"] = forms.Textarea(attrs={"rows": 3})
    else:
        return numbers.formfield(db_field, **kwargs)
    return db_field.formfield(**kwargs)


def _check_duplicates(form, request):
    """Ràng buộc không trùng theo cửa hàng (tên nhóm món, mã bàn…) có ô cửa hàng không nằm trong biểu mẫu nên Django không
    tự kiểm; lưu trùng thì cơ sở dữ liệu báo lỗi và trang hỏng. Kiểm ở đây để báo ngay dưới ô bị trùng."""
    from apps.core.models import Store

    model, instance = form._meta.model, form.instance
    store_id = instance.store_id if getattr(instance, "store_id", None) else (request.user.store_id
                                                                             or Store.get_default().pk)
    for c in model._meta.constraints:
        if not isinstance(c, models.UniqueConstraint) or c.condition is not None or "store" not in c.fields:
            continue
        others = [f for f in c.fields if f != "store"]
        if not others or not all(f in form.cleaned_data for f in others):
            continue
        lookup = {"store_id": store_id, **{f: form.cleaned_data[f] for f in others}}
        if model._default_manager.filter(**lookup).exclude(pk=instance.pk).exists():
            name = others[-1]
            form.add_error(name, f"Đã có {form.fields[name].label.lower()} \"{form.cleaned_data[name]}\"; "
                                 f"đặt khác hoặc sửa mục đã có.")


def _assign_store(obj, request):
    if any(f.name == "store" for f in obj._meta.fields) and getattr(obj, "store_id", None) is None:
        from apps.core.models import Store

        obj.store = request.user.store or Store.get_default()


def _cell(obj, accessor):
    value = accessor(obj) if callable(accessor) else getattr(obj, accessor)
    if callable(value):
        value = value()
    if isinstance(value, bool):
        return "Có" if value else "Không"
    display = getattr(obj, f"get_{accessor}_display", None) if isinstance(accessor, str) else None
    if display:
        return display()
    if isinstance(value, Decimal):
        return numbers.fmt(value)
    if isinstance(value, int):
        return numbers.fmt(value, 0)
    return "" if value is None else value


def list_view(request, key):
    resource = get_resource(request, key)
    qs = resource.get_queryset()
    q = (request.GET.get("q") or "").strip()
    if q and resource.search:
        cond = Q()
        for f in resource.search:
            cond |= Q(**{f"{f}__icontains": q})
        qs = qs.filter(cond)
    active_filters = []
    for param, label, fld, choices in resource.filters:
        value = request.GET.get(param, "")
        if value in {str(v) for v, _ in choices}:
            qs = qs.filter(**{fld: {"1": True, "0": False}.get(value, value)})
        active_filters.append({"param": param, "label": label, "choices": choices, "value": value})
    page, qs_params = paginate(request, qs)
    rows = [{"obj": obj, "cells": [(h, _cell(obj, acc)) for h, acc in resource.columns]} for obj in page.object_list]
    return render(request, "masterdata/list.html", {
        "r": resource, "page": page, "qs": qs_params, "rows": rows, "q": q, "filters": active_filters,
        "headers": [h for h, _ in resource.columns],
    })


class _InlineFormSet(BaseInlineFormSet):
    def get_unique_error_message(self, unique_check):
        # Câu mặc định ghi tên trường tiếng Anh ("trùng lặp cho name"); dùng nhãn của ô.
        labels = [str(self.form.base_fields[f].label).lower() for f in unique_check
                  if f in self.form.base_fields and f != self.fk.name]
        return f"Có hai dòng trùng {' và '.join(labels) or 'nội dung'}; mỗi dòng cần khác nhau."


def _formset_classes(resource):
    classes = []
    for inline in resource.inlines:
        classes.append(inlineformset_factory(
            resource.model, inline.model, formset=_InlineFormSet, fields=inline.fields, fk_name=inline.fk_name,
            extra=inline.extra, can_delete=inline.can_delete, formfield_callback=_formfield))
    return classes


def edit_view(request, key, pk=None):
    resource = get_resource(request, key)
    obj = get_object_or_404(resource.get_queryset(), pk=pk) if pk else None
    editable = resource.can_edit(obj)
    fields = resource.create_fields if obj is None and resource.create_fields else resource.fields
    form_cls = resource.form_class or modelform_factory(resource.model, fields=fields, widgets=resource.widgets,
                                                        formfield_callback=_formfield)
    data = request.POST if request.method == "POST" and editable else None
    form = form_cls(data, instance=obj)
    if resource.form_class is not None:
        for name in list(form.fields):
            if name not in fields:
                del form.fields[name]
    if resource.prepare_form:
        resource.prepare_form(form, obj, request)
    if not editable:
        for f in form.fields.values():
            f.disabled = True
    _style(form)
    formsets = []
    if obj is not None:
        for inline, cls in zip(resource.inlines, _formset_classes(resource)):
            inline_editable = editable and (inline.editable is None or inline.editable(obj))
            fs = cls(data if inline_editable else None, instance=obj, prefix=inline.model._meta.model_name)
            for f in fs.forms + [fs.empty_form]:
                if inline.prepare:
                    inline.prepare(f, obj)
                if not inline_editable:
                    for ff in f.fields.values():
                        ff.disabled = True
                _style(f)
            formsets.append({"inline": inline, "fs": fs, "editable": inline_editable})
    if data is not None:
        live = [x for x in formsets if x["editable"]]
        if form.is_valid():
            _check_duplicates(form, request)
        if form.is_valid() and all(x["fs"].is_valid() for x in live):
            try:
                with transaction.atomic():
                    saved = _save(request, resource, form, obj, live)
            except ValidationError as error:
                form.add_error(None, error)
            except IntegrityError:  # trùng ở dòng con (ví dụ hai cỡ cùng tên) mà biểu mẫu chưa bắt được
                form.add_error(None, "Có mục trùng tên hoặc mã với mục đã có; kiểm tra lại rồi lưu.")
            else:
                messages.success(request, f"Đã lưu {resource.singular.lower()} {saved}.")
                # Bản ghi mới có dòng con hoặc thao tác riêng (đặt mật khẩu, ghi tồn đầu kỳ): mở luôn trang của nó
                # để làm tiếp bước đó.
                if obj is None and (resource.inlines or resource.actions):
                    return redirect("masterdata:edit", key=key, pk=saved.pk)
                return redirect("masterdata:list", key=key)
    actions = []
    if obj is not None:
        for a in resource.actions:
            if a.when is None or a.when(obj):
                action_form = forms.Form(prefix=a.key)
                action_form.fields.update({name: f for name, f in a.fields.items()})
                _style(action_form)
                actions.append({"a": a, "form": action_form})
    return render(request, "masterdata/form.html", {
        "r": resource, "obj": obj, "form": form, "formsets": formsets, "editable": editable, "actions": actions,
    })


def _save(request, resource, form, obj, formsets):
    created = obj is None
    before = snapshot(type(obj)._default_manager.get(pk=obj.pk)) if obj is not None else None
    if resource.save:
        saved = resource.save(request, form, created)
    else:
        saved = form.save(commit=False)
        _assign_store(saved, request)
        saved.save()
        form.save_m2m()
    after = snapshot(saved)
    if not created:
        before, after = changed_fields(before, after)
    if created or after:
        record(Action.CREATE if created else Action.UPDATE, request=request, obj=saved, before=before, after=after)
    for item in formsets:
        _save_formset(request, item["fs"], saved)
    return saved


def _save_formset(request, fs, parent):
    for f in fs.forms:
        if not f.has_changed():
            continue
        if fs.can_delete and f.cleaned_data.get("DELETE"):
            if f.instance.pk:
                record(Action.DELETE, request=request, obj=f.instance, before=snapshot(f.instance))
                f.instance.delete()
            continue
        child = f.instance
        before = {k: f.initial.get(k) for k in f.changed_data} if child.pk else None
        child = f.save(commit=False)
        setattr(child, fs.fk.name, parent)
        child.save()
        after = {k: snapshot(child).get(k) for k in f.changed_data}
        record(Action.UPDATE if before is not None else Action.CREATE, request=request, obj=child,
               before=before, after=after)


def action_view(request, key, pk, action):
    resource = get_resource(request, key)
    obj = get_object_or_404(resource.get_queryset(), pk=pk)
    if request.method != "POST":
        return redirect("masterdata:edit", key=key, pk=pk)
    a = next((x for x in resource.actions if x.key == action and (x.when is None or x.when(obj))), None)
    if a is None:
        raise Http404
    form = forms.Form(request.POST, prefix=a.key)
    form.fields.update({name: f for name, f in a.fields.items()})
    if not form.is_valid():
        for errors in form.errors.values():
            for e in errors:
                messages.error(request, e)
        return redirect("masterdata:edit", key=key, pk=pk)
    try:
        with transaction.atomic():
            result = a.handler(request, obj, form.cleaned_data)
    except ValidationError as error:
        for m in error.messages:
            messages.error(request, m)
        return redirect("masterdata:edit", key=key, pk=pk)
    messages.success(request, result or "Đã thực hiện.")
    target = getattr(result, "redirect_to", None)
    return redirect(target or reverse("masterdata:edit", kwargs={"key": key, "pk": pk}))


class Done(str):
    """Thông báo thành công kèm trang cần chuyển tới (ví dụ bản nháp định mức vừa tạo)."""

    def __new__(cls, text, redirect_to=None):
        s = super().__new__(cls, text)
        s.redirect_to = redirect_to
        return s
