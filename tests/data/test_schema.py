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
    for table in schema.TABLE_DDL:
        assert table in schema.COLUMN_CLASS, f"{table} 缺 COLUMN_CLASS"
        # 每列都必须标注 text/numeric/date
