"""Chặn UPDATE và DELETE trên sổ biến động kho ngay trong cơ sở dữ liệu."""

from django.db import migrations

TABLE = "inventory_stockmovement"
MESSAGE = "So bien dong kho chi duoc them moi"

UP = {
    "sqlite": [
        f"CREATE TRIGGER {TABLE}_no_update BEFORE UPDATE ON {TABLE} BEGIN SELECT RAISE(ABORT, '{MESSAGE}'); END;",
        f"CREATE TRIGGER {TABLE}_no_delete BEFORE DELETE ON {TABLE} BEGIN SELECT RAISE(ABORT, '{MESSAGE}'); END;",
    ],
    "postgresql": [
        f"""CREATE OR REPLACE FUNCTION {TABLE}_append_only() RETURNS trigger AS $$
            BEGIN RAISE EXCEPTION '{MESSAGE}'; END; $$ LANGUAGE plpgsql;""",
        f"""CREATE TRIGGER {TABLE}_no_change BEFORE UPDATE OR DELETE ON {TABLE}
            FOR EACH ROW EXECUTE FUNCTION {TABLE}_append_only();""",
    ],
}
DOWN = {
    "sqlite": [f"DROP TRIGGER IF EXISTS {TABLE}_no_update;", f"DROP TRIGGER IF EXISTS {TABLE}_no_delete;"],
    "postgresql": [f"DROP TRIGGER IF EXISTS {TABLE}_no_change ON {TABLE};",
                   f"DROP FUNCTION IF EXISTS {TABLE}_append_only();"],
}


def _run(statements):
    def run(apps, schema_editor):
        for sql in statements.get(schema_editor.connection.vendor, []):
            schema_editor.execute(sql)
    return run


class Migration(migrations.Migration):
    dependencies = [("inventory", "0002_ingredientstock_stockmovement")]
    operations = [migrations.RunPython(_run(UP), _run(DOWN))]
