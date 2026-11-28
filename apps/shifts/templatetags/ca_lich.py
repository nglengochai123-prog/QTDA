"""Nút mở ca theo lịch đã công bố, hiện ở những chỗ thu ngân thấy quán chưa có ca đang mở."""

from django import template

register = template.Library()


@register.inclusion_tag("shifts/_open_from_schedule.html", takes_context=True)
def mo_ca_theo_lich(context):
    from apps.accounts.permissions import Cap, user_can

    from ..from_schedule import openable, window

    request = context.get("request")
    user = getattr(request, "user", None)
    from ..models import Shift

    rows, can_open_now = [], False
    if user is not None and user.is_authenticated and user_can(user, Cap.CASH_FUND):
        rows = [{"ws": ws, "start": window(ws)[0], "end": window(ws)[1]} for ws in openable()]
        can_open_now = not rows and Shift.objects.operating() is None
    return {"rows": rows, "can_open_now": can_open_now, "csrf_token": context.get("csrf_token"),
            "next": request.get_full_path() if request else ""}


@register.simple_tag
def ca_cu_chua_ket():
    """Ca đã bắt đầu, quá giờ kết thúc hơn 2 giờ mà chưa kết (cũ nhất trước)."""
    from ..models import Shift

    return list(Shift.objects.stale())


@register.filter
def co_quyen(user, cap):
    """Người dùng có quyền `cap` (giá trị trong Cap, ví dụ "shift_close"): để lời dặn nói đúng việc người đó làm được."""
    from apps.accounts.permissions import user_can

    return bool(user and user.is_authenticated and user_can(user, cap))
