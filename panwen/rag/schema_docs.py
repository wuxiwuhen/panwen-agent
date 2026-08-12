"""schema 文档 —— 每表/列的中文描述，喂 schema_retriever 检索。

由 panwen.data.schema.TABLES 派生表名；列描述人工撰写(关键列)。
未列出的列回退为「列名(英文)」占位描述。
"""
from __future__ import annotations
from dataclasses import dataclass
from panwen.data import schema


@dataclass(frozen=True)
class SchemaDocEntry:
    table: str
    column: str | None       # None = 表级描述
    doc: str                 # 中文描述


# 表级 + 关键列描述(可增量补全)
_TABLE_DOCS = {
    "stock_basic": "股票基础信息：全市场代码(code)与名称(name)。",
    "daily_quote": "日行情(后复权)：code 代码、date 日期、open/high/low/close 开高低收、volume 成交量、turnover 换手率。",
    "income_statement": "利润表：code、report_date 报告日、revenue 营业总收入、oper_cost 营业成本、net_profit 净利润。",
    "balance_sheet": "资产负债表：code、report_date、total_assets 资产总计、total_liabilities 负债合计、total_equity 所有者权益。",
    "cashflow_statement": "现金流量表：code、report_date、oper_cashflow 经营现金流等。",
    "financial_indicator": "财务指标：code、report_date、roe 净资产收益率、roa、gross_margin 毛利率、net_margin 净利率、debt_ratio 资产负债率。",
    "margin_daily": "融资融券(上交所)：date、margin_buy 融资买入、margin_balance 融资余额。",
    "dragon_tiger": "龙虎榜明细：code、date、reason 上榜原因。",
    "macro_series": "宏观序列：CPI 同比等，name 指标名、date、value。",
    "industry_board": "行业板块列表：name 板块名、code 板块代码。",
    "industry_board_daily": "行业板块日线：name、date、close。",
    "concept_board": "概念板块列表：name、code。",
    "performance_express": "业绩快报：code、report_date、revenue、net_profit。",
    "trade_calendar": "交易日历：trade_date。",
}

# 关键列补充(反幻觉：告诉模型 code/report_date 是 text/date 键列)
_COL_DOCS = {
    ("stock_basic", "code"): "6 位股票代码(文本，如 600519)",
    ("income_statement", "report_date"): "财报报告日(日期 YYYY-MM-DD，如 2025-12-31)",
}


def build_schema_docs() -> list[SchemaDocEntry]:
    entries: list[SchemaDocEntry] = []
    for table in schema.TABLES:
        entries.append(SchemaDocEntry(table=table, column=None,
                                      doc=_TABLE_DOCS.get(table, f"表 {table}。")))
        for col in schema.COLUMN_CLASS[table]:
            entries.append(SchemaDocEntry(
                table=table, column=col,
                doc=_COL_DOCS.get((table, col), f"{table}.{col}")))
    return entries
