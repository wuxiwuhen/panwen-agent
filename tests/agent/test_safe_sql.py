# tests/agent/test_safe_sql.py
import pytest
from panwen.agent.safe_sql import run_safe_sql, SqlResult
from panwen.agent.config import AgentConfig
from panwen.data import db

@pytest.fixture
def conn(tmp_path):
    c = db.connect(str(tmp_path / "t.duckdb")); db.init_schema(c)
    c.execute("INSERT INTO financial_indicator VALUES ('600519','2025-12-31',30.0,25.0,90.0,45.0,30.0,NULL,NULL)")
    return c

def test_success(conn):
    r = run_safe_sql("SELECT roe FROM financial_indicator WHERE code='600519'", conn, AgentConfig())
    assert r.ok and r.rows and r.rows[0]["roe"] == 30.0 and r.blocking == []

def test_blocking_unknown_col(conn):
    r = run_safe_sql("SELECT fake_col FROM financial_indicator", conn, AgentConfig())
    assert not r.ok and r.rows is None
    assert any(i.code == "ROOT_UNKNOWN_COL" for i in r.blocking)

def test_write_op_blocked(conn):
    r = run_safe_sql("DELETE FROM financial_indicator", conn, AgentConfig())
    assert not r.ok and any(i.code == "ROOT_WRITE_OP" for i in r.blocking)

def test_unparam_is_advisory_not_blocking(conn):
    # Fix B 字面量: WHERE code='600519' 触发 ROOT_UNPARAM，但它是 advisory，照常执行不阻断
    r = run_safe_sql("SELECT roe FROM financial_indicator WHERE code='600519'", conn, AgentConfig())
    assert r.ok                                          # advisory 不阻断执行
    assert "ROOT_UNPARAM" not in [i.code for i in r.blocking]          # 永不进 blocking
    assert any(i.code == "ROOT_UNPARAM" for i in r.advisory)          # 且确被标为 advisory
