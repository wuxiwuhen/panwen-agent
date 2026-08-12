import duckdb
from panwen.data import db, schema

def test_init_schema_creates_all_tables(tmp_path):
    conn = db.connect(str(tmp_path / "t.duckdb"))
    db.init_schema(conn)
    created = {r[0] for r in conn.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema='main'").fetchall()}
    assert set(schema.TABLES).issubset(created)
    conn.close()

def test_connect_read_only_flag(tmp_path):
    p = str(tmp_path / "ro.duckdb")
    db.connect(p);
    ro = db.connect(p, read_only=True)  # 已存在才能只读打开
    ro.close()
