from django.core.management.base import BaseCommand, CommandError

from apps.core import backup


class Command(BaseCommand):
    help = ("Phục hồi một bản sao lưu vào CSDL riêng (không đè CSDL đang chạy) rồi kiểm tra cấu trúc và toàn vẹn. "
            "Ví dụ: manage.py phuc_hoi backups/lamcoffee-20261012-230000.sqlite3 --vao backups/thu-phuc-hoi.sqlite3")

    def add_arguments(self, parser):
        parser.add_argument("ban_sao_luu", nargs="?", help="Tệp .sqlite3 hoặc .dump; bỏ trống để dùng bản mới nhất")
        parser.add_argument("--vao", required=True, help="Tệp SQLite đích hoặc tên CSDL PostgreSQL đích")
        parser.add_argument("--ghi-de", action="store_true", help="Cho phép thay bản thử đã có ở đích")
        parser.add_argument("--cap-nhat-cau-truc", action="store_true",
                            help="Áp các bước cập nhật cấu trúc còn thiếu lên bản phục hồi (khi sao lưu trước lần cập nhật mã)")
        parser.add_argument("--danh-sach", action="store_true", help="Chỉ liệt kê các bản sao lưu hiện có")

    def handle(self, *args, **options):
        if options["danh_sach"]:
            for p in backup.backups():
                self.stdout.write(f"{p.name}  {p.stat().st_size // 1024} KB")
            return
        source = options["ban_sao_luu"] or (backup.backups() or [None])[-1]
        if source is None:
            raise CommandError("Chưa có bản sao lưu nào.")
        try:
            env = backup.restore(source, options["vao"], overwrite=options["ghi_de"])
        except (ValueError, FileNotFoundError, RuntimeError) as error:
            raise CommandError(str(error)) from error
        self.stdout.write(f"Đã phục hồi {source} vào {options['vao']}.")
        failed = False
        for name, code, output in backup.verify(env, migrate=options["cap_nhat_cau_truc"]):
            self.stdout.write(f"[{name}] {'đạt' if code == 0 else 'lỗi'}: {output.splitlines()[-1] if output else 'không có thông báo'}")
            failed = failed or code != 0 or "cần xem lại" in output
        if failed:
            raise CommandError("CSDL phục hồi chưa đạt kiểm tra, xem các dòng trên.")
        self.stdout.write("CSDL phục hồi đạt kiểm tra. Khi cần dùng thật: dừng máy chủ, trỏ SQLITE_NAME hoặc DB_NAME tới đích này, "
                          "chạy lại máy chủ.")
