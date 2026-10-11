from django.db import DatabaseError, IntegrityError, connection, transaction
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import Role, User
from apps.audit.models import Action, AuditLog, ImmutableRecordError
from apps.audit.services import record
from apps.catalog.models import ItemSize, MenuGroup, MenuItem
from apps.core.models import Store


class AppendOnlyTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("chuquan", password="matkhau-thu-123", role=Role.CHU_QUAN)
        self.log = record(Action.UPDATE, actor=self.owner, reason="thử")

    def test_record_fields(self):
        self.assertEqual(self.log.actor_label, "chuquan")
        self.assertEqual(self.log.store_code, "LAM01")

    def test_model_cannot_update_or_delete(self):
        self.log.reason = "sửa"
        with self.assertRaises(ImmutableRecordError):
            self.log.save()
        with self.assertRaises(ImmutableRecordError):
            self.log.delete()

    def test_queryset_cannot_update_or_delete(self):
        with self.assertRaises(ImmutableRecordError):
            AuditLog.objects.filter(pk=self.log.pk).update(reason="sửa")
        with self.assertRaises(ImmutableRecordError):
            AuditLog.objects.all().delete()

    def test_database_trigger_blocks_raw_sql(self):
        for sql in ("UPDATE audit_auditlog SET reason = 'x'", "DELETE FROM audit_auditlog"):
            with self.subTest(sql=sql):
                with self.assertRaises((IntegrityError, DatabaseError)):
                    with transaction.atomic(), connection.cursor() as cursor:
                        cursor.execute(sql)
        self.assertEqual(AuditLog.objects.get(pk=self.log.pk).reason, "thử")

    def test_admin_has_no_add_change_delete(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(reverse("admin:audit_auditlog_add")).status_code, 403)
        url = reverse("admin:audit_auditlog_delete", args=[self.log.pk])
        self.assertEqual(self.client.post(url, {"post": "yes"}).status_code, 403)
        self.assertTrue(AuditLog.objects.filter(pk=self.log.pk).exists())
        changelist = self.client.get(reverse("admin:audit_auditlog_changelist") + "?action=login")
        self.assertEqual(changelist.status_code, 200)


class AuditedAdminTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("chuquan", password="matkhau-thu-123", role=Role.CHU_QUAN)
        store = Store.get_default()
        group = MenuGroup.objects.create(store=store, name="Pha máy")
        self.item = MenuItem.objects.create(store=store, group=group, name="Trà đào")
        self.size = ItemSize.objects.create(item=self.item, name="M", price=35000)
        self.client.force_login(self.owner)

    def test_price_change_logged_with_before_and_after(self):
        # AC-114: đổi giá được ghi nhật ký với giá trước và sau.
        url = reverse("admin:catalog_menuitem_change", args=[self.item.pk])
        data = {
            "group": self.item.group_id, "name": "Trà đào", "status": "nhap", "sort_order": 0,
            "sizes-TOTAL_FORMS": 1, "sizes-INITIAL_FORMS": 1, "sizes-MIN_NUM_FORMS": 0, "sizes-MAX_NUM_FORMS": 1000,
            "sizes-0-id": self.size.pk, "sizes-0-item": self.item.pk, "sizes-0-name": "M",
            "sizes-0-price": 38000, "sizes-0-is_active": "on", "sizes-0-sort_order": 0,
        }
        response = self.client.post(url, data)
        self.assertRedirects(response, reverse("admin:catalog_menuitem_changelist"))
        self.size.refresh_from_db()
        self.assertEqual(self.size.price, 38000)
        log = AuditLog.objects.get(action=Action.UPDATE, object_type="catalog.ItemSize")
        self.assertEqual(log.before, {"price": 35000})
        self.assertEqual(log.after, {"price": 38000})
        self.assertEqual(log.actor, self.owner)
