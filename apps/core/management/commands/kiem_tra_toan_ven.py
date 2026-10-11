from django.core.management.base import BaseCommand

from apps.core import integrity


class Command(BaseCommand):
    help = "Đối chiếu chéo sổ kho, đơn, giao dịch tiền và ca; in các điểm không khớp."

    def handle(self, *args, **options):
        found = integrity.problems()
        for line in found:
            self.stdout.write(f"- {line}")
        self.stdout.write("Không phát hiện sai lệch." if not found else f"Có {len(found)} điểm cần xem lại.")
