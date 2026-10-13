"""Nhập đơn giả định từ Excel vào cơ sở dữ liệu chạy thử: giữ giờ trong tệp, ca đã kết có báo cáo, khớp tổng tiền."""

import io
import tempfile
from pathlib import Path

from django.core.management import CommandError, call_command
from django.test import TestCase
from django.utils import timezone

from apps.core import xlsx
from apps.forecast import services as forecast
from apps.orders.models import Order, Payment

from .helpers import build_menu


class SimulatedOrderImportTests(TestCase):
    def test_imports_paid_orders_on_closed_shifts(self):
        d = build_menu()
        # 46113 = 01/04/2026 trong Excel
        data = xlsx.build([
            ("Don_hang", [["Mã đơn", "Lúc tạo", "Lúc trả", "Thanh toán", "Trạng thái", "Số ly", "Dòng", "Tổng tiền"],
                          ["GD-20260401-001", 46113.375, 46113.4, "Tiền mặt", "Đã thanh toán", 3, 2, 83000]]),
            ("Chi_tiet_mon", [["Mã dòng", "Mã đơn", "Ngày", "Mã món", "Tên món", "Cỡ", "Số ly", "Giá", "Topping",
                               "Phụ thu", "Đường", "Đá", "Thành tiền"],
                              ["1", "GD-20260401-001", 46113, "M02", "Cà phê sữa", "M", 2, 25000, "Không", 0,
                               "Bình thường", "Ít đá", 50000],
                              ["2", "GD-20260401-001", 46113, "M02", "Cà phê sữa", "M", 1, 25000, "Kem muối", 8000,
                               "Bình thường", "Bình thường", 33000]]),
        ])
        path = Path(tempfile.mkdtemp()) / "gia_dinh.xlsx"
        path.write_bytes(data)
        with self.assertRaises(CommandError):
            call_command("nhap_don_gia_dinh", str(path), stdout=io.StringIO())  # thiếu --chay-thu
        call_command("nhap_don_gia_dinh", str(path), "--chay-thu", stdout=io.StringIO())
        order = Order.objects.get(code="GD-20260401-001")
        self.assertEqual(order.status, Order.Status.PAID)
        self.assertEqual(timezone.localtime(order.created_at).strftime("%d/%m %H:%M"), "01/04 09:00")
        self.assertEqual(sum(l.line_total for l in order.lines.all()), 83000)
        self.assertEqual(Payment.objects.get().amount, 83000)
        self.assertEqual(order.lines.get(position=2).options.get().option, d["cream"])
        self.assertEqual(order.shift.report.counted_cash, 83000)
        day = timezone.localtime(order.created_at).date()
        self.assertEqual(forecast.day_status(day, day, today=day.replace(month=5))[day], "du_dieu_kien")
        with self.assertRaises(CommandError):
            call_command("nhap_don_gia_dinh", str(path), "--chay-thu", stdout=io.StringIO())  # không nhập hai lần
