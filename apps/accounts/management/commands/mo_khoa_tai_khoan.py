from django.core.management.base import BaseCommand, CommandError

from apps.audit.models import Action
from apps.audit.services import record


class Command(BaseCommand):
    help = ("Mở khóa một tài khoản bị tạm khóa vì nhập sai mật khẩu nhiều lần. Dùng khi chính Chủ quán bị khóa "
            "và không còn Chủ quán nào khác mở được trên màn hình; quên mật khẩu thì chạy changepassword trước.")

    def add_arguments(self, parser):
        parser.add_argument("username", help="Tên đăng nhập cần mở khóa")

    def handle(self, *args, username, **options):
        from apps.accounts.models import User

        user = User.objects.filter(username=username).first()
        if user is None:
            raise CommandError(f"Không có tài khoản {username}.")
        if not (user.locked_until or user.failed_login_count):
            self.stdout.write(f"Tài khoản {username} không bị khóa.")
            return
        user.reset_failed_logins()
        record(Action.UPDATE, obj=user, actor_label="dòng lệnh", after={"tam_khoa": "đã mở"},
               reason="Mở khóa bằng lệnh mo_khoa_tai_khoan")
        self.stdout.write(f"Đã mở khóa tài khoản {username}; đăng nhập lại được ngay.")
