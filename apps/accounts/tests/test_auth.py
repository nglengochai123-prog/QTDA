from datetime import timedelta

from django.conf import settings
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.audit.models import Action, AuditLog

PASSWORD = "matkhau-thu-123"


class LoginLogoutTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("thungan1", password=PASSWORD, role=Role.THU_NGAN)
        self.login_url = reverse("accounts:login")

    def _login(self, password=PASSWORD, username="thungan1"):
        return self.client.post(self.login_url, {"username": username, "password": password})

    def test_login_success_redirects_home_and_logs(self):
        response = self._login()
        self.assertRedirects(response, reverse("core:home"))
        self.assertTrue(AuditLog.objects.filter(action=Action.LOGIN, actor=self.user).exists())

    def test_wrong_password_shows_error_and_logs(self):
        response = self._login(password="sai-mat-khau")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertTrue(AuditLog.objects.filter(action=Action.LOGIN_FAILED, actor_label="thungan1").exists())

    def test_logout_requires_post_and_logs(self):
        self._login()
        self.assertEqual(self.client.get(reverse("accounts:logout")).status_code, 405)
        response = self.client.post(reverse("accounts:logout"))
        self.assertRedirects(response, self.login_url)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertTrue(AuditLog.objects.filter(action=Action.LOGOUT, actor=self.user).exists())

    def test_session_expires_after_15_minutes_idle(self):
        self.assertEqual(settings.SESSION_COOKIE_AGE, 15 * 60)
        self.assertTrue(settings.SESSION_SAVE_EVERY_REQUEST)


class AccountLockTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("phucvu1", password=PASSWORD, role=Role.PHUC_VU)

    def _login(self, password):
        return self.client.post(reverse("accounts:login"), {"username": "phucvu1", "password": password})

    def test_locks_after_repeated_wrong_passwords(self):
        for _ in range(settings.LOGIN_MAX_FAILED_ATTEMPTS):
            self._login("sai-mat-khau")
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_temporarily_locked)
        self.assertTrue(AuditLog.objects.filter(action=Action.ACCOUNT_LOCKED, actor=self.user).exists())
        # Đúng mật khẩu cũng không vào được khi đang tạm khóa.
        self._login(PASSWORD)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_lock_expires_and_counter_resets(self):
        User.objects.filter(pk=self.user.pk).update(
            locked_until=timezone.now() - timedelta(minutes=1), failed_login_count=3)
        response = self._login(PASSWORD)
        self.assertRedirects(response, reverse("core:home"))
        self.user.refresh_from_db()
        self.assertEqual(self.user.failed_login_count, 0)
        self.assertIsNone(self.user.locked_until)

    def test_owner_locked_account_cannot_login(self):
        self.user.is_active = False
        self.user.save()
        self._login(PASSWORD)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_locked_account_loses_access_mid_session(self):
        self._login(PASSWORD)
        self.user.is_active = False
        self.user.save()
        response = self.client.get(reverse("core:home"))
        self.assertEqual(response.status_code, 302)
