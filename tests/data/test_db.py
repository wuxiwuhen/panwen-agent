import duckdb
import pytest
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

def test_read_only_connection_rejects_writes(tmp_path):
    # T2: 只读连接不仅要能成功打开,更要真正拒绝写。Plan-2 安全模型依赖此强制。
    # 旧测试仅断言"打开成功",无法证明 ENFORCEMENT。此处验证 INSERT 与 CREATE 均抛
    # duckdb.Error,证明写确被拒。
    p = str(tmp_path / "ro.duckdb")
    rw = db.connect(p)
    db.init_schema(rw)
    rw.close()
    ro = db.connect(p, read_only=True)
    with pytest.raises(duckdb.Error):
        ro.execute("INSERT INTO stock_basic (code) VALUES ('000001')")
    with pytest.raises(duckdb.Error):
        ro.execute("CREATE TABLE evil (x INTEGER)")
    ro.close()
