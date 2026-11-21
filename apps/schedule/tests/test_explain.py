"""Câu giải thích vì sao gợi ý N người khớp đúng công thức hàng đợi đã dùng để gợi ý."""
from django.test import SimpleTestCase

from apps.schedule import staffing
from apps.schedule.explain import explain


def basis(hours, rate=20.0, minimum=1, **extra):
    b = {"cups": 330, "cups_mean": 300, "cups_source": "Dự báo phát hành 18/11", "unit": "tải",
         "unit_label": "tải pha chế", "rate": rate, "rate_source": "Đo ở các giờ mọi pha chế đều bận, 8 tuần qua",
         "wait_minutes": 5, "service_percent": 90, "scv": 1.4, "minimum": minimum, "uncovered": [],
         "hours": hours}
    b.update(extra)
    return b


def need(load, rate=20.0, minimum=1):
    return staffing.servers_needed(load, rate, 5 / 60, 0.9, 1.4, minimum)


class ExplainTests(SimpleTestCase):
    def test_peak_hour_drives_number_and_fewer_people_falls_short(self):
        loads = {7: 30.0, 8: 55.0, 9: 40.0}
        hours = [[h, v, need(v)] for h, v in loads.items()]
        n = max(x[2] for x in hours)
        why = explain(n, basis(hours), "Pha chế")
        text = " ".join(why["lines"])
        self.assertEqual(why["peak"], 8)
        self.assertIn("8–9 giờ", why["short"])
        self.assertIn("khoảng 300 ly", text)
        self.assertIn("đủ cho 330 ly", text)
        self.assertIn("55 món quy đổi", text)
        self.assertIn("món được bắt đầu pha", why["short"])
        ok = staffing.wait_ok_probability(n, 55.0, 20.0, 5 / 60, 1.4)
        fewer = staffing.wait_ok_probability(n - 1, 55.0, 20.0, 5 / 60, 1.4)
        self.assertGreaterEqual(ok, 0.9)
        self.assertLess(fewer, 0.9)
        self.assertIn(f"Với {n} pha chế", text)
        self.assertIn(f"còn {n - 1} người", text)

    def test_low_load_says_minimum_rule(self):
        why = explain(2, basis([[14, 3.0, 2]], minimum=2), "Thu ngân")
        self.assertIn("tối thiểu 2", why["short"])
        self.assertIn("chỉ cần 1 thu ngân", " ".join(why["lines"]))

    def test_overlapping_shift_shares_peak(self):
        why = explain(1, basis([[8, 55.0, need(55.0)]]), "Pha chế")
        self.assertIn("ca chồng giờ góp thêm", why["short"])

    def test_assumed_rate_is_flagged(self):
        why = explain(1, basis([[9, 12.0, 1]], unit="lượt", rate_kind="standard", rate_source="Theo thời gian chuẩn 2 phút mỗi lượt"), "Phục vụ")
        self.assertIn("số giả định, chưa đo được ở quán", " ".join(why["lines"]))
        self.assertIn("lượt phục vụ có người làm", why["short"])

    def test_no_basis_no_explanation(self):
        self.assertIsNone(explain(None, {}, "Pha chế"))
        self.assertIsNone(explain(2, {"missing": "Chưa đủ dữ liệu"}, "Pha chế"))
