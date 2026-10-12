"""Thực đơn và công thức thật của LAM Coffee do Chủ quán gửi ngày 12/10/2026.

Công thức ghi theo đơn vị pha chế (ml cà phê, ml nước đường, ml foam). Kho theo dõi nguyên liệu mua vào, nên các
bán thành phẩm được quy ra nguyên liệu gốc theo tỷ lệ Chủ quán cho (BASES). Nước lọc và đá không tính.
Món chưa có giá: tạo ở trạng thái Đang soạn, một cỡ "Chuẩn" giá 0 để Chủ quán nhập giá rồi mới mở bán.
"""

from decimal import Decimal as D

# Nguyên liệu kho: tên -> đơn vị tính (g, ml, cai, qua, goi)
INGREDIENTS = {
    "Cà phê bột": "g", "Đường cát": "g", "Đường gói": "goi", "Đường phèn": "g", "Muối": "g",
    "Sữa đặc": "ml", "Sữa tươi": "ml", "Kem béo Rich": "ml", "Nước cốt dừa": "ml", "Bột kem trứng": "g",
    "Kem dừa (viên)": "cai", "Kem socola (viên)": "cai", "Sương sáo (viên)": "cai",
    "Bột cacao": "g", "Bột matcha": "g", "Bột khoai môn": "g",
    "Chanh": "qua", "Tắc": "qua", "Cam": "qua", "Xoài": "qua", "Bơ": "qua", "Thịt bơ": "g", "Chanh dây": "qua",
    "Vải ngâm": "qua", "Đào ngâm (lát)": "cai", "Xí muội (cục)": "cai", "Tắc xí muội": "ml",
    "Mứt xoài": "ml", "Mứt vải": "ml", "Mứt đào": "ml", "Mứt dâu": "ml", "Mứt mãng cầu": "ml", "Mứt chanh dây": "ml",
    "Siro chanh": "ml", "Siro vải": "ml", "Siro đào": "ml", "Siro thơm": "ml", "Siro chanh dây": "ml",
    "Cốt xoài chanh dây": "g", "Nước cốt xoài": "ml", "Cốt mãng cầu": "ml", "Cốt đác thơm": "ml", "Đác thơm": "g",
    "Cốt đác dâu": "ml", "Hạt sen": "g", "Đông trùng hạ thảo": "g", "Mật ong": "ml",
    "Trà nhài (đã pha)": "ml", "Trà oolong (đã pha)": "ml", "Trà đào (đã pha)": "ml", "Trà vải (đã pha)": "ml",
    "Trà hibiscus (đã pha)": "ml", "Trà oolong túi lọc": "cai",
    "Gói trà chanh": "goi", "Gói trà dâu": "goi", "Gói trà dưỡng nhan": "goi", "Gói trà đông trùng hạt sen": "goi",
    "Gói trà cam quế mật ong": "goi",
}

# Bán thành phẩm: lượng nguyên liệu gốc cho 1 ml thành phẩm
_FOAM_ML = D(100 + 200 + 90)  # sữa đặc + rich + sữa tươi; muối và bột kem trứng coi như không thêm thể tích
BASES = {
    "cf": ("Cà phê pha: 500 g bột ra 1 lít", {"Cà phê bột": D("0.5")}),
    "nước đường": ("Nước đường: 1 kg đường + 1 lít nước ra 1,6 lít", {"Đường cát": D(1000) / D(1600)}),
    "foam muối": ("Foam muối: 100 ml sữa đặc + 200 ml rich + 90 ml sữa tươi + 5 g muối (khoảng 390 ml)",
                  {"Sữa đặc": 100 / _FOAM_ML, "Kem béo Rich": 200 / _FOAM_ML, "Sữa tươi": 90 / _FOAM_ML,
                   "Muối": 5 / _FOAM_ML}),
    "foam trứng": ("Foam trứng: như foam muối, thay muối bằng 10 g bột kem trứng",
                   {"Sữa đặc": 100 / _FOAM_ML, "Kem béo Rich": 200 / _FOAM_ML, "Sữa tươi": 90 / _FOAM_ML,
                    "Bột kem trứng": 10 / _FOAM_ML}),
}

# Nhóm tùy chọn có nguyên liệu: nhóm -> các tùy chọn (bắt buộc chọn một)
OPTION_GROUPS = {
    "Vị kem": ["Dừa", "Socola"],
    "Loại foam": ["Muối", "Trứng"],
    "Vị hibiscus": ["Đào", "Vải", "Chanh dây"],
}

