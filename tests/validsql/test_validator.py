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
