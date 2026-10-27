"""Phân tích bán hàng, biểu đồ và các trang báo cáo có biểu đồ (bảng điều khiển, doanh thu, kho, tải nhân sự)."""

import tempfile
from datetime import timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from apps.inventory import lots
from apps.inventory import operations as ops
from apps.inventory.models import Supplier
from apps.orders import payments
from apps.orders.models import Order
from apps.orders.tests.helpers import PASSWORD
from apps.orders.tests.test_adjust_pay import Base, key
from apps.reports import charts, insights, services


def photo():
    return SimpleUploadedFile("hd.jpg", b"\xff\xd8\xffjpeg", content_type="image/jpeg")


@override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix="lam-test-media-"))
class InsightTests(Base):
    def paid(self, quantity=1, method="tien_mat"):
        order, line = self.order(quantity=quantity)
        self.finish(line)
        payments.pay_table(self.cashier, key(), order.table_id, method, transfer_confirmed=True)
        return Order.objects.get(pk=order.pk)

    def prices(self):
        supplier = Supplier.objects.create(store=self.d["store"], name="NCC mẫu")
        ops.create_receipt(self.d["owner"], key(), supplier.pk, [
            {"ingredient": self.d["coffee"].pk, "quantity": "1000", "unit_price": 300},
            {"ingredient": self.d["milk"].pk, "quantity": "380", "unit_price": 60}], "tra_ngay", invoice_photo=photo())

    def test_kpis_cost_of_goods_from_actual_stock_draws(self):
        self.prices()
        self.paid(2)
        today = timezone.localdate()
        s = insights.sales(today, today)
        # 2 ly × (20 g cà phê × 300 đ + 30 ml sữa đặc × 60 đ) = 15.600 đ giá vốn
        self.assertEqual(s["revenue"], 50000)
        self.assertEqual(round(s["cost"]), 15600)
        kpi = {k["label"]: k for k in s["kpis"]}
        self.assertEqual(kpi["Doanh thu"]["value"], 50000)
        self.assertEqual(kpi["Số đơn"]["value"], 1)
        self.assertEqual(kpi["Giá trị mỗi đơn"]["value"], 50000)
        self.assertEqual(kpi["Lãi gộp ước tính"]["value"], 34400)
        self.assertIsNone(kpi["Doanh thu"]["delta"])  # kỳ trước chưa bán
        self.assertTrue(any("Giá vốn nguyên liệu bằng 31% doanh thu" in n for n in s["notes"]))
        self.assertIsNotNone(s["heat_chart"])
        self.assertIsNone(s["matrix_chart"])  # cần ít nhất hai món để chia ô

    def test_daily_usage_counts_only_days_with_ledger(self):
        self.paid(2)
        rate = lots.daily_usage([self.d["coffee"].pk])[self.d["coffee"].pk]
        self.assertAlmostEqual(rate, 40)  # sổ kho mới có từ hôm nay: chia 1 ngày, không chia 28

    def test_dimension_charts_pick_a_form_per_dimension(self):
        self.paid(2)
        self.paid(1, "chuyen_khoan")
        today = timezone.localdate()
        kinds = {dim: insights.dimension_chart(services.revenue(today, today, dim))[0] for dim in services.DIMENSIONS}
        self.assertEqual(kinds["ngay"], None)  # ngày dùng đường xu hướng chung
        self.assertEqual(kinds["khung_gio"], "columns")
        self.assertEqual(kinds["phuong_thuc"], "share")
        self.assertEqual(kinds["mon"], "hbars")

    def test_report_pages_render_charts(self):
        self.prices()
        self.paid(2)
        ops.record_waste(self.d["barista"], key(), self.d["coffee"].pk, "50", "do_vo")
        self.client.login(username=self.d["owner"].username, password=PASSWORD)
        page = self.client.get(reverse("reports:dashboard"))
        for text in ("Giờ đông khách", "Món mang lại doanh thu", "Kho cần chú ý", "Nhận định", 'class="chart-svg"'):
            self.assertContains(page, text)
        today = timezone.localdate().isoformat()
        for dim in services.DIMENSIONS:
            r = self.client.get(reverse("reports:revenue"), {"tu": today, "den": today, "theo": dim})
            self.assertEqual(r.status_code, 200, dim)
            self.assertContains(r, "chart-svg" if dim != "phuong_thuc" else "share-legend")
        r = self.client.get(reverse("reports:inventory"))
        self.assertContains(r, "Nhận định")
        self.assertContains(r, "hao hụt nhiều nhất")
        r = self.client.get(reverse("staff:workload"))
        self.assertContains(r, "Số ly theo khung giờ")


class ChartGeometryTests(Base):
    def test_scatter_labels_never_overlap(self):
        points = [{"x": 50 + i % 3, "y": 20 + (i % 2), "label": f"Món số {i}", "tip": str(i)} for i in range(8)]
        c = charts.scatter(points, 40, 15, width=charts.HALF, label_top=8)
        boxes = []
        for d in c["dots"]:
            if not d["show"]:
                continue
            w = len(d["text"]) * 6.2 + 4
            x0 = d["lx"] if d["anchor"] == "start" else d["lx"] - w
            boxes.append((x0, d["ly"] - 6.5, x0 + w, d["ly"] + 6.5))
        self.assertTrue(boxes)
        for i, a in enumerate(boxes):
            for b in boxes[i + 1:]:
                self.assertFalse(a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3], (a, b))

    def test_ranges_axis_hugs_the_data(self):
        c = charts.ranges([{"label": "A", "lo": 9, "mid": 24, "hi": 43, "tip": ""}], width=charts.HALF)
        self.assertEqual(c["ticks"][-1]["text"], "50")
        self.assertGreater(c["rows"][0]["bw"], 0)

    def test_line_end_label_does_not_collide_with_last_regular_label(self):
        labels = [f"{d:02d}/10" for d in range(1, 27)]
        c = charts.line(labels, [{"name": "a", "values": list(range(26)), "slot": 1}], width=charts.HALF)
        shown = [i for i, h in enumerate(c["hits"]) if h["show_label"]]
        self.assertEqual(shown[-1], 25)
        step = c["hits"][1]["cx"] - c["hits"][0]["cx"]
        self.assertGreaterEqual((shown[-1] - shown[-2]) * step, 36)


@override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix="lam-test-media-"))
class LotAlertTests(Base):
    def test_expired_lot_raises_alert_and_closes_after_disposal(self):
        from apps.control import alerts
        from apps.control.models import Alert

        supplier = Supplier.objects.create(store=self.d["store"], name="NCC sữa")
        today = timezone.localdate()
        result, _ = ops.create_receipt(self.d["owner"], key(), supplier.pk, [
            {"ingredient": self.d["milk"].pk, "quantity": "380", "unit_price": 60, "expiry_date": today.isoformat()}],
            "tra_ngay", invoice_photo=photo())
        later = timezone.now() + timedelta(days=2)
        alerts.sync(later)
        alert = Alert.objects.get(kind=Alert.Kind.LOT_EXPIRED)
        self.assertEqual(alert.assignee_role, "pha_che")
        self.assertEqual(alert.link, "/kho/lay-hang/")
        self.assertIn(result["lots"][0], alert.title)
        lot = self.d["milk"].lots.get(code=result["lots"][0])
        ops.dispose_lot(self.d["owner"], key(), lot.pk, note="Hộp phồng")
        alerts.sync(later)
        alert.refresh_from_db()
        self.assertTrue(alert.auto_closed)
