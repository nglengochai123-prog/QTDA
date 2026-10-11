from django.contrib.auth.backends import ModelBackend


class LockAwareBackend(ModelBackend):
    """Từ chối đăng nhập khi tài khoản bị khóa (is_active=False) hoặc đang tạm khóa."""

    def user_can_authenticate(self, user):
        if getattr(user, "is_temporarily_locked", False):
            return False
        return super().user_can_authenticate(user)
