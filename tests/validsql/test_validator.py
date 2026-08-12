"""Task 2: ValidSQL 6 检查(检查 6 执行超时在 Task 7)。每检查 pass + fail 夹具。"""
import pytest
from panwen.validsql import validator as V


@pytest.fixture
def sv():
    return V.build_schema_view()


# --- 检查 1: AST 白名单(只读) ---
def test_write_op_rejected(sv):
    issues = V.validate_sql("DELETE FROM income_statement WHERE code='600519'", sv)
    assert any(i.code == "ROOT_WRITE_OP" for i in issues)

def test_select_passes_write(sv):
    # 用 ? 参数绑定，避免触发检查 5(ROOT_UNPARAM)，专注于验证 SELECT 不被检查 1 拒绝
    assert V.validate_sql("SELECT revenue FROM income_statement WHERE code=?", sv) == []


# --- 检查 2: 表/列存在性 ---
def test_unknown_column_rejected(sv):
    issues = V.validate_sql("SELECT fake_col FROM income_statement", sv)
    assert any(i.code == "ROOT_UNKNOWN_COL" for i in issues)

def test_unknown_table_rejected(sv):
    issues = V.validate_sql("SELECT * FROM nonexist_table", sv)
    assert any(i.code == "ROOT_UNKNOWN_TABLE" for i in issues)


# --- 检查 3: 类型约束(text 列禁聚合) ---
def test_text_column_aggregation_rejected(sv):
    # code/name 是 text，对 name 求 AVG 无意义
    issues = V.validate_sql("SELECT AVG(name) FROM stock_basic", sv)
    assert any(i.code == "ROOT_TYPE_AGG" for i in issues)

def test_numeric_column_aggregation_passes(sv):
    assert V.validate_sql("SELECT AVG(roe) FROM financial_indicator", sv) == []


# --- 检查 4: 防笛卡尔(多表须 JOIN ON) ---
def test_cartesian_without_join_rejected(sv):
    sql = ("SELECT i.revenue FROM income_statement i, balance_sheet b "
           "WHERE i.code='600519'")
    issues = V.validate_sql(sql, sv)
    assert any(i.code == "ROOT_CARTESIAN" for i in issues)

def test_join_with_on_passes(sv):
    # 用 ? 参数绑定，避免触发检查 5(ROOT_UNPARAM)，专注于验证 JOIN ON 通过检查 4
    sql = ("SELECT i.revenue FROM income_statement i "
           "JOIN balance_sheet b ON i.code=b.code AND i.report_date=b.report_date "
           "WHERE i.code=?")
    assert V.validate_sql(sql, sv) == []


# --- 检查 5: 参数化(裸字面量应走 ? 绑定) ---
def test_bare_literal_in_predicate_warned(sv):
    # WHERE code='600519' —— 应生成 WHERE code=?
    issues = V.validate_sql("SELECT revenue FROM income_statement WHERE code='600519'", sv)
    assert any(i.code == "ROOT_UNPARAM" for i in issues)

def test_parameterized_predicate_passes(sv):
    assert V.validate_sql("SELECT revenue FROM income_statement WHERE code=?", sv) == []


# --- 检查 4 EXPLAIN 行数估算：千分位逗号回归 ---
# DuckDB 在 explain_value 中以 ``~222,517 rows`` 形式输出(带千分位逗号、
# 小写 rows、~ 前缀)。原正则 ``~(\d+)\s*Rows`` 在逗号处中断 → None → 检查 4
# EXPLAIN 分支成为死代码。这里用 fake conn 锁定 DuckDB 文本格式。

class _FakeResult:
    """DuckDB cursor 的最小替身：fetchall 返回构造时给定的 plan 行。"""
    def __init__(self, rows):
        self._rows = rows
    def fetchall(self):
        return self._rows


class _FakeConn:
    """DuckDB conn 的最小替身：execute(q) 返回 _FakeResult，忽略 q 内容。"""
    def __init__(self, plan_rows):
        self._plan_rows = plan_rows
    def execute(self, q):
        # 真实 DuckDB EXPLAIN 返回 (explain_key, explain_value) 两列。
        return _FakeResult(self._plan_rows)


def test_explain_row_estimate_with_comma_thousands_fires_cartesian(sv):
    # 42,000 行 > 10,000 阈值 → 应告警(ROOT_CARTESIAN)
    plan = [("physical_plan",
             "... Join\n  ~42,000 rows\n  ...")]
    fake_conn = _FakeConn(plan)
    # 不用 ? 占位符，避免触发 DuckDB prepared-parameter(此处为 fake，但保持真实形状)
    sql = ("SELECT i.revenue FROM income_statement i "
           "JOIN balance_sheet b ON i.code=b.code")
    issues = V.validate_sql(sql, sv, conn=fake_conn)
    assert any(i.code == "ROOT_CARTESIAN" for i in issues), \
        f"期望 ROOT_CARTESIAN(42,000 > 10,000)，实际 {[i.code for i in issues]}"


def test_explain_row_estimate_small_passes(sv):
    # 500 行 < 10,000 阈值 → 不告警
    plan = [("physical_plan", "... ~500 rows ...")]
    fake_conn = _FakeConn(plan)
    sql = ("SELECT i.revenue FROM income_statement i "
           "JOIN balance_sheet b ON i.code=b.code")
    issues = V.validate_sql(sql, sv, conn=fake_conn)
    assert not any(i.code == "ROOT_CARTESIAN" for i in issues), \
        f"不应告警(500 < 10,000)，实际 {[i.code for i in issues]}"


def test_extract_row_estimate_handles_comma_format():
    # 直接锁定正则对 DuckDB 真实文本格式(带逗号、小写 rows、多算子)的解析
    plan = [("physical_plan",
             "┌───────────────────┐\n"
             "│ ~222,517 rows     │\n"
             "│ ~2,687 rows       │\n"
             "│ ~2,650 rows       │\n"
             "└───────────────────┘")]
    assert V._extract_row_estimate(plan) == 222517


def test_extract_row_estimate_returns_none_when_no_match():
    plan = [("physical_plan", "no row estimate here")]
    assert V._extract_row_estimate(plan) is None
