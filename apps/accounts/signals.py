from django.contrib.auth import get_user_model
from django.contrib.auth.signals import user_logged_in, user_login_failed
from django.dispatch import receiver

from apps.audit.models import Action
from apps.audit.services import record


@receiver(user_login_failed)
def count_failed_login(sender, credentials, request=None, **kwargs):
    username = credentials.get("username")
    if not username:
        return
    User = get_user_model()
    user = User.objects.filter(username=username).first()
    if user is None or user.is_temporarily_locked:
        return
    if user.register_failed_login():
        record(Action.ACCOUNT_LOCKED, actor=user, request=request,
               reason="Sai mật khẩu quá số lần cho phép")


@receiver(user_logged_in)
def reset_failed_logins(sender, request, user, **kwargs):
    user.reset_failed_logins()
