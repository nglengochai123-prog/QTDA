# Kiểm thử tự động của đợt QA

## Tệp đã tạo (chưa commit)

| Tệp | Nội dung |
|---|---|
| `apps/core/tests/test_qa_audit.py` | 42 ca nghiệp vụ, mã QA-AUTH, PERM, AUDIT, MD, SALE, BAR, ADJ, REF, INV, SHIFT, LOSS, REP, DASH, SCH, PERF |
| `apps/core/tests/test_qa_concurrency_pg.py` | 3 ca tranh chấp QA-CONC-01..03, tự bỏ qua khi không chạy PostgreSQL |
| `docs/qa/*.md` | 7 tài liệu báo cáo |

Không sửa tệp test nào có sẵn, không sửa mã sản phẩm. Hai ca QA-SALE-F, QA-SALE-G ghi lại hành vi hiện tại để có cơ sở khi Hai quyết định; chúng đang đạt vì chỉ mô tả hiện trạng.

Hai ca đang hỏng có chủ ý vì chứng minh lỗi thật: `test_qa_md_03_price_zero_on_selling_item_via_form` (BUG-01), `test_qa_perf_01_no_n_plus_one_on_hot_screens` (BUG-04); trên PostgreSQL thêm `test_qa_conc_01_order_sent_while_shift_closing` (BUG-02). Không sửa các test này để chúng đạt; chúng sẽ đạt khi lỗi được sửa.

## Cách chạy

SQLite (CSDL test tạm, không chạm `db.sqlite3`):

```powershell
.venv\Scripts\python.exe manage.py test apps.core.tests.test_qa_audit --parallel 1 --noinput
```

PostgreSQL (cần một máy chủ PostgreSQL thử và các biến `DB_ENGINE=postgresql`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`):

```powershell
.venv\Scripts\python.exe manage.py test apps.core.tests.test_qa_audit apps.core.tests.test_concurrency apps.core.tests.test_qa_concurrency_pg --parallel 1 --noinput
```

## Công cụ ngoài bộ test (thư mục tạm, không nằm trong repo)

- `qa_browser.py` (Playwright, Edge không giao diện): mở mọi liên kết nội bộ theo 4 vai trò ở 375x812, đo tràn ngang, lỗi JavaScript, mã HTTP; thử PWA mất mạng và gửi lại đơn.
- `qa_reconcile.py`: tính lại doanh thu, hoàn tiền, doanh thu chốt ca, tổng đơn, sổ kho từ bảng gốc rồi so với báo cáo và Excel.
- `scan_views.py`: quét AST tìm view thiếu kiểm soát đăng nhập hoặc quyền.

Nếu muốn giữ các công cụ này, có thể đưa vào thư mục `scripts/qa/` sau khi Hai duyệt.

## Đề xuất đưa vào CI

1. Chạy bộ test gốc và `test_qa_audit` trên cả SQLite và PostgreSQL.
2. Chạy `test_concurrency` và `test_qa_concurrency_pg` trên PostgreSQL.
3. Giữ `test_qa_perf_01` làm ngưỡng chống N+1 cho các màn nóng.
