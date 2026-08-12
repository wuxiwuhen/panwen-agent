"""Task 11: full-backfill orchestrator + 常量列注入 + 板块键路由 端到端测试。"""
import pandas as pd
from pathlib import Path
from panwen.data import db
from panwen.data.ingest import backfill, runner, specs, client as clientmod

# cwd-独立: 测试文件 tests/data/test_backfill.py -> parents[2] = 仓库根
ROOT = Path(__file__).resolve().parents[2]
SEED = ROOT / "panwen" / "seeds" / "dev_codes.txt"


def test_run_all_on_seed(tmp_path, mocker):
    """dev 种子端到端: 全量 run_all 在 mock 数据源下应写入 stock_basic / daily_quote 各 1 行。"""
    conn = db.connect(str(tmp_path / "t.duckdb"))
    db.init_schema(conn)
    mocker.patch("akshare.stock_info_a_code_name",
                 return_value=pd.DataFrame({"code": ["000001"], "name": ["平安"]}))
    mocker.patch("akshare.stock_zh_a_hist", return_value=pd.DataFrame({
        "日期": ["2024-01-02"], "股票代码": ["000001"], "开盘": [1.0], "收盘": [1.0],
        "最高": [1.0], "最低": [1.0], "成交量": [1], "成交额": [1.0],
        "涨跌幅": [1.0], "换手率": [1.0]}))
    mocker.patch("akshare.stock_zh_a_spot_em",
                 return_value=pd.DataFrame({"代码": ["000001"], "名称": ["平安"], "最新价": [1.0]}))
    mocker.patch("akshare.tool_trade_date_hist_sina",
                 return_value=pd.DataFrame({"trade_date": ["2024-01-02"]}))
    # 财务/板块/宏观等 mock 为空 DF(空 DF 不写)
    for fn in ["stock_financial_report_sina", "stock_financial_analysis_indicator",
               "stock_yjbb_em", "stock_board_industry_name_em", "stock_board_industry_cons_em",
               "stock_board_industry_hist_em", "stock_board_concept_name_em",
               "stock_board_concept_cons_em", "stock_margin_sse", "stock_lhb_detail_em",
               "stock_gdfx_holding_detail_em", "macro_china_cpi"]:
        mocker.patch(f"akshare.{fn}", return_value=pd.DataFrame())
    backfill.run_all(conn, seed_path=str(SEED), periods=["20231231"], client=clientmod)
    assert conn.execute("SELECT count(*) FROM stock_basic").fetchone()[0] == 1
    assert conn.execute("SELECT count(*) FROM daily_quote").fetchone()[0] == 1


def test_fin_indicator_code_injected_from_key(tmp_path, mocker):
    """Gate #1 (CRITICAL): 端点不返回股票代码;code 必须由 per_code 迭代键注入。

    若 const_cols 未生效,code 列缺失 -> 写入 NULL -> 与第二次同键 upsert 行折叠/ PK 异常。
    """
    conn = db.connect(str(tmp_path / "t.duckdb"))
    db.init_schema(conn)
    # 注意: 返回 df 刻意不含 "股票代码" 列(模拟真实端点行为)
    mocker.patch("akshare.stock_financial_analysis_indicator", return_value=pd.DataFrame({
        "日期": ["2023-12-31"], "净资产收益率(%)": [12.0], "资产负债率(%)": [60.0]}))
    runner.run_ingest(conn, specs.FIN_INDICATOR_SPEC, client=clientmod, code_source=["000001"])
    row = conn.execute("SELECT code, roe FROM financial_indicator").fetchone()
    assert row[0] == "000001"   # 从迭代键注入, 端点输出中不存在
    assert row[1] == 12.0


def test_board_spec_uses_board_names_not_codes(tmp_path, mocker):
    """板块键路由: per_code 板块 spec 的迭代键应来自板块表(板块名), 而非股票代码种子。

    路由逻辑在 backfill._key_source(按 spec.key_domain 选键); run_ingest 本身保持泛型。
    """
    conn = db.connect(str(tmp_path / "t.duckdb"))
    db.init_schema(conn)
    # 先填充板块列表表(模拟 oneshot INDUSTRY_BOARD_SPEC 已跑过)
    conn.execute("INSERT INTO industry_board VALUES ('小金属', 'BK0001')")
    spy = mocker.patch("akshare.stock_board_industry_cons_em",
                       return_value=pd.DataFrame({"板块名称": ["小金属"], "代码": ["000001"]}))
    # _key_source 应丢弃股票代码 600519, 路由到板块名 "小金属"
    keys = backfill._key_source(conn, specs.INDUSTRY_CONST_SPEC, ["600519"])
    assert keys == ["小金属"]
    # 用路由后的键跑 run_ingest, 验证板块名(而非股票代码)到达数据源
    runner.run_ingest(conn, specs.INDUSTRY_CONST_SPEC, client=clientmod, code_source=keys)
    assert spy.call_args.kwargs.get("symbol") == "小金属"


