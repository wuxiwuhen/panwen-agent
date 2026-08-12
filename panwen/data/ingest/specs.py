# panwen/data/ingest/specs.py
from dataclasses import dataclass, field
from typing import Callable, Any


@dataclass
class Spec:
    """声明式 ingest 配置 —— 每张 canonical 表一份。"""
    name: str                       # checkpoint domain 名
    table: str                      # 目标 canonical 表
    source: Callable[..., Any]      # akshare 函数(如 ak.stock_zh_a_hist)
    iteration: str                  # "oneshot" | "per_code" | "per_period" | "per_date"
    rename_map: dict[str, str]      # akshare中文列 → canonical列
    conflict_cols: list[str]
    # 按迭代策略构造 source 的 kwargs:
    arg_builder: Callable[[str], dict] = field(default=lambda k: {})
    # 可选: per_code 的代码来源(默认全部 A 股)
    extra_kwargs: dict = field(default_factory=dict)


import akshare as ak

# ===== 基础/行情域 =====
# source 用 lambda 包裹,使其在调用时经 akshare 模块属性解析 —— 这样测试里
# mocker.patch("akshare.<func>") 才能生效(直接 source=ak.<func> 会在 import 时
# 固化函数对象、绕过 mock)。对真实回填透明:无 mock 时 lambda 直接转发到原函数。
#
# 列名校准来源(inline probe 2026-08-12):
#   stock_info_a_code_name   -> VERIFIED  ['code', 'name']
#   tool_trade_date_hist_sina -> VERIFIED  ['trade_date']
#   stock_zh_a_hist(hfq)     -> VERIFIED (Task 4) 日期/股票代码/开盘/收盘/最高/最低/成交量/成交额/振幅/涨跌幅/涨跌额/换手率
#   stock_zh_a_spot_em       -> UNVERIFIED (eastmoney push2 ProxyError); rename_map 沿用文档schema猜测,
#                               首次真实回填前需在开放网络重探测,否则 map_columns 会静默丢列。
STOCK_BASIC_SPEC = Spec(
    name="stock_basic", table="stock_basic",
    source=lambda *a, **kw: ak.stock_info_a_code_name(*a, **kw),
    iteration="oneshot",
    rename_map={"code": "code", "name": "name"},   # 探测确认: 列名就是 code/name,直通
    conflict_cols=["code"],
)

TRADE_CAL_SPEC = Spec(
    name="trade_calendar", table="trade_calendar",
    source=lambda *a, **kw: ak.tool_trade_date_hist_sina(*a, **kw),
    iteration="oneshot",
    rename_map={"trade_date": "date"},   # 探测确认: 实际列名 trade_date
    conflict_cols=["date"],
)

DAILY_QUOTE_SPEC = Spec(
    name="daily_quote", table="daily_quote",
    source=lambda *a, **kw: ak.stock_zh_a_hist(*a, **kw),
    iteration="per_code",
    rename_map={"日期": "date", "股票代码": "code", "开盘": "open", "收盘": "close",
                "最高": "high", "最低": "low", "成交量": "volume", "成交额": "amount",
                "涨跌幅": "pct_chg", "换手率": "turnover"},
    conflict_cols=["code", "date"],
    arg_builder=lambda code: {"symbol": code, "period": "daily",
                              "start_date": "20100101", "end_date": "20991231",
                              "adjust": "hfq"},
)

SPOT_SPEC = Spec(
    name="spot_snapshot", table="spot_snapshot",
    source=lambda *a, **kw: ak.stock_zh_a_spot_em(*a, **kw),
    iteration="oneshot",
    rename_map={"代码": "code", "名称": "name", "昨收": "last_close", "最新价": "price",
                "涨跌幅": "pct_chg", "成交额": "amount", "成交量": "volume",
                "换手率": "turnover", "市盈率-动态": "pe_ttm", "市净率": "pb",
                "总市值": "total_mv", "流通市值": "circ_mv"},
    conflict_cols=["code"],
)

def build_quote_specs():
    return [STOCK_BASIC_SPEC, TRADE_CAL_SPEC, DAILY_QUOTE_SPEC, SPOT_SPEC]
