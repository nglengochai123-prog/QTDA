from django.conf import settings
from django.forms.models import model_to_dict

from .models import AuditLog


def snapshot(instance, exclude=("password",)):
    """Ảnh chụp dữ liệu của một bản ghi để lưu vào cột Trước/Sau."""
    if instance is None:
        return None
    data = model_to_dict(instance)
    for key in exclude:
        data.pop(key, None)
    for key, value in list(data.items()):
        if hasattr(value, "pk"):
            data[key] = value.pk
        elif isinstance(value, (list, tuple)):
            data[key] = [getattr(v, "pk", v) for v in value]
    return data


def changed_fields(before, after):
    if not before or not after:
        return before, after
    keys = [k for k in after if before.get(k) != after.get(k)]
    return {k: before.get(k) for k in keys}, {k: after.get(k) for k in keys}


def _client_ip(request):
    if request is None:
        return None
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def record(action, *, actor=None, request=None, obj=None, before=None, after=None,
           reason="", actor_label=None, object_type=None):
    """Ghi một dòng nhật ký. Mọi chức năng nghiệp vụ dùng hàm này."""
    if actor is None and request is not None and getattr(request, "user", None) is not None:
        if request.user.is_authenticated:
            actor = request.user
    store = getattr(actor, "store", None)
    return AuditLog.objects.create(
        store_code=getattr(store, "code", None) or settings.LAM_STORE_CODE,
        actor=actor,
        actor_label=actor_label or (actor.get_username() if actor else ""),
        action=action,
        object_type=object_type or (obj._meta.label if obj is not None else ""),
        object_id=str(obj.pk) if obj is not None and obj.pk is not None else "",
        object_repr=str(obj)[:255] if obj is not None else "",
        before=before,
        after=after,
        reason=reason,
        ip_address=_client_ip(request),
        path=request.path[:255] if request is not None else "",
    )