def test_empty_board_table_no_fallback_to_stock_codes(tmp_path, mocker):
    """Important #1 回归: 板块表为空时,绝不可回退到股票代码当作板块键。

    场景: INDUSTRY_BOARD_SPEC oneshot 返回空 DF(无错),industry_board 表为空。
    _key_source 返回 []; 旧代码 `keys = code_source or _all_codes(conn)` 把 [] 当 falsy
    -> 回退到 stock_basic 的股票代码 -> 板块源被以股票代码为 key 调用(语义错+浪费额度)。
    修复: `keys = code_source if code_source is not None else _all_codes(conn)`。
    本测试在旧代码上 FAIL(spy 被以股票代码调用 1 次),在新代码上 PASS(spy 0 调用)。
    """
    conn = db.connect(str(tmp_path / "t.duckdb"))
    db.init_schema(conn)
    # stock_basic 有行 -> 若 bug 存在, _all_codes 回退会返回 ["000001"]
    conn.execute("INSERT INTO stock_basic (code, name) VALUES ('000001', '平安')")
    # industry_board 表刻意留空(模拟 oneshot 板块列表返回空)
    spy = mocker.patch("akshare.stock_board_industry_cons_em",
                       return_value=pd.DataFrame({"板块名称": ["小金属"], "代码": ["000001"]}))
    # 真实路径: 板块表为空时 _key_source 返回 []
    keys = backfill._key_source(conn, specs.INDUSTRY_CONST_SPEC, ["000001"])
    assert keys == []  # 空板块表 -> 无板块名
    runner.run_ingest(conn, specs.INDUSTRY_CONST_SPEC, client=clientmod, code_source=keys)
    # 板块源绝不可被调用(不可回退到股票代码)
    assert spy.call_count == 0


class _FastClient:
    """测试用 client: 直接转发 source(无节流/无重试),用于隔离测试快速失败。"""
    def fetch(self, func, *args, **kwargs):
        return func(*args, **kwargs)


def test_run_all_isolates_failing_spec(tmp_path, mocker):
    """Important #2 回归: 单个 spec 抛错(尤其 oneshot)不得中断整轮回填。

    旧代码 run_all 无 try/except 包裹 run_ingest -> 一个 oneshot ProxyError 即整轮中止,
    后续 macro 等 spec 永远跑不到。修复: run_all 内 per-spec try/except,记录后继续。
    本测试让首个 spec(STOCK_BASIC)源抛错,断言异常不外传且后续 spec(TRADE_CAL)仍落库。
    """
    conn = db.connect(str(tmp_path / "t.duckdb"))
    db.init_schema(conn)
    # STOCK_BASIC(首个 spec)源抛错
    mocker.patch("akshare.stock_info_a_code_name", side_effect=Exception("proxy boom"))
    # TRADE_CAL(在 STOCK_BASIC 之后)正常返回 1 行
    mocker.patch("akshare.tool_trade_date_hist_sina",
                 return_value=pd.DataFrame({"trade_date": ["2024-01-02"]}))
    # 其余源 mock 为空 DF,避免真实网络(用 _FastClient 跳过节流/重试,快速跑完)
    for fn in ["stock_zh_a_hist", "stock_zh_a_spot_em",
               "stock_financial_report_sina", "stock_financial_analysis_indicator",
               "stock_yjbb_em", "stock_board_industry_name_em", "stock_board_industry_cons_em",
               "stock_board_industry_hist_em", "stock_board_concept_name_em",
               "stock_board_concept_cons_em", "stock_margin_sse", "stock_lhb_detail_em",
               "stock_gdfx_holding_detail_em", "macro_china_cpi"]:
        mocker.patch(f"akshare.{fn}", return_value=pd.DataFrame())
    # 不得抛出
    backfill.run_all(conn, seed_path=str(SEED), periods=["20231231"], client=_FastClient())
    # 失败 spec 未落库
    assert conn.execute("SELECT count(*) FROM stock_basic").fetchone()[0] == 0
    # 后续 spec 仍执行并落库 -> 隔离生效
    assert conn.execute("SELECT count(*) FROM trade_calendar").fetchone()[0] == 1

