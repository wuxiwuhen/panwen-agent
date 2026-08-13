# panwen/agent/tools/narrow.py
"""4 个窄 tool —— 固定形状的字面量 SQL recipe（零幻觉）。

每个 tool：① _check_code 守卫（6 位数字注入屏障）
        ② 拼字面量 SQL（code 已校验，安全插值）
        ③ _run 调 run_safe_sql 执行 → ToolResult(data, source=Source(...))

列名取自 panwen/data/schema.py（已逐项核对，含 op_cf）。
"""
from __future__ import annotations
import re

from panwen.agent.safe_sql import run_safe_sql
from panwen.agent.config import AgentConfig
from panwen.agent.tools.types import ToolResult, Source


def _check_code(code: str) -> str:
    """注入屏障：仅放行恰好 6 位数字。其余 → ValueError。"""
    if not re.fullmatch(r"\d{6}", code):
        raise ValueError(f"非法股票代码: {code!r}（须 6 位数字）")
    return code


def _run(conn, sql: str, table: str, as_of: str | None = None) -> ToolResult:
    sr = run_safe_sql(sql, conn, AgentConfig())
    return ToolResult(
        ok=sr.ok,
        data=sr.rows if sr.ok else (sr.rootCause or "查询失败"),
        source=Source(kind="duckdb", table=table, sql=sql, as_of=as_of),
        note=None if sr.ok else "; ".join(i.code for i in sr.blocking),
    )


def get_stock_profile(conn, code: str) -> ToolResult:
    """股票基本信息：名称/板块/行业/ST/上市日。"""
    code = _check_code(code)
    sql = (f"SELECT name, board, industry, is_st, listing_date "
           f"FROM stock_basic WHERE code = '{code}'")
    return _run(conn, sql, "stock_basic")


def get_financials(conn, code: str, report_date: str | None = None) -> ToolResult:
    """最新财务：营收/净利/资产/负债/权益/经营现金流/ROE/毛利率/负债率。

    4 表 JOIN USING(code, report_date)（ValidSQL 反笛卡尔检查接受 USING）。
    字面量 code 触发 ROOT_UNPARAM advisory（非阻断），符合预期。
    """
    code = _check_code(code)
    filt = f"AND i.report_date = '{report_date}'" if report_date else ""
    sql = (
        f"SELECT i.report_date, i.revenue, i.net_profit, "
        f"b.total_assets, b.total_liab, b.total_equity, "
        f"c.op_cf, f.roe, f.gross_margin, f.debt_ratio "
        f"FROM income_statement i "
        f"JOIN balance_sheet b USING(code, report_date) "
        f"JOIN cashflow_statement c USING(code, report_date) "
        f"JOIN financial_indicator f USING(code, report_date) "
        f"WHERE i.code = '{code}' {filt} "
        f"ORDER BY i.report_date DESC LIMIT 1"
    )
    return _run(conn, sql, "income_statement+balance+cashflow+indicator")


def get_recent_quotes(conn, code: str, days: int = 30) -> ToolResult:
    """近 N 日行情（日K）：开/高/低/收/量。days 经 int() 强制。"""
    code = _check_code(code)
    n = int(days)
    sql = (f"SELECT date, open, high, low, close, volume "
           f"FROM daily_quote WHERE code = '{code}' "
           f"ORDER BY date DESC LIMIT {n}")
    return _run(conn, sql, "daily_quote")


def get_performance(conn, code: str) -> ToolResult:
    """业绩快报：营收/净利同比（全部报告期，最新在前）。"""
    code = _check_code(code)
    sql = (f"SELECT report_date, revenue_yoy, net_profit_yoy "
           f"FROM performance_express WHERE code = '{code}' "
           f"ORDER BY report_date DESC")
    return _run(conn, sql, "performance_express")
