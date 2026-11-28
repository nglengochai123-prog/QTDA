# Danh sách ca kiểm thử

Phiên bản: commit f0e5d30. Ngày chạy: 28/11/2026. Tệp test tự động nằm ở `apps/core/tests/` (cột Bằng chứng ghi tên tệp).
Ưu tiên P0 là mất tiền, mất hàng, lộ quyền; P1 sai nghiệp vụ chính; P2 vận hành, hiệu năng; P3 thẩm mỹ, cấu hình.

| Mã | Phân hệ | Chức năng | Ưu tiên | Điều kiện | Vai trò | Dữ liệu | Bước | Mong đợi | Thực tế | Bằng chứng | Trạng thái |
|---|---|---|---|---|---|---|---|---|---|---|---|
| QA-ENV-01 | Môi trường | Xác minh phiên bản | P0 | Thư mục D:\QTDA | QA | git | rev-parse HEAD, so origin/main, status | HEAD = f0e5d30, không có thay đổi code chưa commit | HEAD f0e5d30 = origin/main; chỉ có tệp demo_*.sqlite3 và .impeccable chưa theo dõi | Lệnh git, giai đoạn 1 | PASS |
| QA-ENV-02 | Môi trường | Bộ test gốc | P0 | SQLite test riêng | QA | 583 test sẵn có | manage.py test --parallel 1 | Toàn bộ đạt | 582/583 đạt; 1 test lịch phụ thuộc ngày (sau trưa thứ Năm) hỏng | qa_baseline.txt | FAIL |
| QA-ENV-03 | Môi trường | check, migration, toàn vẹn | P0 | CSDL thật chỉ đọc | QA | db.sqlite3 | check; check --deploy; makemigrations --check; kiem_tra_toan_ven | Không lỗi, không thiếu migration, không sai lệch | check sạch; --deploy 6 cảnh báo (DEBUG local, chưa đặt HSTS); không thiếu migration; không sai lệch | Đầu ra lệnh, giai đoạn 2 | PASS |
| QA-SEC-01 | Bảo mật | Mọi view có kiểm soát | P0 | Mã nguồn | QA | Quét AST mọi view | Liệt kê view thiếu login_required/capability_required | Chỉ trang công khai cố ý được bỏ kiểm soát | Chỉ đăng nhập, sw.js, manifest, offline, healthcheck công khai | scan_views.py | PASS |
| QA-AUTH-01 | Tài khoản | Khóa tạm sau nhiều lần sai | P0 | Ca mở | Phục vụ | LOGIN_MAX_FAILED_ATTEMPTS lần sai | Sai đủ số lần, thử mật khẩu đúng, hết hạn khóa thử lại | Bị khóa, mật khẩu đúng vẫn bị chặn, hết hạn thì vào được | Đúng như mong đợi | test_qa_audit.py | PASS |
| QA-AUTH-02 | Tài khoản | Hết phiên khi không thao tác | P1 | SESSION_COOKIE_AGE 900 s | Phục vụ | Phiên quá hạn | Giả lập hết hạn phiên rồi mở trang | Chuyển về đăng nhập | Đúng | test_qa_audit.py | PASS |
| QA-AUTH-03 | Tài khoản | Chưa đăng nhập | P0 | - | Khách | Mọi mục menu Chủ quán | GET từng URL | 302 về đăng nhập | Đúng với mọi URL | test_qa_audit.py | PASS |
| QA-PERM-01 | Phân quyền | Ma trận vai trò x màn hình | P0 | - | 4 vai trò | Menu Chủ quán | GET từng màn theo từng vai trò | 200 khi và chỉ khi có quyền, còn lại 403 | Đúng với toàn bộ ma trận | test_qa_audit.py | PASS |
| QA-PERM-02 | Phân quyền | POST thẳng vượt quyền | P0 | - | Phục vụ | Thu ngân, tham số, lịch, dữ liệu gốc, kiểm kê, duyệt | POST trực tiếp | 403 (hoặc 405 nếu chỉ nhận GET), dữ liệu không đổi | Đúng | test_qa_audit.py | PASS |
| QA-PERM-03 | Phân quyền | Chặn ở tầng nghiệp vụ | P0 | - | Pha chế, thu ngân | Kiểm kê vượt ngưỡng, xác minh tổn thất | Gọi thẳng hàm nghiệp vụ | PermissionDenied | Đúng | test_qa_audit.py | PASS |
| QA-AUDIT-01 | Nhật ký | Ghi và chống sửa | P0 | - | Phục vụ, pha chế, thu ngân | 1 đơn | Tạo, pha, thu; thử sửa/xóa log qua ORM | Có log kèm người làm; sửa/xóa bị chặn | Đúng | test_qa_audit.py | PASS |
| QA-MD-01 | Dữ liệu gốc | Đổi giá không đổi đơn cũ | P1 | Đã có đơn | Chủ quán | Giá 25.000 → 30.000 | Đổi giá, tạo đơn mới | Đơn cũ giữ giá cũ | Đúng | test_qa_audit.py | PASS |
| QA-MD-02 | Dữ liệu gốc | Đổi định mức | P1 | Đơn đang chờ pha | Chủ quán | Định mức 20 g → 25 g | Đổi định mức, pha đơn cũ | Đơn cũ trừ theo định mức lúc nhận | Đúng | test_qa_audit.py | PASS |
| QA-MD-03 | Dữ liệu gốc | Giá 0 trên món Đang bán | P0 | Món Đang bán | Chủ quán | Cỡ M giá 25.000 | Sửa giá cỡ M thành 0 trên form Món và giá, rồi tạo đơn | Bị chặn như khi mở bán (BRU-20, AC-47) | Form lưu (302), món vẫn bán, tạo được đơn tổng 0 đ | test_qa_audit.py (có đối chứng giá 26.000 lưu được) | FAIL |
| QA-MD-04 | Dữ liệu gốc | Số lẻ định mức | P2 | - | Pha chế | 0,1 g x 30 ly | Pha 30 lần | Tồn giảm đúng 3,0 g | Đúng | test_qa_audit.py | PASS |
| QA-SALE-A | Bán hàng | Đơn có topping, ghi chú | P0 | Ca mở | Phục vụ, pha chế, thu ngân | 2 ly + kem muối, 1 ly ít đá | Gửi, pha, mang ra, thu | Giá, giữ kho, trừ kho, tiền, sổ khớp | Đúng | test_qa_audit.py | PASS |
| QA-SALE-B | Bán hàng | Kịch bản B theo đề bài | P1 | - | - | - | Gộp vào A và E | - | Các bước của B đã nằm trong A (nhiều món) và E (thêm đơn khi đang thu) | - | PASS |
| QA-SALE-C | Bán hàng | Thiếu nguyên liệu | P0 | Tồn 2.000 g | Phục vụ | 3 dòng x 50 ly (3.000 g) | Gửi đơn | Từ chối cả đơn, không giữ dở, tồn không âm | Đúng | test_qa_audit.py | PASS |
| QA-SALE-D | Bán hàng | Gửi lại cùng mã | P0 | - | Phục vụ | Cùng operation key | Gửi 2 lần; gửi cùng mã khác nội dung | 1 đơn, giữ kho 1 lần; khác nội dung bị từ chối | Đúng | test_qa_audit.py | PASS |
| QA-SALE-D2 | Bán hàng | Thu tiền hai lần | P0 | - | Thu ngân | Cùng mã, khác mã | Bấm thu 2 lần | 1 giao dịch | Đúng | test_qa_audit.py | PASS |
| QA-SALE-E | Bán hàng | Bàn đổi khi đang thu | P0 | - | Thu ngân | expected = số cũ | Thêm đơn rồi thu theo số cũ | Chặn, không ghi tiền | Đúng | test_qa_audit.py | PASS |
| QA-SALE-F | Bán hàng | Thu tiền khi chưa xác nhận tiền đầu ca | P2 | Chưa có bút toán đầu ca | Thu ngân | - | Thu tiền mặt | Tài liệu chưa quy định | Thu được; chỉ chặn ở lúc kết ca | test_qa_audit.py | NEEDS SPEC |
| QA-SALE-G | Bán hàng | Nhân viên chưa chấm công tạo đơn | P3 | Không có trong lịch | Phục vụ | - | Tạo đơn | Tài liệu chưa quy định | Tạo được | test_qa_audit.py | NEEDS SPEC |
| QA-BACKUP-SLIP | Bán hàng | Phiếu dự phòng khi mất mạng | P1 | - | Phục vụ, thu ngân | - | Dựa trên test sẵn có của orders.backup | Không tạo trùng, chặn kết ca khi chưa đối chiếu | Test gốc đạt trong baseline; QA không viết thêm | baseline | PASS |
| QA-BAR-01 | Quầy | Bấm Xong vượt số ly, màn cũ | P0 | - | Pha chế | - | Bấm Xong nhiều hơn, bấm lại | Chỉ tính phần còn lại, trừ kho 1 lần | Đúng | test_qa_audit.py | PASS |
| QA-BAR-02 | Quầy | Mang ra | P1 | - | Phục vụ | - | Mang ra trước khi pha; mang ra 2 lần | Chặn; lần 2 không đổi gì | Đúng | test_qa_audit.py | PASS |
| QA-BAR-03 | Quầy | Thu ngân bấm Xong | P2 | Quyết định 21/11 | Thu ngân | - | Bấm Xong | Được, trừ kho 1 lần | Đúng | test_qa_audit.py | PASS |
| QA-ADJ-01 | Điều chỉnh | Tự duyệt | P0 | - | Phục vụ | - | Duyệt yêu cầu của mình | Bị chặn | Đúng | test_qa_audit.py | PASS |
| QA-ADJ-02 | Điều chỉnh | Hủy ly đã pha | P1 | - | Chủ quán | - | Hủy 1 ly đã pha | Tiền giảm, kho không hoàn | Đúng | test_qa_audit.py | PASS |
| QA-ADJ-03 | Điều chỉnh | Hủy ly chưa pha | P1 | - | Chủ quán | - | Hủy 1 ly | Trả phần giữ | Đúng | test_qa_audit.py | PASS |
| QA-ADJ-04 | Điều chỉnh | Duyệt hai lần | P0 | - | Chủ quán | 2 mã khác nhau | Duyệt 2 lần | Trừ tiền 1 lần | Đúng | test_qa_audit.py | PASS |
| QA-REF-01 | Hoàn tiền | Hủy hóa đơn đã thu tiền mặt | P0 | - | Thu ngân, Chủ quán | 25.000 đ | Yêu cầu, duyệt, xác nhận hoàn 2 lần | 1 khoản hoàn, quỹ trừ 1 lần | Đúng | test_qa_audit.py | PASS |
| QA-REF-02 | Hoàn tiền | Hoàn chuyển khoản | P1 | - | Thu ngân | - | Hủy hóa đơn trả chuyển khoản | Hoàn chuyển khoản, két không đổi | Đúng | test_qa_audit.py | PASS |
| QA-INV-01 | Kho | Hao hụt vượt tồn | P0 | - | Pha chế | - | Ghi hao hụt | Vượt tồn bị chặn, hợp lệ trừ đúng | Đúng | test_qa_audit.py | PASS |
| QA-INV-02 | Kho | Kiểm kê lệch | P0 | - | Pha chế, Chủ quán | Lệch nhỏ, lệch lớn | Kiểm kê, xác nhận 2 lần | Lệch nhỏ điều chỉnh ngay; lớn chờ duyệt; 1 lần | Đúng | test_qa_audit.py | PASS |
| QA-INV-03 | Kho | Phiếu nhập thiếu ảnh | P1 | - | Pha chế | - | Lưu phiếu không ảnh | Từ chối, tồn không đổi | Đúng | test_qa_audit.py | PASS |
| QA-INV-04 | Kho | Sổ kho = tồn | P0 | - | - | Bán, hao hụt, kiểm kê | Cộng biến động | Bằng tồn vật lý | Đúng | test_qa_audit.py | PASS |
| QA-SHIFT-01 | Ca, quỹ | Nộp tiền giữa ca | P0 | - | Thu ngân, Chủ quán | - | Nộp cho mình, người không giữ quỹ, quá két; kết ca khi chưa xác nhận | Chặn tất cả; chỉ người nhận xác nhận | Đúng | test_qa_audit.py | PASS |
| QA-SHIFT-02 | Ca, quỹ | Kết ca, báo cáo, đối soát | P0 | - | Thu ngân | Thiếu 20.000 đ | Kết ca khi còn đơn; báo cáo; gửi lại; gửi khác | Đúng 1 chênh lệch, không đối soát 2 lần, ca kết không ghi quỹ | Đúng | test_qa_audit.py | PASS |
| QA-SHIFT-03 | Ca, quỹ | Chi không ảnh chứng từ | P1 | - | Thu ngân | Từ ngưỡng | Ghi chi | Chặn | Đúng | test_qa_audit.py | PASS |
| QA-LOSS-01 | Tổn thất | Thu hồi tổn thất | P1 | Đã xác minh | Chủ quán | - | Thu hồi vượt, gửi lại | Không vượt, không ghi 2 lần | Đúng | test_qa_audit.py | PASS |
| QA-REP-01 | Báo cáo | Doanh thu = thu − hoàn | P0 | - | Chủ quán | - | So các chiều xem | Bằng nhau | Đúng | test_qa_audit.py | PASS |
| QA-REP-02 | Báo cáo | Ranh giới ngày theo giờ VN | P1 | - | - | Thu lúc 23:30 | Xem báo cáo ngày | Thuộc đúng ngày | Đúng | test_qa_audit.py | PASS |
| QA-REP-03 | Báo cáo | Excel | P1 | - | Chủ quán | - | Tải Excel | Mở được, 7 trang, số khớp màn | Đúng (kiểm tra cấu trúc tệp, chưa mở bằng Excel thật) | test_qa_audit.py | PASS |
| QA-REP-04 | Báo cáo | Nhân viên tải Excel | P0 | - | Phục vụ | - | Tải Excel | 403 | Đúng | test_qa_audit.py | PASS |
| QA-DASH-01 | Bảng điều khiển | Doanh thu hôm nay | P1 | - | Chủ quán | - | So với tổng tiền thu | Bằng nhau | Đúng | test_qa_audit.py | PASS |
| QA-SCH-01 | Lịch làm | Đăng ký ca | P2 | - | Nhân viên | - | Đăng ký vị trí khác, quá hạn | Chặn | Đúng | test_qa_audit.py | PASS |
| QA-FC-01 | Dự báo, mua hàng | Kế hoạch mua | P2 | - | Chủ quán | - | Dựa trên test sẵn có của forecast | - | Test gốc đạt trong baseline; độ chính xác dự báo chưa đánh giá trên dữ liệu thật | baseline | NOT TESTED |
| QA-CONC-00 | Đồng thời | 5 tình huống gốc trên PostgreSQL | P0 | PostgreSQL 16 riêng (cổng 5433) | - | 6 luồng | Tranh tồn cuối, cùng mã, Xong nhiều lần, thu cùng bàn, 2 người duyệt | Không âm kho, không trùng tiền | 5/5 đạt | qa_pg.txt | PASS |
| QA-CONC-01 | Đồng thời | Gửi đơn lúc đang kết ca | P1 | PostgreSQL, làm chậm bước tính số kết ca 0,8 s | Phục vụ, thu ngân | - | Hai luồng: kết ca và gửi đơn | Kết ca bị chặn hoặc đơn không vào ca đã kết | Ca kết thành công, đơn 2811-001 chưa thu nằm trong ca đã kết | test_qa_concurrency_pg.py | FAIL |
| QA-CONC-02 | Đồng thời | Hai khoản chi vượt két | P0 | PostgreSQL | Thu ngân | Két 100.000, 4 x chi 60.000 | 4 luồng cùng lúc | Chỉ 1 khoản ghi | Đúng: 1 ghi, 3 bị chặn | test_qa_concurrency_pg.py | PASS |
| QA-CONC-03 | Đồng thời | Kết ca hai lần | P1 | PostgreSQL | Thu ngân, quản lý | - | 4 luồng | Kết 1 lần, 1 dòng nhật ký | Đúng | test_qa_concurrency_pg.py | PASS |
| QA-BR-01 | Sao lưu | Sao lưu và phục hồi SQLite | P0 | Bản sao của db.sqlite3 trong thư mục tạm | QA | 95 bảng, 104.344 dòng | sao_luu, phuc_hoi --vao tệp riêng, kiem_tra_toan_ven, so đếm dòng | Khớp từng bảng; CSDL nguồn không đổi | Khớp 95/95 bảng; migrate --check và toàn vẹn đạt; hash db.sqlite3 trước và sau như nhau | Giai đoạn sao lưu | PASS |
| QA-BR-02 | Sao lưu | Chống phục hồi đè | P0 | - | QA | - | Phục hồi vào tệp đã có; vào chính CSDL đang chạy | Từ chối | Từ chối cả hai | Đầu ra lệnh | PASS |
| QA-BR-03 | Sao lưu | Sao lưu và phục hồi PostgreSQL (pg_dump) | P1 | - | - | - | - | - | Chưa chạy: CSDL PostgreSQL thử chỉ có dữ liệu test | - | NOT TESTED |
| QA-PWA-01 | PWA | Mất mạng khi chuyển trang | P1 | Service worker đã cài | Phục vụ | - | Tắt mạng, mở /kho/ | Hiện trang Mất kết nối | Đúng | qa_browser.json, pwa_offline_nav.png | PASS |
| QA-PWA-02 | PWA | Gửi đơn khi mất mạng rồi gửi lại | P0 | - | Phục vụ | 1 ly | Tắt mạng, gửi, tải lại trang, bật mạng, gửi lại | Giữ phiếu và mã; gửi lại tạo đúng 1 đơn | Giữ mã 03B55DA5 sau tải lại; tạo đúng 1 đơn, 1 bản ghi mã | qa_browser.json | PASS |
| QA-UI-01 | Giao diện | 375px không tràn ngang | P2 | Bản sao dữ liệu | 4 vai trò | 129 trang | Mở mọi liên kết nội bộ ở 375x812 | Không tràn ngang, không lỗi JS, không lỗi HTTP | 127/129 đạt; tràn ngang ở /kho/phieu-nhap/ (thanh tổng phiếu) và /lich/ (dải bước) | qa_browser.json | FAIL |
| QA-PERF-01 | Hiệu năng | Truy vấn theo số bàn | P2 | - | - | 1 và 9 bàn chờ thu | Đếm truy vấn | Không tăng theo số bàn | Thu ngân 23 → 55 (khoảng 4 truy vấn mỗi bàn); quầy và tổng quan không tăng | test_qa_audit.py | FAIL |
| QA-PERF-02 | Hiệu năng | Báo cáo trên dữ liệu 4.100 đơn | P2 | Bản sao dữ liệu mô phỏng | Chủ quán | 3.277 thanh toán | Đo thời gian | Mở được trong vài giây | Doanh thu 7,6–8,4 s (54 truy vấn, chậm ở receipts._payment_entries); Bảng điều khiển lần đầu 1.082 truy vấn, 14–16 s; lần sau 88 truy vấn, 1,3 s | Đo bằng Client và cProfile | FAIL |
| QA-DAY-01 | Đối soát | Đối soát độc lập theo ngày | P0 | Bản sao dữ liệu mô phỏng | QA | 5 ngày có và không có hoàn tiền, cả tháng 11 | Tính lại từ bảng gốc, so báo cáo, 7 chiều xem, Excel, doanh thu chốt ca | Khớp tuyệt đối | Khớp mọi ngày, mọi chiều, mọi ca; tháng 11: thu 86.909.000, hoàn 75.000, thuần 86.834.000 | qa_reconcile.py | PASS |
| QA-DAY-02 | Đối soát | Toàn bộ đơn và kho | P0 | Bản sao dữ liệu | QA | 4.105 đơn | Tính lại tổng từng đơn, cộng sổ kho | 0 lệch | 0 đơn lệch, 0 nguyên liệu lệch, 0 tồn âm, 0 đơn đã thu thiếu thanh toán | qa_reconcile.py | PASS |

Tổng: PASS 52, FAIL 6, NEEDS SPEC 2, NOT TESTED 2 trên 62 ca.
