# panwen/data/ingest/specs.py
from dataclasses import dataclass, field
from typing import Callable, Any


# Sentinel: when used as a value in Spec.const_cols, instructs run_ingest to
# substitute the current per_code iteration key (e.g. the stock code or board
# name being fetched) as that column's value. Used for endpoints that omit the
# key dimension from their returned rows (e.g. stock_financial_analysis_indicator
# does not return 股票代码).
_KEY = object()


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
    # Task 11: 声明式常量列注入。col -> 字面值, 或 _KEY -> 当前 per_code 迭代键。
    # run_ingest 在 map_columns 之后写入这些列(空 const_cols 为 no-op,向后兼容)。
    const_cols: dict = field(default_factory=dict)
    # Task 11: per_code spec 的迭代键来源域。
    #   "code"           -> 股票代码(默认;由 code_source / stock_basic 提供)
    #   "industry_board" -> 行业板块名(由 industry_board 表提供)
    #   "concept_board"  -> 概念板块名(由 concept_board 表提供)
    # backfill.run_all 据此路由; run_ingest 本身仍只消费 code_source。
    key_domain: str = "code"


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
# 列名校准来源:
#   stock_financial_analysis_indicator -> VERIFIED (Task 11 probe 2026-08-12, symbol=600519):
#                     端点可达,实际列见 FIN_INDICATOR_SPEC 注释(roa=总资产净利润率(%) 等)。
#                     端点不返回 股票代码/市盈率/市净率 -> code 由 const_cols 注入; pe/pb 见 spot_snapshot。
#   stock_yjbb_em                      -> VERIFIED (Task 11 probe 2026-08-12, PERFORMANCE_SPEC)。
#   stock_financial_report_sina        -> VERIFIED (probe 2026-08-12, sh600519 非银行, 三大报表):
#                     INCOME/BALANCE/CASHFLOW rename_map 已按真实列名校准(资产总计/负债合计、
#                     经营/投资/筹资活动产生的现金流量净额 等);端点不返回 股票代码 -> code 由 const_cols 注入。
def _report_arg(stmt):  # stmt: "利润表"/"资产负债表"/"现金流量表"
    return lambda code: {"stock": to_sina_code(code), "symbol": stmt}

