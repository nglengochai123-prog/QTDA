from django.core.management.base import BaseCommand, CommandError

from apps.core import backup


class Command(BaseCommand):
    help = "Sao lưu CSDL (và ảnh chứng từ) ra thư mục LAM_BACKUP_DIR, giữ LAM_BACKUP_KEEP bản mới nhất (NFR-09)."

    def add_arguments(self, parser):
        parser.add_argument("--thu-muc", help="Thư mục đích, mặc định LAM_BACKUP_DIR")
        parser.add_argument("--giu", type=int, help="Số bản giữ lại, mặc định LAM_BACKUP_KEEP")

    def handle(self, *args, **options):
        try:
            target, removed = backup.make_backup(options.get("thu_muc"), options.get("giu"))
        except Exception as error:  # in lỗi rõ để Task Scheduler ghi vào nhật ký
            raise CommandError(f"Sao lưu thất bại: {error}") from error
        self.stdout.write(f"Đã sao lưu: {target} ({target.stat().st_size // 1024} KB)")
        for name in removed:
            self.stdout.write(f"Đã xóa bản cũ: {name}")
