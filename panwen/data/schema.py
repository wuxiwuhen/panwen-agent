"""盘问 canonical schema —— 全局单一事实源。列名英文 snake_case。"""
from __future__ import annotations

# text / numeric / date 三类。text 列禁聚合、numeric 允许范围比较与聚合(Plan 2 ValidSQL 用)。
COLUMN_CLASS: dict[str, dict[str, str]] = {
    "stock_basic": {"code": "text", "name": "text", "listing_date": "date",
                    "board": "text", "industry": "text", "is_st": "text", "delist_date": "date"},
    "trade_calendar": {"date": "date", "is_open": "text"},
    "daily_quote": {"code": "text", "date": "date", "open": "numeric", "high": "numeric",
                    "low": "numeric", "close": "numeric", "volume": "numeric", "amount": "numeric",
                    "pct_chg": "numeric", "turnover": "numeric"},
    "spot_snapshot": {"code": "text", "name": "text", "last_close": "numeric", "price": "numeric",
                      "pct_chg": "numeric", "amount": "numeric", "volume": "numeric",
                      "turnover": "numeric", "pe_ttm": "numeric", "pb": "numeric",
                      "total_mv": "numeric", "circ_mv": "numeric", "ts": "date"},
    "income_statement": {"code": "text", "report_date": "date", "revenue": "numeric",
                         "oper_cost": "numeric", "net_profit": "numeric", "npr": "numeric"},
    "balance_sheet": {"code": "text", "report_date": "date", "total_assets": "numeric",
                      "total_liab": "numeric", "total_equity": "numeric"},
    "cashflow_statement": {"code": "text", "report_date": "date", "op_cf": "numeric",
                           "inv_cf": "numeric", "fin_cf": "numeric"},
    "financial_indicator": {"code": "text", "report_date": "date", "roe": "numeric",
                            "roa": "numeric", "gross_margin": "numeric", "net_margin": "numeric",
                            "debt_ratio": "numeric", "pe": "numeric", "pb": "numeric"},
    "performance_express": {"code": "text", "report_date": "date", "revenue_yoy": "numeric",
                            "net_profit_yoy": "numeric"},
    "industry_board": {"name": "text", "code": "text"},
    "industry_board_const": {"board_name": "text", "code": "text"},
    "industry_board_daily": {"board_name": "text", "date": "date", "close": "numeric",
                             "pct_chg": "numeric", "amount": "numeric"},
    "concept_board": {"name": "text", "code": "text"},
    "concept_board_const": {"board_name": "text", "code": "text"},
    "margin_daily": {"date": "date", "market": "text", "rzye": "numeric",
                     "rqye": "numeric", "rzrqye": "numeric"},
    "dragon_tiger": {"code": "text", "date": "date", "reason": "text", "net_buy": "numeric"},
    "top10_holders": {"code": "text", "report_date": "date", "rank": "numeric",
                      "holder_name": "text", "hold_amount": "numeric", "hold_ratio": "numeric",
                      "holder_type": "text"},
    "macro_series": {"indicator": "text", "date": "date", "value": "numeric"},
}

PRIMARY_KEYS: dict[str, list[str]] = {
    "stock_basic": ["code"], "trade_calendar": ["date"],
    "daily_quote": ["code", "date"], "spot_snapshot": ["code"],
    "income_statement": ["code", "report_date"], "balance_sheet": ["code", "report_date"],
    "cashflow_statement": ["code", "report_date"], "financial_indicator": ["code", "report_date"],
    "performance_express": ["code", "report_date"],
    "industry_board": ["name"], "industry_board_const": ["board_name", "code"],
    "industry_board_daily": ["board_name", "date"],
    "concept_board": ["name"], "concept_board_const": ["board_name", "code"],
    "margin_daily": ["date", "market"], "dragon_tiger": ["code", "date", "reason"],
    "top10_holders": ["code", "report_date", "rank", "holder_type"],
    "macro_series": ["indicator", "date"],
}

def _ddl(table: str) -> str:
    cols = COLUMN_CLASS[table]
    pk = PRIMARY_KEYS[table]
    sqltype = {"text": "TEXT", "numeric": "DOUBLE", "date": "DATE"}
    body = ",\n  ".join(f"{c} {sqltype[t]}" for c, t in cols.items())
    return f"CREATE TABLE IF NOT EXISTS {table} (\n  {body},\n  PRIMARY KEY ({', '.join(pk)})\n);"

TABLE_DDL: dict[str, str] = {t: _ddl(t) for t in COLUMN_CLASS}
TABLES: list[str] = list(COLUMN_CLASS.keys())
