"""CSDL chưa chạy migrate: thay trang lỗi bằng trang chỉ lệnh sao lưu và cập nhật."""

from unittest import mock

from django.db import OperationalError
from django.test import RequestFactory, SimpleTestCase

from apps.core.middleware import SchemaOutdatedMiddleware, pending_migrations


class SchemaOutdatedTests(SimpleTestCase):
    def setUp(self):
        self.mw = SchemaOutdatedMiddleware(lambda request: None)
        self.request = RequestFactory().get("/du-bao/")

    def test_missing_column_with_pending_migration_shows_commands(self):
        error = OperationalError("no such column: inventory_ingredient.kind")
        from django.conf import settings

        db = {"ENGINE": "django.db.backends.sqlite3", "NAME": settings.BASE_DIR / "nghiem_thu.sqlite3"}
        with mock.patch("apps.core.middleware.pending_migrations", return_value=["inventory.0014_ban_thanh_pham"]), \
                mock.patch.dict(settings.DATABASES["default"], db), self.assertLogs("lam.schema", "ERROR"):
            response = self.mw.process_exception(self.request, error)
        self.assertEqual(response.status_code, 503)
        page = response.content.decode()
        self.assertIn("Cần cập nhật cơ sở dữ liệu", page)
        self.assertIn("manage.py sao_luu", page)
        self.assertIn("manage.py migrate", page)
        self.assertIn('$env:SQLITE_NAME = "nghiem_thu.sqlite3"', page)
        self.assertIn("inventory.0014_ban_thanh_pham", page)

    def test_other_errors_are_left_alone(self):
        with mock.patch("apps.core.middleware.pending_migrations", return_value=[]):
            self.assertIsNone(self.mw.process_exception(self.request, OperationalError("no such column: x")))
        with mock.patch("apps.core.middleware.pending_migrations", return_value=["a.0001"]):
            self.assertIsNone(self.mw.process_exception(self.request, OperationalError("database is locked")))
            self.assertIsNone(self.mw.process_exception(self.request, ValueError("no such column")))


class PendingMigrationTests(SimpleTestCase):
    databases = {"default"}

    def test_test_database_is_up_to_date(self):
        self.assertEqual(pending_migrations(), [])
