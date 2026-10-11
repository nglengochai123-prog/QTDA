import time

from django.core.management.base import BaseCommand

from apps.core import periodic


class Command(BaseCommand):
    help = "Chạy các kiểm tra quá hạn (chuyển cấp duyệt, giao chậm). Dùng --lap N để lặp mỗi N giây."

    def add_arguments(self, parser):
        parser.add_argument("--lap", type=int, default=0, help="Lặp lại sau mỗi N giây; 0 là chạy một lần.")

    def handle(self, *args, lap=0, **options):
        while True:
            result = periodic.run_all()
            self.stdout.write(f"Chuyển cấp {len(result['chuyen_cap_yeu_cau'])} yêu cầu; "
                              f"{len(result['dat_hang_giao_cham'])} lần đặt giao chậm; "
                              f"nhắc {len(result['nhac_ca_thieu_du_phong'])} ca thiếu người duyệt dự phòng.")
            if not lap:
                break
            time.sleep(lap)