GROUPS = ["Cà phê", "Cacao và Matcha", "Nước ép", "Sinh tố", "Trà", "Món dừa"]

# Món: (nhóm, tên, công thức như Chủ quán ghi, [(nguyên liệu hoặc bán thành phẩm, lượng)],
#       {nhóm tùy chọn: {tùy chọn: [(…, lượng)]}}, [điểm cần xác nhận])
ITEMS = [
    ("Cà phê", "Cà phê đen", "1 gói đường + 40ml cf",
     [("Đường gói", 1), ("cf", 40)], {}, []),
    ("Cà phê", "Cà phê sữa", "20ml sữa đặc + 40ml cf",
     [("Sữa đặc", 20), ("cf", 40)], {}, []),
    ("Cà phê", "Cà phê Sài Gòn sữa", "60ml cf + 30ml sữa đặc",
     [("cf", 60), ("Sữa đặc", 30)], {}, []),
    ("Cà phê", "Cà phê Sài Gòn đen", "60ml cf + 20ml đường",
     [("cf", 60), ("nước đường", 20)], {}, []),
    ("Cà phê", "Bạc xỉu", "30ml sữa đặc + 20ml sữa tươi + 10ml rich + 40ml cf",
     [("Sữa đặc", 30), ("Sữa tươi", 20), ("Kem béo Rich", 10), ("cf", 40)], {}, []),
    ("Cà phê", "Cà phê kem", "10ml sữa đặc + 40ml cf + 2 viên kem (dừa or socola)",
     [("Sữa đặc", 10), ("cf", 40)],
     {"Vị kem": {"Dừa": [("Kem dừa (viên)", 2)], "Socola": [("Kem socola (viên)", 2)]}}, []),
    ("Cà phê", "Cà phê muối / trứng", "40ml cf + 20ml sữa đặc + 40ml Foam muối/trứng",
     [("cf", 40), ("Sữa đặc", 20)],
     {"Loại foam": {"Muối": [("foam muối", 40)], "Trứng": [("foam trứng", 40)]}}, []),
    ("Cà phê", "Cà phê sương sáo",
     "6-7 viên sương sáo đáy ly + 40ml cốt dừa + 20ml sữa đặc + 20ml đường + 20ml sữa tươi + 40ml cf",
     [("Sương sáo (viên)", D("6.5")), ("Nước cốt dừa", 40), ("Sữa đặc", 20), ("nước đường", 20), ("Sữa tươi", 20),
      ("cf", 40)], {}, ["Sương sáo ghi 6-7 viên, tạm tính 6,5 viên"]),
    ("Cà phê", "Cà phê dừa", "20ml đường + 10ml sữa tươi + 30ml sữa đặc + 10ml rich + 50ml cốt dừa",
     [("nước đường", 20), ("Sữa tươi", 10), ("Sữa đặc", 30), ("Kem béo Rich", 10), ("Nước cốt dừa", 50)], {},
     ["Công thức không ghi lượng cà phê; chưa tính cà phê cho món này"]),

    ("Cacao và Matcha", "Cacao", "5g bột cacao + 40ml sữa đặc + 30ml sữa tươi +10ml rich",
     [("Bột cacao", 5), ("Sữa đặc", 40), ("Sữa tươi", 30), ("Kem béo Rich", 10)], {}, []),
    ("Cacao và Matcha", "Cacao muối / trứng",
     "5g bột cacao + 40ml sữa đặc + 30ml sữa tươi +10ml rich + 20ml foam muối/trứng",
     [("Bột cacao", 5), ("Sữa đặc", 40), ("Sữa tươi", 30), ("Kem béo Rich", 10)],
     {"Loại foam": {"Muối": [("foam muối", 20)], "Trứng": [("foam trứng", 20)]}}, []),
    ("Cacao và Matcha", "Matcha", "30ml sữa đặc + 50ml sữa tươi + 20ml rich + 5g bột matcha",
     [("Sữa đặc", 30), ("Sữa tươi", 50), ("Kem béo Rich", 20), ("Bột matcha", 5)], {}, []),
    ("Cacao và Matcha", "Matcha muối / trứng",
     "30ml sữa đặc + 50ml sữa tươi + 20ml rich + 5g bột matcha + 20ml foam muối/trứng",
     [("Sữa đặc", 30), ("Sữa tươi", 50), ("Kem béo Rich", 20), ("Bột matcha", 5)],
     {"Loại foam": {"Muối": [("foam muối", 20)], "Trứng": [("foam trứng", 20)]}}, []),

    ("Nước ép", "Nước chanh",
     "1,5 trái chanh + 1 tắc + 100ml nước + 40ml đường + 10ml tắc xí muội + 1 cục xí muội",
     [("Chanh", D("1.5")), ("Tắc", 1), ("nước đường", 40), ("Tắc xí muội", 10), ("Xí muội (cục)", 1)], {}, []),
    ("Nước ép", "Nước cam", "3 trái cam + 10ml đường",
     [("Cam", 3), ("nước đường", 10)], {}, []),

    ("Sinh tố", "Sinh tố xoài", "½ xoài + 30ml mứt xoài + 30-40ml sữa đặc tuỳ xoài + 50g đá",
     [("Xoài", D("0.5")), ("Mứt xoài", 30), ("Sữa đặc", 35)], {},
     ["Sữa đặc ghi 30-40 ml tùy xoài, tạm tính 35 ml"]),
    ("Sinh tố", "Sinh tố bơ", "1,5 trái bơ + 10ml sữa đặc + 10ml đường + 10ml sữa tươi + 50g đá",
     [("Bơ", D("1.5")), ("Sữa đặc", 10), ("nước đường", 10), ("Sữa tươi", 10)], {}, []),
    ("Sinh tố", "Sinh tố trái cây", "30ml sữa đặc + Xoài - bơ - thanh long - Đu đủ",
     [("Sữa đặc", 30)], {},
     ["Chưa có lượng xoài, bơ, thanh long, đu đủ cho một ly; định mức mới có sữa đặc"]),

    ("Trà", "Trà chanh", "100ml nước + 1 gói trà chanh + 1 tắc + ½ trái chanh + 30ml đường + 20ml siro chanh",
     [("Gói trà chanh", 1), ("Tắc", 1), ("Chanh", D("0.5")), ("nước đường", 30), ("Siro chanh", 20)], {}, []),
    ("Trà", "Trà sen", "150ml trà olong + 30ml đường + 20ml foam muối + 30g hạt sen",
     [("Trà oolong (đã pha)", 150), ("nước đường", 30), ("foam muối", 20), ("Hạt sen", 30)], {}, []),
    ("Trà", "Trà xoài", "100ml trà nhài + 70ml nước cốt + 1 tắc + 10ml đường + 15g cốt xoài chanh dây",
     [("Trà nhài (đã pha)", 100), ("Nước cốt xoài", 70), ("Tắc", 1), ("nước đường", 10),
      ("Cốt xoài chanh dây", 15)], {}, ["\"70ml nước cốt\" tạm hiểu là nước cốt xoài"]),
    ("Trà", "Trà vải", "100ml trà vải + 20ml đường + 10ml siro vải + 20ml mứt vải + 2 trái vải",
     [("Trà vải (đã pha)", 100), ("nước đường", 20), ("Siro vải", 10), ("Mứt vải", 20), ("Vải ngâm", 2)], {}, []),
    ("Trà", "Trà đào", "100ml trà đào + 1 tắc + 20ml đường + 20ml mứt + 10ml siro + 3 lát đào",
     [("Trà đào (đã pha)", 100), ("Tắc", 1), ("nước đường", 20), ("Mứt đào", 20), ("Siro đào", 10),
      ("Đào ngâm (lát)", 3)], {}, ["\"Mứt\" và \"siro\" tạm hiểu là mứt đào, siro đào"]),
    ("Trà", "Trà dâu chanh dây", "1 gói trà dâu + 100ml nước + 30ml mứt dâu + ½ trái chanh dây + 1 tắc",
     [("Gói trà dâu", 1), ("Mứt dâu", 30), ("Chanh dây", D("0.5")), ("Tắc", 1)], {}, []),
    ("Trà", "Trà mãng cầu", "100ml trà nhài + 50ml cốt + 30ml mứt mãng cầu + 20ml đường + 2 tắc",
     [("Trà nhài (đã pha)", 100), ("Cốt mãng cầu", 50), ("Mứt mãng cầu", 30), ("nước đường", 20), ("Tắc", 2)],
     {}, ["\"50ml cốt\" tạm hiểu là cốt mãng cầu"]),
    ("Trà", "Trà lài đác thơm",
     "120ml trà nhài + 30ml đường + 50ml cốt đác thơm + 20ml siro thơm + 1 tắc + 30g đác thơm",
     [("Trà nhài (đã pha)", 120), ("nước đường", 30), ("Cốt đác thơm", 50), ("Siro thơm", 20), ("Tắc", 1),
      ("Đác thơm", 30)], {}, []),
    ("Trà", "Trà hibiscus", "100ml trà hibicus + 20ml đường + 20ml siro + 20ml mứt (đào / vải / chanh dây)",
     [("Trà hibiscus (đã pha)", 100), ("nước đường", 20)],
     {"Vị hibiscus": {"Đào": [("Siro đào", 20), ("Mứt đào", 20)], "Vải": [("Siro vải", 20), ("Mứt vải", 20)],
                      "Chanh dây": [("Siro chanh dây", 20), ("Mứt chanh dây", 20)]}}, []),
    ("Trà", "Trà đác dâu tằm", "100ml trà nhài + 30ml cốt đác dâu + 20ml đường + 1 Tắc",
     [("Trà nhài (đã pha)", 100), ("Cốt đác dâu", 30), ("nước đường", 20), ("Tắc", 1)], {}, []),
    ("Trà", "Trà tắc xí muội", "120ml trà nhài + 3 tắc + 1 chanh + 60ml đường + 10ml tắc xí muội",
     [("Trà nhài (đã pha)", 120), ("Tắc", 3), ("Chanh", 1), ("nước đường", 60), ("Tắc xí muội", 10)], {}, []),
    ("Trà", "Trà dưỡng nhan", "1 Gói sẵn + 1 trà Oolong túi lọc",
     [("Gói trà dưỡng nhan", 1), ("Trà oolong túi lọc", 1)], {}, []),
    ("Trà", "Trà đông trùng hạt sen", "1 Gói sẵn + 5g đường phèn + 10g đông trùng + 20g hạt sen",
     [("Gói trà đông trùng hạt sen", 1), ("Đường phèn", 5), ("Đông trùng hạ thảo", 10), ("Hạt sen", 20)], {}, []),
    ("Trà", "Trà cam quế mật ong", "1 Gói sẵn + ¼ trái cam + 30ml mật ong",
     [("Gói trà cam quế mật ong", 1), ("Cam", D("0.25")), ("Mật ong", 30)], {}, []),

    ("Món dừa", "Bơ già", "50ml cốt dừa + 20ml sữa tươi + 30ml sữa đặc + 10ml rich + 100g bơ",
     [("Nước cốt dừa", 50), ("Sữa tươi", 20), ("Sữa đặc", 30), ("Kem béo Rich", 10), ("Thịt bơ", 100)], {},
     ["Bơ tính theo gram (100 g) trong khi sinh tố bơ tính theo trái; cần biết 1 trái bơ được khoảng bao nhiêu gram "
      "để gộp thành một nguyên liệu"]),
    ("Món dừa", "Khoai môn sữa dừa", "50ml cốt dừa + 20ml sữa tươi + 30ml sữa đặc + 10ml rich + 5g bột khoai môn",
     [("Nước cốt dừa", 50), ("Sữa tươi", 20), ("Sữa đặc", 30), ("Kem béo Rich", 10), ("Bột khoai môn", 5)], {}, []),
]

