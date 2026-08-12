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


from panwen.data.ingest.mapping import to_sina_code

# ===== 财务域 =====
# 列名校准来源: stock_financial_analysis_indicator / stock_em_yjbb / stock_financial_report_sina
# 均在 Task 4 探测中被 ProxyError 阻断(eastmoney 上游),所以下列 rename_map 为
# 文档 schema 猜测,NOT VERIFIED。首次真实回填前需在开放网络用 probe_akshare.py 重探,
# 否则 map_columns 会静默丢列。仅 FIN_INDICATOR_SPEC 的中文 key 与本任务 mock 测试 df
# 对齐以保证测试通过 —— 这并不代表真实 akshare 列名。
def _report_arg(stmt):  # stmt: "利润表"/"资产负债表"/"现金流量表"
    return lambda code: {"stock": to_sina_code(code), "symbol": stmt}

INCOME_SPEC = Spec(
    name="income", table="income_statement",
    source=lambda *a, **kw: ak.stock_financial_report_sina(*a, **kw),
    iteration="per_code",
    rename_map={"报告日": "report_date", "股票代码": "code", "营业总收入": "revenue",
                "营业成本": "oper_cost", "净利润": "net_profit"},
    conflict_cols=["code", "report_date"], arg_builder=_report_arg("利润表"),
)
BALANCE_SPEC = Spec(
    name="balance", table="balance_sheet",
    source=lambda *a, **kw: ak.stock_financial_report_sina(*a, **kw),
    iteration="per_code",
    rename_map={"报告日": "report_date", "股票代码": "code", "总资产": "total_assets",
                "总负债": "total_liab", "所有者权益": "total_equity"},
    conflict_cols=["code", "report_date"], arg_builder=_report_arg("资产负债表"),
)
CASHFLOW_SPEC = Spec(
    name="cashflow", table="cashflow_statement",
    source=lambda *a, **kw: ak.stock_financial_report_sina(*a, **kw),
    iteration="per_code",
    rename_map={"报告日": "report_date", "股票代码": "code",
                "经营现金流": "op_cf", "投资现金流": "inv_cf", "筹资现金流": "fin_cf"},
    conflict_cols=["code", "report_date"], arg_builder=_report_arg("现金流量表"),
)
FIN_INDICATOR_SPEC = Spec(
    name="fin_indicator", table="financial_indicator",
    source=lambda *a, **kw: ak.stock_financial_analysis_indicator(*a, **kw),
    iteration="per_code",
    rename_map={"日期": "report_date", "股票代码": "code", "净资产收益率(%)": "roe",
                "总资产报酬率(%)": "roa", "销售毛利率(%)": "gross_margin",
                "销售净利率(%)": "net_margin", "资产负债率(%)": "debt_ratio",
                "市盈率": "pe", "市净率": "pb"},
    conflict_cols=["code", "report_date"],
    arg_builder=lambda code: {"symbol": code, "start_year": "2015"},
)
PERFORMANCE_SPEC = Spec(  # 业绩快报: 按报告期全市场批量
    name="performance", table="performance_express",
    source=lambda *a, **kw: ak.stock_em_yjbb(*a, **kw),
    iteration="per_period",
    rename_map={"股票代码": "code", "报告日": "report_date",
                "营业收入-同比增长": "revenue_yoy", "净利润-同比增长": "net_profit_yoy"},
    conflict_cols=["code", "report_date"],
    arg_builder=lambda period: {"date": period},
)

def build_finance_specs():
    return [INCOME_SPEC, BALANCE_SPEC, CASHFLOW_SPEC, FIN_INDICATOR_SPEC, PERFORMANCE_SPEC]


# ===== 行业板块 / 概念板块 / 资金面 / 宏观 / 事件域 (Task 10) =====
#
# 常量列注入(const-col injection)—— Task 11 实现,本任务仅声明 spec。
# 下列 spec 需要一列 akshare 端点不返回,须在 Task 11 的 backfill 编排里于
# map_columns 之后注入(给 run_ingest 加 post_map 钩子或特例两行补列):
#   - MARGIN_SPEC                -> inject market="sse"
#   - MACRO_CPI_SPEC             -> inject indicator="CPI_YOY"
#                                   (extra_kwargs["__indicator"] 是 INTENTIONAL magic key:
#                                    Task 11 在 fetch 前剥离 __ 前缀键、用于注入。
#                                    勿在 Task 10 中"修正"或移除。)
#   - INDUSTRY_BOARD_DAILY_SPEC  -> inject board_name=<iteration key>
#   - FIN_INDICATOR_SPEC (Task 9 承接) -> inject code=<iteration key>
# 这些 spec 的 conflict_cols 引用了被注入列;在 Task 11 注入前不要真实回填这些表。
#
# 列名校准来源(probe 2026-08-12):
#   stock_margin_sse (SSE)        -> VERIFIED  ['信用交易日期','融资余额','融资买入额',
#                                    '融券余量','融券余量金额','融券卖出量','融资融券余额']
#   macro_china_cpi (国家统计局)   -> VERIFIED  ['月份','全国-当月','全国-同比增长',
#                                    '全国-环比增长','全国-累计','城市-当月', ...]
#   stock_board_industry_name_em  -> UNVERIFIED (eastmoney push2 ProxyError)
#   stock_board_industry_cons_em  -> UNVERIFIED (eastmoney proxy-blocked)
#   stock_board_industry_hist_em  -> UNVERIFIED (eastmoney proxy-blocked)
#   stock_board_concept_name_em   -> UNVERIFIED (eastmoney push2 ProxyError)
#   stock_board_concept_cons_em   -> UNVERIFIED (eastmoney proxy-blocked)
#   stock_lhb_detail_em           -> UNVERIFIED (eastmoney proxy-blocked)
#   stock_gdfx_holding_detail_em  -> UNVERIFIED (eastmoney proxy-blocked)
# 受阻端点的 rename_map 沿用文档 schema 猜测,首次真实回填前需在开放网络重探测,
# 否则 map_columns 会静默丢列。

