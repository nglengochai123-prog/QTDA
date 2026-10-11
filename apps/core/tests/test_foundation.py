from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import Role, User
from apps.core.models import Store


class FoundationTests(TestCase):
    def test_healthz(self):
        response = self.client.get(reverse("core:healthz"))
        self.assertEqual(response.json(), {"status": "ok"})

    def test_home_requires_login(self):
        response = self.client.get(reverse("core:home"))
        self.assertRedirects(response, f"{reverse('accounts:login')}?next=/")

    def test_home_after_login(self):
        User.objects.create_user("phucvu1", password="matkhau-thu-123", role=Role.PHUC_VU)
        self.client.login(username="phucvu1", password="matkhau-thu-123")
        response = self.client.get(reverse("core:home"))
        self.assertContains(response, "Phục vụ")

    def test_pwa_files(self):
        self.assertEqual(self.client.get("/manifest.webmanifest").status_code, 200)
        self.assertEqual(self.client.get("/sw.js")["Service-Worker-Allowed"], "/")

    def test_user_gets_default_store(self):
        user = User.objects.create_user("phache1", password="matkhau-thu-123", role=Role.PHA_CHE)
        self.assertEqual(user.store, Store.get_default())
