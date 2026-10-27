"""Phần lõi bổ sung theo khung lý thuyết: nhiễu quan sát và độ phân tán (3.1), chọn cấu hình qua đánh giá và chỉ áp dụng
khi Chủ quán duyệt (3.1, 6.1), độ nhạy nhận định (2.1), kiểm tra nhận định bằng kịch bản (6.1), đối chiếu các lần phát
hành (6.1), nhập lịch sử bán lưu riêng thật và mô phỏng (6.1)."""

import io
import math
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.forecast import dglm, evaluate, services
from apps.forecast.models import ExpertJudgement, HistoryBatch, MethodDecision, SeriesConfig
from apps.orders.tests.helpers import PASSWORD, build_menu

from .test_forecast import fake_history


class DispersionTests(TestCase):
    def run_model(self, ys, v):
        m, C = dglm.prior_state((60, 2), (60, 2))
        model = dglm.PoissonDGLM(m, C, 0.95, 0.99, obs_var=v)
        pts = []
        for y in ys:
            a, b, *_ = model.predictive(0)
            pts.append((a, b, y))
            model.update(y, 0)
        return dglm.dispersion(pts[20:])

    def test_overdispersed_sales_are_detected_and_observation_noise_fixes_it(self):
        rng = dglm.make_rng("phan-tan")
        poisson_ys = [dglm.poisson(30, rng) for _ in range(150)]
        noisy_ys = [dglm.poisson(30 * math.exp(rng.gauss(0, 0.35)), rng) for _ in range(150)]
        self.assertLess(abs(self.run_model(poisson_ys, 0.0) - 1), 0.4)
        over = self.run_model(noisy_ys, 0.0)
        fixed = self.run_model(noisy_ys, 0.10)
        self.assertGreater(over, 1.8)  # Poisson thuần đánh giá thấp độ biến động
        self.assertLess(abs(fixed - 1), abs(over - 1))
        a0, b0, *_ = dglm.PoissonDGLM(*dglm.prior_state((60, 2), (60, 2)), 0.95, 0.99).predictive(0)
        a1, b1, *_ = dglm.PoissonDGLM(*dglm.prior_state((60, 2), (60, 2)), 0.95, 0.99, obs_var=0.1).predictive(0)
        self.assertLess(a1, a0)  # nhiễu quan sát làm phân phối dự báo rộng hơn