INCOME_SPEC = Spec(
    name="income", table="income_statement",
    source=lambda *a, **kw: ak.stock_financial_report_sina(*a, **kw),
    iteration="per_code",
    # 列名校准: probe 2026-08-12 (stock_financial_report_sina 利润表, sh600519 非银行) VERIFIED
    #   实际列含 报告日/营业总收入/营业成本/净利润。端点不返回 股票代码 -> code 由 const_cols 注入。
    rename_map={"报告日": "report_date", "营业总收入": "revenue",
                "营业成本": "oper_cost", "净利润": "net_profit"},
    conflict_cols=["code", "report_date"], arg_builder=_report_arg("利润表"),
    const_cols={"code": _KEY},  # 端点不返回股票代码;从 per_code 迭代键注入
)
BALANCE_SPEC = Spec(
    name="balance", table="balance_sheet",
    source=lambda *a, **kw: ak.stock_financial_report_sina(*a, **kw),
    iteration="per_code",
    # 列名校准: probe 2026-08-12 (资产负债表, sh600519) VERIFIED
    #   实际列为 资产总计/负债合计/所有者权益(或股东权益)合计 (非旧 schema 猜测的 总资产/总负债)。
    #   注意: 同端点另有裸列「所有者权益」实测恒为空(nan) —— 不可用作 total_equity。
    #   正确的总权益 = 归属于母公司股东权益合计 + 少数股东权益 = 所有者权益(或股东权益)合计
    #   (probe 实测 600519: 270,894,035,676.27 + 10,241,850,759.42 = 281,135,886,435.69 ✓)。
    #   列名含半角括号 (0x28/0x29),非全角 —— rename_map 须逐字精确,否则 map_columns 静默丢列。
    #   端点不返回 股票代码 -> code 由 const_cols 注入。
    rename_map={"报告日": "report_date", "资产总计": "total_assets",
                "负债合计": "total_liab", "所有者权益(或股东权益)合计": "total_equity"},
    conflict_cols=["code", "report_date"], arg_builder=_report_arg("资产负债表"),
    const_cols={"code": _KEY},
)
CASHFLOW_SPEC = Spec(
    name="cashflow", table="cashflow_statement",
    source=lambda *a, **kw: ak.stock_financial_report_sina(*a, **kw),
    iteration="per_code",
    # 列名校准: probe 2026-08-12 (现金流量表, sh600519) VERIFIED
    #   实际列为 经营/投资/筹资活动产生的现金流量净额 (非旧猜测 经营/投资/筹资现金流);
    #   端点不返回 股票代码 -> code 由 const_cols 注入。
    rename_map={"报告日": "report_date",
                "经营活动产生的现金流量净额": "op_cf",
                "投资活动产生的现金流量净额": "inv_cf",
                "筹资活动产生的现金流量净额": "fin_cf"},
    conflict_cols=["code", "report_date"], arg_builder=_report_arg("现金流量表"),
    const_cols={"code": _KEY},
)
FIN_INDICATOR_SPEC = Spec(
    name="fin_indicator", table="financial_indicator",
    source=lambda *a, **kw: ak.stock_financial_analysis_indicator(*a, **kw),
    iteration="per_code",
    # 列名校准来源: probe 2026-08-12 (stock_financial_analysis_indicator, symbol=600519)
    #   VERIFIED 实际列含: 日期 / 净资产收益率(%) / 总资产净利润率(%) / 销售毛利率(%) /
    #                       销售净利率(%) / 资产负债率(%) (roa 取 总资产净利润率(%) = 净利/总资产)
    #   端点不返回 股票代码 -> code 由 const_cols 从迭代键注入(_KEY)。
    #   端点不返回 市盈率/市净率 -> 已从 rename_map 移除;pe/pb 由 spot_snapshot 提供
    #                       (spot_snapshot.pe_ttm / spot_snapshot.pb)。勿在此重加。
    rename_map={"日期": "report_date", "净资产收益率(%)": "roe",
                "总资产净利润率(%)": "roa", "销售毛利率(%)": "gross_margin",
                "销售净利率(%)": "net_margin", "资产负债率(%)": "debt_ratio"},
    conflict_cols=["code", "report_date"],
    arg_builder=lambda code: {"symbol": code, "start_year": "2015"},
    const_cols={"code": _KEY},  # 端点不返回股票代码;从 per_code 迭代键注入
)
PERFORMANCE_SPEC = Spec(  # 业绩报表: 按报告期全市场批量
    # 列名校准来源: VERIFIED (Task 11 probe 2026-08-12, stock_yjbb_em date=20231231):
    #   实际列含 股票代码 / 营业总收入-同比增长 / 净利润-同比增长 / 最新公告日期 等。
    #   (Task 9 原写 stock_em_yjbb / 报告日 / 营业收入-同比增长 均不存在 -> 已修正。)
    name="performance", table="performance_express",
    source=lambda *a, **kw: ak.stock_yjbb_em(*a, **kw),
    iteration="per_period",
    rename_map={"股票代码": "code", "最新公告日期": "report_date",
                "营业总收入-同比增长": "revenue_yoy", "净利润-同比增长": "net_profit_yoy"},
    conflict_cols=["code", "report_date"],
    arg_builder=lambda period: {"date": period},
)

def build_finance_specs():
    return [INCOME_SPEC, BALANCE_SPEC, CASHFLOW_SPEC, FIN_INDICATOR_SPEC, PERFORMANCE_SPEC]