GENERAL_NOTES = [
    "Trà nhài, oolong, đào, vải, hibiscus đang tính theo ml trà đã pha. Cần tỷ lệ ủ (bao nhiêu gram trà khô ra bao "
    "nhiêu ml) để quy ra trà khô như cà phê và nước đường.",
    "Không có giá bán và kích cỡ: mỗi món tạo một cỡ \"Chuẩn\" giá 0, trạng thái Đang soạn. Nhập giá rồi mới mở bán.",
    "Nước lọc và đá không tính vào định mức (phần lớn công thức không ghi đá).",
    "Quy cách đóng gói, thời gian giao hàng, tồn an toàn của nguyên liệu chưa có: tạm để quy cách 1, giao 1 ngày, "
    "tồn an toàn 0 (Tạm thời). Cần sửa ở Quản trị › Nguyên vật liệu trước khi dùng đề xuất đặt hàng.",
]


def expand(lines):
    """Quy bán thành phẩm ra nguyên liệu gốc; trả {nguyên liệu: lượng} làm tròn 2 chữ số."""
    out = {}
    for name, qty in lines:
        qty = D(qty)
        parts = BASES[name][1] if name in BASES else {name: D(1)}
        for ing, per in parts.items():
            out[ing] = out.get(ing, D(0)) + qty * per
    return {k: v.quantize(D("0.01")) for k, v in out.items()}
