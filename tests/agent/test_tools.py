# tests/agent/test_tools.py
"""Task 6: Tier-2 工具层测试。

覆盖：
- 窄 tool code 注入校验（_check_code 共享，单测一条即可）
- 4 个窄 tool 的字面量 SQL 形态快照（patch run_safe_sql）
- make_query_database 包装 run_query
"""
import pytest
from unittest.mock import patch

from panwen.agent.tools import narrow, query_database
from panwen.agent.tools.types import ToolResult, Source, TableResult


# ---------- code 注入校验（共享 _check_code，单测一条即可）----------

def test_check_code_rejects_non_digit():
    # 非 6 位数字 → 拒（注入屏障）；用 keyword 传参确保走到 _check_code
    with pytest.raises(ValueError):
        narrow.get_stock_profile(conn=None, code="'; DROP--")


def test_check_code_rejects_short_code():
    with pytest.raises(ValueError):
        narrow.get_performance(conn=None, code="60051")  # 5 位


# ---------- get_stock_profile：字面量 SQL 快照 ----------

def test_get_stock_profile_builds_literal_sql():
    with patch("panwen.agent.tools.narrow.run_safe_sql") as m:
        m.return_value = type("R", (), {"ok": True, "rows": [{"name": "茅台"}],
                                        "sql": "SELECT name FROM stock_basic WHERE code='600519'",
                                        "blocking": [], "rootCause": None})()
        r = narrow.get_stock_profile(conn=None, code="600519")
        sql = m.call_args.args[0]
        assert "stock_basic" in sql and "600519" in sql and "?" not in sql   # 字面量
        assert r.source.kind == "duckdb"
        assert r.source.table == "stock_basic"


# ---------- get_financials：4 表 JOIN 字面量 SQL 快照 ----------

def test_get_financials_sql_shape():
    with patch("panwen.agent.tools.narrow.run_safe_sql") as m:
        m.return_value = type("R", (), {"ok": True, "rows": [], "sql": "",
                                        "blocking": [], "rootCause": None})()
        narrow.get_financials(conn=None, code="600519")
        sql = m.call_args.args[0]
        assert "income_statement" in sql and "balance_sheet" in sql
        assert "USING(code, report_date)" in sql
        assert "600519" in sql and "?" not in sql


def test_get_financials_report_date_filter():
    with patch("panwen.agent.tools.narrow.run_safe_sql") as m:
        m.return_value = type("R", (), {"ok": True, "rows": [], "sql": "",
                                        "blocking": [], "rootCause": None})()
        narrow.get_financials(conn=None, code="600519", report_date="2024-12-31")
        sql = m.call_args.args[0]
        assert "2024-12-31" in sql and "report_date" in sql


# ---------- get_recent_quotes：字面量 SQL 快照 ----------

def test_get_recent_quotes_sql_shape():
    with patch("panwen.agent.tools.narrow.run_safe_sql") as m:
        m.return_value = type("R", (), {"ok": True, "rows": [], "sql": "",
                                        "blocking": [], "rootCause": None})()
        narrow.get_recent_quotes(conn=None, code="000001", days=7)
        sql = m.call_args.args[0]
        assert "daily_quote" in sql
        assert "ORDER BY date DESC" in sql
        assert "LIMIT 7" in sql
        assert "000001" in sql and "?" not in sql


def test_get_recent_quotes_days_coerced_to_int():
    with patch("panwen.agent.tools.narrow.run_safe_sql") as m:
        m.return_value = type("R", (), {"ok": True, "rows": [], "sql": "",
                                        "blocking": [], "rootCause": None})()
        narrow.get_recent_quotes(conn=None, code="000001", days="14")
        sql = m.call_args.args[0]
        assert "LIMIT 14" in sql  # int() 强制


# ---------- get_performance：字面量 SQL 快照 ----------

def test_get_performance_sql_shape():
    with patch("panwen.agent.tools.narrow.run_safe_sql") as m:
        m.return_value = type("R", (), {"ok": True, "rows": [], "sql": "",
                                        "blocking": [], "rootCause": None})()
        narrow.get_performance(conn=None, code="600519")
        sql = m.call_args.args[0]
        assert "performance_express" in sql
        assert "revenue_yoy" in sql
        assert "600519" in sql and "?" not in sql


# ---------- make_query_database：包装 run_query ----------

def test_make_query_database_wraps_run_query():
    from panwen.agent.types import AgentResult, Explanation
    with patch("panwen.agent.tools.query_database.run_query") as m:
        m.return_value = AgentResult(status="answered", sql="SELECT 1", rows=[{"a": 1}],
                                     reply=None, explanation=Explanation([], 0.9, "s"), trace=[])
        qd = query_database.make_query_database(conn=None, backend=None, rag=None, fewshot=None,
                                                config=None)
        r = qd("茅台ROE")
        assert r.ok and r.source.sql == "SELECT 1"
        assert isinstance(r, ToolResult)


def test_make_query_database_failed_status():
    from panwen.agent.types import AgentResult, Explanation
    with patch("panwen.agent.tools.query_database.run_query") as m:
        m.return_value = AgentResult(status="failed", sql=None, rows=None,
                                     reply=None, explanation=Explanation([], 0.0, "err"), trace=[])
        qd = query_database.make_query_database(conn=None, backend=None, rag=None, fewshot=None,
                                                config=None)
        r = qd("无关问题")
        assert r.ok is False


# ---------- types ----------

def test_types_construct():
    s = Source(kind="duckdb", table="t", sql="SELECT 1")
    tr = ToolResult(ok=True, data=[], source=s)
    tb = TableResult(title="x", rows=[], source=s)
    assert tr.source.kind == "duckdb" and tb.title == "x"


# ---------- schemas ----------

def test_tools_schema_shape():
    from panwen.agent.tools.schemas import TOOLS_SCHEMA
    names = [t["name"] for t in TOOLS_SCHEMA]
    assert names == ["get_stock_profile", "get_financials", "get_recent_quotes",
                     "get_performance", "query_database"]
    for t in TOOLS_SCHEMA:
        assert set(t.keys()) >= {"name", "description", "input_schema"}
        assert t["input_schema"]["type"] == "object"
