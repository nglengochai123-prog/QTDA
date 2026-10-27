"""Trang dữ liệu nền riêng: quyền chỉ Chủ quán, ghi nhật ký, quy tắc nghiệp vụ giữ nguyên như trước."""

from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.audit.models import AuditLog
from apps.catalog.models import ItemSize, MenuItem, PriceRecord
from apps.inventory.models import Ingredient, RecipeLine, RecipeVersion, StockMovement
from apps.orders.tests.helpers import PASSWORD, build_menu
from apps.shifts.models import Shift
from apps.staff.models import Employee


def dt(value):
    return timezone.localtime(value).strftime("%Y-%m-%dT%H:%M")


class MasterDataTests(TestCase):
    def setUp(self):
        self.d = build_menu()
        self.manager = User.objects.create_user("thungan", password=PASSWORD, role=Role.THU_NGAN)
        self.client.login(username=self.d["owner"].username, password=PASSWORD)

    def url(self, key, pk=None, action=None):
        if action:
            return reverse("masterdata:action", args=[key, pk, action])
        return reverse("masterdata:edit", args=[key, pk]) if pk else reverse("masterdata:create", args=[key])

    def test_only_owner_and_every_list_opens(self):
        for key in ("ca", "nhan-vien", "ban", "nhom-mon", "mon", "tuy-chon", "ly-do", "nha-cung-cap", "nguyen-lieu",
                    "dinh-muc"):
            self.assertEqual(self.client.get(reverse("masterdata:list", args=[key])).status_code, 200, key)
            self.assertEqual(self.client.get(self.url(key)).status_code, 200, key)
        self.assertEqual(self.client.get(reverse("masterdata:audit_log")).status_code, 200)
        self.client.login(username="thungan", password=PASSWORD)
        self.assertEqual(self.client.get(reverse("masterdata:list", args=["mon"])).status_code, 403)
        self.assertEqual(self.client.post(self.url("ban"), {"code": "99", "seats": 2, "sort_order": 0}).status_code, 403)
        self.assertEqual(self.client.get(reverse("masterdata:audit_log")).status_code, 403)

    def test_add_shift_by_owner_is_logged(self):
        # Không còn Quản lý ca: Chủ quán tạo ca là người phụ trách duyệt; không cần người duyệt dự phòng.
        start = timezone.now() + timedelta(days=1)
        form = {"name": "Ca sáng", "starts_at": dt(start), "ends_at": dt(start + timedelta(hours=8))}
        r = self.client.post(self.url("ca"), {**form, "ends_at": dt(start - timedelta(hours=1))})
        self.assertContains(r, "Giờ kết thúc phải sau giờ bắt đầu")
        r = self.client.post(self.url("ca"), form)
        self.assertRedirects(r, reverse("masterdata:list", args=["ca"]))
        shift = Shift.objects.get()
        self.assertEqual((shift.store, shift.approver), (self.d["store"], self.d["owner"]))
        self.assertTrue(AuditLog.objects.filter(object_type="shifts.Shift", object_id=str(shift.pk), action="create").exists())
        page = self.client.get(self.url("ca"))
        self.assertContains(page, 'value="Ca sáng"')  # gợi ý ca kế tiếp

    def test_employee_account_password_and_quit_locks(self):
        r = self.client.post(self.url("nhan-vien"), {"full_name": "Lê Văn Bình", "phone": "0901234567",
                                                     "roles": [Role.PHUC_VU, Role.PHA_CHE], "hourly_wage": 25000,
                                                     "status": "dang_lam", "username": ""})
        self.assertEqual(r.status_code, 302)
        emp = Employee.objects.get(phone="0901234567")
        self.assertEqual(emp.user.username, "0901234567")
        self.assertFalse(emp.user.has_usable_password())
        r = self.client.post(self.url("nhan-vien", emp.pk, "mat-khau"),
                             {"mat-khau-password1": "Cafe-Lam-2026", "mat-khau-password2": "Cafe-Lam-2026"})
        emp.user.refresh_from_db()
        self.assertTrue(emp.user.check_password("Cafe-Lam-2026"))
        self.client.post(self.url("nhan-vien", emp.pk), {"full_name": "Lê Văn Bình", "phone": "0901234567",
                                                         "roles": [Role.PHUC_VU], "hourly_wage": 25000,
                                                         "status": "nghi_viec"})
        emp.user.refresh_from_db()
        self.assertFalse(emp.user.is_active)  # AC-75
        # Trùng số điện thoại thì không lưu (AC-74)
        r = self.client.post(self.url("nhan-vien"), {"full_name": "Người khác", "phone": "0901234567",
                                                     "roles": [Role.PHUC_VU], "hourly_wage": 0, "status": "dang_lam"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Employee.objects.filter(phone="0901234567").count(), 1)

    def test_menu_item_sizes_keep_price_history(self):
        item = self.d["item"]
        size = self.d["size_m"]
        prefix = "itemsize"
        data = {"name": item.name, "group": item.group_id, "status": item.status, "sort_order": 0,
                "option_groups": [g.pk for g in item.option_groups.all()],
                f"{prefix}-TOTAL_FORMS": 2, f"{prefix}-INITIAL_FORMS": 1, f"{prefix}-MIN_NUM_FORMS": 0,
                f"{prefix}-MAX_NUM_FORMS": 1000,
                f"{prefix}-0-id": size.pk, f"{prefix}-0-item": item.pk, f"{prefix}-0-name": "M",
                f"{prefix}-0-price": "27.000", f"{prefix}-0-sort_order": 0, f"{prefix}-0-is_active": "on",
                f"{prefix}-1-item": item.pk, f"{prefix}-1-name": "L", f"{prefix}-1-price": "32,000",
                f"{prefix}-1-sort_order": 1, f"{prefix}-1-is_active": "on"}
        r = self.client.post(self.url("mon", item.pk), data)
        self.assertEqual(r.status_code, 302, r.context and (r.context["form"].errors, [x["fs"].errors for x in r.context["formsets"]], [x["fs"].non_form_errors() for x in r.context["formsets"]]))
        size.refresh_from_db()
        self.assertEqual(size.price, 27000)
        self.assertEqual(list(PriceRecord.objects.filter(size=size).order_by("effective_from").values_list("price", flat=True)),
                         [25000, 27000])
        self.assertTrue(ItemSize.objects.filter(item=item, name="L", price=32000).exists())
        self.assertTrue(AuditLog.objects.filter(object_type="catalog.ItemSize", action="update").exists())

    def test_recipe_draft_lines_publish_and_copy(self):
        item = MenuItem.objects.create(store=self.d["store"], group=self.d["item"].group, name="Bạc xỉu")
        size = ItemSize.objects.create(item=item, name="M", price=29000)
        r = self.client.post(self.url("dinh-muc"), {"item": item.pk, "note": "Bản đầu"})
        draft = RecipeVersion.objects.get(item=item)
        self.assertRedirects(r, self.url("dinh-muc", draft.pk))
        p = "recipeline"
        r = self.client.post(self.url("dinh-muc", draft.pk), {
            "note": "Bản đầu", f"{p}-TOTAL_FORMS": 1, f"{p}-INITIAL_FORMS": 0, f"{p}-MIN_NUM_FORMS": 0,
            f"{p}-MAX_NUM_FORMS": 1000, f"{p}-0-version": draft.pk, f"{p}-0-size": size.pk,
            f"{p}-0-ingredient": self.d["coffee"].pk, f"{p}-0-quantity": "18"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(RecipeLine.objects.filter(version=draft).count(), 1)
        self.client.post(self.url("dinh-muc", draft.pk, "ap-dung"))
        draft.refresh_from_db()
        self.assertTrue(draft.is_published)
        page = self.client.get(self.url("dinh-muc", draft.pk))
        self.assertContains(page, "Chỉ xem")
        r = self.client.post(self.url("dinh-muc", draft.pk, "tao-ban-nhap"))
        new = RecipeVersion.objects.get(item=item, status="nhap")
        self.assertRedirects(r, self.url("dinh-muc", new.pk))
        self.assertEqual(new.lines.count(), 1)

    def test_opening_stock_once(self):
        ing = Ingredient.objects.create(store=self.d["store"], name="Trà đen", unit="g", pack_size=500, lead_time_days=2)
        self.client.post(self.url("nguyen-lieu", ing.pk, "ton-dau-ky"), {"ton-dau-ky-quantity": "500"})
        self.assertEqual(StockMovement.objects.filter(ingredient=ing).count(), 1)
        page = self.client.get(self.url("nguyen-lieu", ing.pk))
        self.assertNotContains(page, "Ghi tồn đầu kỳ")

    def test_issue_rule_set_from_ingredient_form(self):
        ing = Ingredient.objects.create(store=self.d["store"], name="Ly nhựa", unit="cai", pack_size=50, lead_time_days=2)
        self.assertContains(self.client.get(self.url("nguyen-lieu", ing.pk)), "Quy tắc xuất lô")
        form = {"name": "Ly nhựa", "unit": "cai", "pack_size": "50", "lead_time_days": "2", "safety_stock": "0",
                "moq_packs": "1", "exposure_days": "1", "is_active": "on", "issue_rule": "lifo"}
        r = self.client.post(self.url("nguyen-lieu", ing.pk), {**form, "shelf_life_days": "7"})
        self.assertContains(r, "Hàng có hạn dùng không xuất theo kiểu nhập sau, xuất trước")
        r = self.client.post(self.url("nguyen-lieu", ing.pk), form)
        self.assertEqual(r.status_code, 302)
        ing.refresh_from_db()
        self.assertEqual((ing.issue_rule, ing.rule_short), ("lifo", "Nhập sau"))
        self.assertContains(self.client.get(reverse("masterdata:list", args=["nguyen-lieu"])), "Nhập sau")

    def test_number_fields_read_vietnamese_thousands(self):
        # Ô số trong Dữ liệu nền: "1.000" là một nghìn, không phải 1; hiện lại đúng như đã gõ.
        ing = Ingredient.objects.create(store=self.d["store"], name="Sữa tươi", unit="ml", pack_size=50, lead_time_days=2)
        form = {"name": "Sữa tươi", "unit": "ml", "pack_size": "1.000", "lead_time_days": "2", "safety_stock": "1.500,5",
                "moq_packs": "1", "exposure_days": "1", "is_active": "on"}
        self.assertEqual(self.client.post(self.url("nguyen-lieu", ing.pk), form).status_code, 302)
        ing.refresh_from_db()
        self.assertEqual((ing.pack_size, ing.safety_stock), (1000, Decimal("1500.5")))
        page = self.client.get(self.url("nguyen-lieu", ing.pk))
        self.assertContains(page, 'value="1.000"')
        self.assertContains(page, 'value="1.500,5"')
        self.assertNotContains(page, "---------")
        self.assertContains(page, "Tự chọn theo hạn dùng")
        self.assertContains(self.client.get(reverse("masterdata:list", args=["nguyen-lieu"])), "1.500,5")
        r = self.client.post(self.url("nguyen-lieu", ing.pk), {**form, "pack_size": "1.0.0"})
        self.assertContains(r, "Nhập một số, ví dụ 1.000 hoặc 1,5.")
        # Nhật ký hiện tên trường và số như người đọc, không hiện khóa nội bộ.
        log = self.client.get(reverse("masterdata:audit_log"), {"loai": "inventory.Ingredient"})
        self.assertContains(log, "Quy cách đóng gói")
        self.assertContains(log, "<b>1.000</b>", html=False)
        self.assertNotContains(log, "pack_size")

    def test_audit_log_filters(self):
        r = self.client.get(reverse("masterdata:audit_log"), {"thao_tac": "login"})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(all(log.action == "login" for log in r.context["page"].object_list))