class CoreTests(TestCase):
    def setUp(self):
        self.d = build_menu()
        self.owner, self.size = self.d["owner"], self.d["size_m"]
        self.today = timezone.localdate()
        for day_type, typical, low, high in (("ngay_thuong", 20, 12, 28), ("cuoi_tuan", 30, 20, 40)):
            ExpertJudgement.objects.create(store=self.d["store"], size=self.size, day_type=day_type, typical=typical,
                                           low=low, high=high, basis="Sổ bán", provided_by=self.owner)

    def test_evaluation_selects_config_reports_dispersion_and_sensitivity(self):
        with mock.patch("apps.forecast.evaluate.history",
                        return_value=fake_history(self.size.pk, 84, self.today, weekday=24, weekend=36)):
            r = evaluate.evaluate(self.today)["rows"][0]
        self.assertIn(r["obs_var"], evaluate.OBS_VARS)
        self.assertIsNotNone(r["dispersion"]["test"])
        self.assertEqual([x["factor"] for x in r["sensitivity"]], [0.5, 1, 2])

    def test_config_used_only_after_owner_approves_model(self):
        hist = fake_history(self.size.pk, 84, self.today, weekday=24, weekend=36)
        with mock.patch("apps.forecast.services.history", return_value=hist):
            rel = services.release(user=self.owner)
        self.assertFalse(any("đã được Chủ quán duyệt" in x for x in rel.series.get().limitations))
        self.client.login(username=self.owner.username, password=PASSWORD)
        with mock.patch("apps.forecast.evaluate.history", return_value=hist):
            self.client.post(reverse("forecast:choose_method", args=[self.size.pk]),
                             {"method": "bayes", "note": "Thử nghiệm có theo dõi"})
        cfg = SeriesConfig.objects.get(size=self.size)
        self.assertIsNotNone(cfg.approved_at)
        self.assertIn("dispersion", cfg.evidence)
        with mock.patch("apps.forecast.services.history", return_value=hist):
            rel = services.release(user=self.owner)
        s = rel.series.get()
        self.assertEqual(s.method, "bayes")
        self.assertTrue(any("đã được Chủ quán duyệt" in x for x in s.limitations))
        MethodDecision.objects.create(store=self.d["store"], size=self.size, method="uoc_tinh", decided_by=self.owner)
        self.assertIsNone(services.approved_config(self.size.pk))  # quay về ước tính ban đầu thì bỏ cấu hình

    def test_prior_check_scenarios_match_judgement(self):
        check = services.prior_check(self.size.pk)
        self.assertTrue(10 <= check["weekday"][0] <= 15 and 25 <= check["weekday"][1] <= 31)
        self.assertLess(check["week"][0], check["week"][1])
        self.assertLess(check["week"][1], check["week"][2])

    def test_release_accuracy_compares_stored_forecasts(self):
        hist = fake_history(self.size.pk, 30, self.today)
        old_day = self.today - timedelta(days=10)
        with mock.patch("apps.forecast.services.history", return_value=hist):
            with mock.patch("django.utils.timezone.localdate", return_value=old_day):
                rel = services.release(user=self.owner)
            rel.first_day = old_day
            rel.save()
            acc = services.release_accuracy(self.today)
        self.assertTrue(acc["buckets"])
        self.assertEqual(acc["buckets"][0]["label"], "1 ngày")

    def test_history_import_merges_real_but_not_simulated(self):
        start = self.today - timedelta(days=20)
        lines = ["Ngày;Món;Kích cỡ;Số lượng;Trạng thái"]
        for k in range(14):
            d = start + timedelta(days=k)
            status = "Đóng cửa" if k == 3 else ("Thiếu hàng" if k == 5 else "")
            lines.append(f"{d:%d/%m/%Y};Cà phê sữa;M;{20 + k};{status}")
        lines.append(f"{start:%d/%m/%Y};Món lạ;L;3;")
        data = "\n".join(lines).encode("utf-8")
        batch = services.import_history(io.BytesIO(data), "ban.csv", HistoryBatch.Kind.REAL, self.owner)
        self.assertEqual(batch.summary["days"], 14)
        self.assertEqual(batch.summary["unmatched"], {"Món lạ L": 1})
        dates, status, cups, flags = services.history(self.today)
        self.assertEqual(status[start + timedelta(days=3)], "dong_cua")
        self.assertEqual(cups[self.size.pk][start], 20)
        self.assertIn(start + timedelta(days=5), services.size_flags(flags, self.size.pk))
        sim = services.import_history(io.BytesIO(data.replace(b";20;", b";99;")), "mo-phong.csv",
                                      HistoryBatch.Kind.SIMULATED, self.owner)
        self.assertEqual(services.history(self.today)[2][self.size.pk][start], 20)  # mô phỏng không lẫn vào
        self.assertEqual(services.history(self.today, include_simulated=True)[2][self.size.pk][start], 119)
        sim.active = False
        sim.save()
        self.client.login(username=self.owner.username, password=PASSWORD)
        page = self.client.get(reverse("forecast:history"))
        self.assertContains(page, "ban.csv")
        self.assertContains(page, f"{start:%d/%m/%Y} →")  # ngày ghi kiểu Việt Nam, không phải 2026-10-06
        # Tệp lưu bằng bảng mã khác UTF-8: báo cách sửa bằng tiếng Việt, không in lỗi của Python.
        from django.core.files.uploadedfile import SimpleUploadedFile
        bad = SimpleUploadedFile("ban.csv", "Ngày;Món\n01/10/2026;Cà phê".encode("cp1258"))
        r = self.client.post(reverse("forecast:history"), {"file": bad, "kind": HistoryBatch.Kind.REAL}, follow=True)
        self.assertContains(r, "CSV UTF-8")
        self.assertNotContains(r, "codec")
        # Không dòng nào khớp thì báo rõ lý do, không tạo lần nhập rỗng; dòng hỏng hoặc ngày tương lai được kể ra.
        before = HistoryBatch.objects.count()
        none = SimpleUploadedFile("sai.csv", f"Ngày;Món;Số ly\n{start:%d/%m/%Y};Món lạ;3\nhôm qua;Cà phê sữa;2".encode())
        r = self.client.post(reverse("forecast:history"), {"file": none, "kind": HistoryBatch.Kind.REAL}, follow=True)
        self.assertContains(r, "Không có dòng nào nhập được (1 dòng không đọc được ngày hoặc số ly, món không khớp")
        self.assertEqual(HistoryBatch.objects.count(), before)
        mixed = SimpleUploadedFile("mot-phan.csv", f"Ngày;Món;Kích cỡ;Số ly\n{start:%d/%m/%Y};Cà phê sữa;M;5\n"
                                   f"{self.today:%d/%m/%Y};Cà phê sữa;M;7\nxx;Cà phê sữa;M;1".encode())
        r = self.client.post(reverse("forecast:history"), {"file": mixed, "kind": HistoryBatch.Kind.REAL}, follow=True)
        self.assertContains(r, "Đã nhập 5 ly trong 1 ngày")
        self.assertContains(r, "Đã bỏ qua 1 dòng không đọc được ngày hoặc số ly, 1 dòng từ hôm nay trở đi.")
        _ = Decimal
