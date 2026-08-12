import duckdb
from panwen.data import schema

def test_all_ddl_execute_in_duckdb():
    conn = duckdb.connect(":memory:")
    for table, ddl in schema.TABLE_DDL.items():
        conn.execute(ddl)  # 不抛异常即通过
    conn.close()

def test_required_mvp_tables_present():
    required = {
        "stock_basic", "trade_calendar", "daily_quote", "spot_snapshot",
        "income_statement", "balance_sheet", "cashflow_statement",
        "financial_indicator", "performance_express",
        "industry_board", "industry_board_const", "industry_board_daily",
        "concept_board", "concept_board_const",
        "margin_daily", "dragon_tiger", "top10_holders", "macro_series",
    }
    assert required.issubset(set(schema.TABLE_DDL.keys()))

def test_every_column_has_class():
    # T1: 原实现遍历 TABLE_DDL(派生自 COLUMN_CLASS 键)再查 COLUMN_CLASS 成员,
    # 属恒真命题(tautology),无法失败。改为对 COLUMN_CLASS 与 PRIMARY_KEYS 真正断言。
    valid_classes = {"text", "numeric", "date"}
    for table, cols in schema.COLUMN_CLASS.items():
        # (a) 每列的 class 必须是三类之一
        for col, cls in cols.items():
            assert cls in valid_classes, f"{table}.{col} 非法列类: {cls}"


def test_primary_keys_are_subset_of_columns():
    # T1(b): 完整性 —— 每张表的 PK 列必须都在 COLUMN_CLASS 中声明(否则 DDL 生成会 KeyError
    # 或写出不存在的 PK)。当前两条均成立,原测试根本未检查。
    for table, pk in schema.PRIMARY_KEYS.items():
        assert table in schema.COLUMN_CLASS, f"{table} 在 PRIMARY_KEYS 但缺 COLUMN_CLASS"
        assert set(pk) <= set(schema.COLUMN_CLASS[table]), \
            f"{table} PK {pk} 未全部在 COLUMN_CLASS 中: {set(schema.COLUMN_CLASS[table])}"
