from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.dispatch import receiver

from .models import Action
from .services import record


@receiver(user_logged_in)
def on_login(sender, request, user, **kwargs):
    record(Action.LOGIN, actor=user, request=request)


@receiver(user_logged_out)
def on_logout(sender, request, user, **kwargs):
    if user is not None:
        record(Action.LOGOUT, actor=user, request=request)


@receiver(user_login_failed)
def on_login_failed(sender, credentials, request=None, **kwargs):
    record(Action.LOGIN_FAILED, request=request, actor_label=str(credentials.get("username", ""))[:150])
