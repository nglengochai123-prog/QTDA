"""Chặn UPDATE và DELETE trên bảng nhật ký ngay trong cơ sở dữ liệu (BRU-40, NFR-08)."""

from django.db import migrations

TABLE = "audit_auditlog"

SQLITE_UP = [
    f"""CREATE TRIGGER {TABLE}_no_update BEFORE UPDATE ON {TABLE}
        BEGIN SELECT RAISE(ABORT, 'Nhat ky thao tac chi duoc them moi'); END;""",
    f"""CREATE TRIGGER {TABLE}_no_delete BEFORE DELETE ON {TABLE}
        BEGIN SELECT RAISE(ABORT, 'Nhat ky thao tac chi duoc them moi'); END;""",
]
SQLITE_DOWN = [f"DROP TRIGGER IF EXISTS {TABLE}_no_update;", f"DROP TRIGGER IF EXISTS {TABLE}_no_delete;"]

POSTGRES_UP = [
    f"""CREATE OR REPLACE FUNCTION {TABLE}_append_only() RETURNS trigger AS $$
        BEGIN RAISE EXCEPTION 'Nhat ky thao tac chi duoc them moi'; END; $$ LANGUAGE plpgsql;""",
    f"""CREATE TRIGGER {TABLE}_no_change BEFORE UPDATE OR DELETE ON {TABLE}
        FOR EACH ROW EXECUTE FUNCTION {TABLE}_append_only();""",
    f"""CREATE TRIGGER {TABLE}_no_truncate BEFORE TRUNCATE ON {TABLE}
        FOR EACH STATEMENT EXECUTE FUNCTION {TABLE}_append_only();""",
]
POSTGRES_DOWN = [
    f"DROP TRIGGER IF EXISTS {TABLE}_no_change ON {TABLE};",
    f"DROP TRIGGER IF EXISTS {TABLE}_no_truncate ON {TABLE};",
    f"DROP FUNCTION IF EXISTS {TABLE}_append_only();",
]


def _run(statements_by_vendor):
    def run(apps, schema_editor):
        statements = statements_by_vendor.get(schema_editor.connection.vendor, [])
        for sql in statements:
            schema_editor.execute(sql)

    return run


class Migration(migrations.Migration):
    dependencies = [("audit", "0001_initial")]

    operations = [
        migrations.RunPython(
            _run({"sqlite": SQLITE_UP, "postgresql": POSTGRES_UP}),
            _run({"sqlite": SQLITE_DOWN, "postgresql": POSTGRES_DOWN}),
        ),
    ]
