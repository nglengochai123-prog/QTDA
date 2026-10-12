"""Sao lưu giữ đủ số bản, phục hồi chỉ vào CSDL riêng (NFR-09)."""

import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest import skipUnless

from django.conf import settings
from django.test import TestCase

from apps.core import backup


@skipUnless(backup.is_sqlite(), "Sao lưu PostgreSQL thử bằng lệnh sao_luu trên máy có pg_dump (xem docs/VAN_HANH.md)")
class BackupTests(TestCase):
    def test_backup_rotation_and_restore_guards(self):
        with tempfile.TemporaryDirectory() as tmp:
            start = datetime(2026, 10, 1, 23, 0)
            for i in range(3):
                target, removed = backup.make_backup(tmp, keep=2, now=start + timedelta(days=i))
            self.assertEqual([p.name for p in backup.backups(tmp)],
                             ["lamcoffee-20261002-230000.sqlite3", "lamcoffee-20261003-230000.sqlite3"])
            self.assertEqual(removed, ["lamcoffee-20261001-230000.sqlite3"])
            self.assertEqual(backup.sqlite_integrity(target), "ok")
            with self.assertRaises(ValueError):
                backup.restore(target, settings.DATABASES["default"]["NAME"])
            restored = Path(tmp) / "thu.sqlite3"
            env = backup.restore(target, restored)
            self.assertEqual(env["SQLITE_NAME"], str(restored.resolve()))
            with self.assertRaises(ValueError):  # không ghi đè bản đã có nếu không yêu cầu rõ
                backup.restore(target, restored)
            backup.restore(target, restored, overwrite=True)
