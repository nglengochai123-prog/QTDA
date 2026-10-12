"""Bỏ vai trò Quản lý ca (Chủ quán quyết định ngày 12/10/2026): tài khoản và hồ sơ đang mang vai trò này chuyển sang Thu ngân.

Dữ liệu lịch sử (chấm công, nhật ký, khoản chênh lệch) giữ nguyên.
"""

from django.db import migrations


def forwards(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    Employee = apps.get_model("staff", "Employee")
    User.objects.filter(role="quan_ly_ca").update(role="thu_ngan")
    for emp in Employee.objects.all():
        roles = list(emp.roles or [])
        if "quan_ly_ca" in roles:
            new = []
            for r in ["thu_ngan" if r == "quan_ly_ca" else r for r in roles]:
                if r not in new:
                    new.append(r)
            emp.roles = new
            emp.save(update_fields=["roles"])


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0002_remove_user_phone_user_failed_login_count_and_more"),
        ("staff", "0002_attendance"),
    ]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
