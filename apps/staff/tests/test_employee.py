from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import Role, User
from apps.accounts.permissions import Cap, user_can
from apps.staff.models import Employee, EmploymentStatus


class EmployeeTests(TestCase):
    def test_create_profile_with_account_and_two_roles(self):
        # AC-74
        emp = Employee.create_with_account(full_name="Nguyễn Văn An", phone="0905123456",
                                           roles=[Role.PHA_CHE, Role.PHUC_VU], hourly_wage=25000)
        self.assertEqual(emp.status, EmploymentStatus.WORKING)
        self.assertEqual(emp.user.username, "0905123456")
        self.assertTrue(emp.user.is_active)
        self.assertFalse(emp.user.has_usable_password())
        self.assertEqual(emp.user.roles, {Role.PHA_CHE, Role.PHUC_VU})
        self.assertTrue(user_can(emp.user, Cap.BAR_PREPARE))
        self.assertTrue(user_can(emp.user, Cap.ORDER_CREATE))
        self.assertFalse(user_can(emp.user, Cap.PAYMENT))

    def test_duplicate_phone_rejected(self):
        Employee.create_with_account(full_name="Trần Bình", phone="0905000001", roles=[Role.PHUC_VU])
        with self.assertRaises(ValidationError):
            Employee.create_with_account(full_name="Lê Chi", phone="0905000001", roles=[Role.PHUC_VU],
                                         username="lechi")

    def test_roles_required_and_valid(self):
        with self.assertRaises(ValidationError):
            Employee.create_with_account(full_name="Lê Chi", phone="0905000002", roles=[])

    def test_leaving_locks_account_immediately(self):
        # AC-75 / BRU-38
        emp = Employee.create_with_account(full_name="Phạm Dũng", phone="0905000003", roles=[Role.PHUC_VU])
        emp.status = EmploymentStatus.LEFT
        emp.save()
        emp.user.refresh_from_db()
        self.assertFalse(emp.user.is_active)
        self.assertFalse(user_can(emp.user, Cap.ORDER_CREATE))
        emp.status = EmploymentStatus.WORKING
        emp.save()
        emp.user.refresh_from_db()
        self.assertTrue(emp.user.is_active)

    def test_owner_creates_profile_in_admin(self):
        owner = User.objects.create_user("chuquan", password="matkhau-thu-123", role=Role.CHU_QUAN)
        self.client.force_login(owner)
        response = self.client.post(reverse("admin:staff_employee_add"), {
            "full_name": "Võ Thị Em", "phone": "0905000004", "roles": [Role.THU_NGAN, Role.PHUC_VU],
            "hourly_wage": 24000, "status": EmploymentStatus.WORKING, "username": "",
        })
        self.assertEqual(response.status_code, 302)
        emp = Employee.objects.get(phone="0905000004")
        self.assertEqual(emp.user.username, "0905000004")
        self.assertEqual(emp.user.role, Role.THU_NGAN)

    def test_non_owner_cannot_open_profiles(self):
        manager = User.objects.create_user("qlca", password="matkhau-thu-123", role=Role.THU_NGAN)
        self.client.force_login(manager)
        self.assertEqual(self.client.get(reverse("admin:staff_employee_changelist")).status_code, 302)
