"""Nút mở ca theo lịch đã công bố, hiện ở những chỗ thu ngân thấy quán chưa có ca đang mở."""

from django import template

register = template.Library()


@register.inclusion_tag("shifts/_open_from_schedule.html", takes_context=True)
def mo_ca_theo_lich(context):
    from apps.accounts.permissions import Cap, user_can

    from ..from_schedule import openable, window

    request = context.get("request")
    user = getattr(request, "user", None)
    rows = []
    if user is not None and user.is_authenticated and user_can(user, Cap.CASH_FUND):
        rows = [{"ws": ws, "start": window(ws)[0], "end": window(ws)[1]} for ws in openable()]
    return {"rows": rows, "csrf_token": context.get("csrf_token"), "next": request.get_full_path() if request else ""}


@register.filter
def co_quyen(user, cap):
    """Người dùng có quyền `cap` (giá trị trong Cap, ví dụ "shift_close"): để lời dặn nói đúng việc người đó làm được."""
    from apps.accounts.permissions import user_can

    return bool(user and user.is_authenticated and user_can(user, cap))