# --- 行业板块 ---
INDUSTRY_BOARD_SPEC = Spec(  # UNVERIFIED (eastmoney proxy-blocked) — re-probe on open network before first backfill
    name="industry_board", table="industry_board",
    source=lambda *a, **kw: ak.stock_board_industry_name_em(*a, **kw),
    iteration="oneshot",
    rename_map={"板块名称": "name", "板块代码": "code"},
    conflict_cols=["name"],
)
INDUSTRY_CONST_SPEC = Spec(  # UNVERIFIED (eastmoney proxy-blocked) — re-probe on open network before first backfill
    name="industry_const", table="industry_board_const",
    source=lambda *a, **kw: ak.stock_board_industry_cons_em(*a, **kw),
    iteration="per_code",
    rename_map={"板块名称": "board_name", "代码": "code"},
    conflict_cols=["board_name", "code"],
    arg_builder=lambda board: {"symbol": board},
)
INDUSTRY_BOARD_DAILY_SPEC = Spec(  # UNVERIFIED (eastmoney proxy-blocked) — re-probe on open network before first backfill
    name="industry_board_daily", table="industry_board_daily",
    source=lambda *a, **kw: ak.stock_board_industry_hist_em(*a, **kw),
    iteration="per_code",
    rename_map={"日期": "date", "收盘": "close", "涨跌幅": "pct_chg", "成交额": "amount"},
    conflict_cols=["board_name", "date"],
    arg_builder=lambda board: {"symbol": board, "period": "daily",
                               "start_date": "20100101", "end_date": "20991231"},
)

# --- 概念板块 ---
CONCEPT_BOARD_SPEC = Spec(  # UNVERIFIED (eastmoney proxy-blocked) — re-probe on open network before first backfill
    name="concept_board", table="concept_board",
    source=lambda *a, **kw: ak.stock_board_concept_name_em(*a, **kw),
    iteration="oneshot",
    rename_map={"板块名称": "name", "板块代码": "code"},
    conflict_cols=["name"],
)
CONCEPT_CONST_SPEC = Spec(  # UNVERIFIED (eastmoney proxy-blocked) — re-probe on open network before first backfill
    name="concept_const", table="concept_board_const",
    source=lambda *a, **kw: ak.stock_board_concept_cons_em(*a, **kw),
    iteration="per_code",
    rename_map={"板块名称": "board_name", "代码": "code"},
    conflict_cols=["board_name", "code"],
    arg_builder=lambda b: {"symbol": b},
)

# --- 资金面 ---
MARGIN_SPEC = Spec(  # VERIFIED (stock_margin_sse 探测 2026-08-12);market 列由 Task 11 注入
    name="margin", table="margin_daily",
    source=lambda *a, **kw: ak.stock_margin_sse(*a, **kw),
    iteration="oneshot",
    rename_map={"信用交易日期": "date", "融资余额": "rzye",
                "融券余量金额": "rqye", "融资融券余额": "rzrqye"},
    conflict_cols=["date", "market"],
    extra_kwargs={"start_date": "20150101", "end_date": "20991231"},
)
DRAGON_TIGER_SPEC = Spec(  # UNVERIFIED (eastmoney proxy-blocked) — re-probe on open network before first backfill
    name="dragon_tiger", table="dragon_tiger",
    source=lambda *a, **kw: ak.stock_lhb_detail_em(*a, **kw),
    iteration="oneshot",
    rename_map={"代码": "code", "上榜日": "date", "解读": "reason", "净买入": "net_buy"},
    conflict_cols=["code", "date", "reason"],
    extra_kwargs={"start_date": "20150101", "end_date": "20991231"},
)

# --- 公司事件 (🟡批次) ---
TOP10_HOLDERS_SPEC = Spec(  # UNVERIFIED (eastmoney proxy-blocked) — re-probe on open network before first backfill
    name="top10_holders", table="top10_holders",
    source=lambda *a, **kw: ak.stock_gdfx_holding_detail_em(*a, **kw),
    iteration="per_code",
    rename_map={"股票代码": "code", "报告期": "report_date", "名次": "rank",
                "股东名称": "holder_name", "持股数量": "hold_amount",
                "持股比例": "hold_ratio", "股东性质": "holder_type"},
    conflict_cols=["code", "report_date", "rank", "holder_type"],
    arg_builder=lambda code: {"symbol": code},
)

# --- 宏观 ---
MACRO_CPI_SPEC = Spec(  # VERIFIED (macro_china_cpi 探测 2026-08-12);indicator 列由 Task 11 注入
    name="macro_cpi", table="macro_series",
    source=lambda *a, **kw: ak.macro_china_cpi(*a, **kw),
    iteration="oneshot",
    rename_map={"月份": "date", "全国-同比增长": "value"},
    conflict_cols=["indicator", "date"],
    extra_kwargs={"__indicator": "CPI_YOY"},  # INTENTIONAL magic key: Task 11 fetch 前剥离 __ 前缀、用于注入 indicator 列。勿移除。
)


def build_domain_specs():
    """行业板块/概念板块/资金面/宏观/事件域 spec 集合(9 张 canonical 表)。"""
    return [INDUSTRY_BOARD_SPEC, INDUSTRY_CONST_SPEC, INDUSTRY_BOARD_DAILY_SPEC,
            CONCEPT_BOARD_SPEC, CONCEPT_CONST_SPEC,
            MARGIN_SPEC, DRAGON_TIGER_SPEC, TOP10_HOLDERS_SPEC, MACRO_CPI_SPEC]