# ===== 行业板块 / 概念板块 / 资金面 / 宏观 / 事件域 (Task 10) =====
#
# 常量列注入(const-col injection)—— Task 11 实现于 run_ingest 的 _apply_const,
# 通过 Spec.const_cols 声明式驱动(非 wrapper-client)。下列 spec 需要一列 akshare
# 端点不返回,已在 Task 11 通过 const_cols 声明:
#   - MARGIN_SPEC                -> const_cols={"market": "sse"}
#   - MACRO_CPI_SPEC             -> const_cols={"indicator": "CPI_YOY"}
#   - INDUSTRY_BOARD_DAILY_SPEC  -> const_cols={"board_name": _KEY}  (per_code 迭代键)
#   - FIN_INDICATOR_SPEC (Task 9 承接) -> const_cols={"code": _KEY} (per_code 迭代键)
# 这些 spec 的 conflict_cols 引用了被注入列;const_cols 注入在 upsert 之前完成。
#
# 板块键路由(board-key routing)—— per_code 板块 spec 通过 key_domain 声明其迭代键
# 来源,backfill.run_all._key_source 据此从板块表读取板块名(而非股票代码):
#   - INDUSTRY_CONST_SPEC / INDUSTRY_BOARD_DAILY_SPEC -> key_domain="industry_board"
#   - CONCEPT_CONST_SPEC                              -> key_domain="concept_board"
# build_domain_specs() 已保证 oneshot 板块-LIST spec 排在 per_code 板块 spec 之前。
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
#   stock_lhb_detail_em           -> VERIFIED 2026-08-12 (可达;实际列见 DRAGON_TIGER_SPEC,含 龙虎榜净买额)
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
    key_domain="industry_board",  # Task 11: 迭代键来自 industry_board.name, 非股票代码
)
INDUSTRY_BOARD_DAILY_SPEC = Spec(  # UNVERIFIED (eastmoney proxy-blocked) — re-probe on open network before first backfill
    name="industry_board_daily", table="industry_board_daily",
    source=lambda *a, **kw: ak.stock_board_industry_hist_em(*a, **kw),
    iteration="per_code",
    rename_map={"日期": "date", "收盘": "close", "涨跌幅": "pct_chg", "成交额": "amount"},
    conflict_cols=["board_name", "date"],
    arg_builder=lambda board: {"symbol": board, "period": "daily",
                               "start_date": "20100101", "end_date": "20991231"},
    const_cols={"board_name": _KEY},  # Task 11: 端点不返回板块名;从迭代键注入
    key_domain="industry_board",      # Task 11: 迭代键来自 industry_board.name, 非股票代码
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
    key_domain="concept_board",  # Task 11: 迭代键来自 concept_board.name, 非股票代码
)

# --- 资金面 ---
MARGIN_SPEC = Spec(  # VERIFIED (stock_margin_sse 探测 2026-08-12);market 列由 const_cols 注入
    name="margin", table="margin_daily",
    source=lambda *a, **kw: ak.stock_margin_sse(*a, **kw),
    iteration="oneshot",
    rename_map={"信用交易日期": "date", "融资余额": "rzye",
                "融券余量金额": "rqye", "融资融券余额": "rzrqye"},
    conflict_cols=["date", "market"],
    extra_kwargs={"start_date": "20150101", "end_date": "20991231"},
    const_cols={"market": "sse"},  # Task 11: 静态常量列(SSE 融资融券),run_ingest 注入
)
DRAGON_TIGER_SPEC = Spec(  # VERIFIED (stock_lhb_detail_em probe 2026-08-12, reachable)
    name="dragon_tiger", table="dragon_tiger",
    source=lambda *a, **kw: ak.stock_lhb_detail_em(*a, **kw),
    iteration="oneshot",
    # 列名校准: probe 2026-08-12 VERIFIED 实际列含 代码/上榜日/解读/龙虎榜净买额 (非旧猜测 净买入)。
    rename_map={"代码": "code", "上榜日": "date", "解读": "reason", "龙虎榜净买额": "net_buy"},
    # PK 收敛为 (code, date): 真实 lhb 数据的「解读」(reason) 存在空值,作为 PK 分量会触发
    # NOT NULL 约束整批失败(真实回填 2026-08-12 暴露: ConstraintException reason)。
    # reason 降为普通可空属性保留(DuckDB 非 PK TEXT 列允许 NULL)。(code, date) 是龙虎榜的
    # 稳定自然键;同一股同日因多原因上榜时按 last-write-wins 合并(reason 取末行值)。
    # schema.PRIMARY_KEYS["dragon_tiger"] 已同步改为 ["code", "date"]。
    conflict_cols=["code", "date"],
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
MACRO_CPI_SPEC = Spec(  # VERIFIED (macro_china_cpi 探测 2026-08-12);indicator 列由 const_cols 注入
    name="macro_cpi", table="macro_series",
    source=lambda *a, **kw: ak.macro_china_cpi(*a, **kw),
    iteration="oneshot",
    rename_map={"月份": "date", "全国-同比增长": "value"},
    conflict_cols=["indicator", "date"],
    extra_kwargs={},  # macro_china_cpi 不接受参数;indicator 经 const_cols 注入(非 __indicator magic key)
    const_cols={"indicator": "CPI_YOY"},  # Task 11: 静态常量列,run_ingest 注入
)


def build_domain_specs():
    """行业板块/概念板块/资金面/宏观/事件域 spec 集合(9 张 canonical 表)。"""
    return [INDUSTRY_BOARD_SPEC, INDUSTRY_CONST_SPEC, INDUSTRY_BOARD_DAILY_SPEC,
            CONCEPT_BOARD_SPEC, CONCEPT_CONST_SPEC,
            MARGIN_SPEC, DRAGON_TIGER_SPEC, TOP10_HOLDERS_SPEC, MACRO_CPI_SPEC]
