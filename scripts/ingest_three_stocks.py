#!/usr/bin/env python
"""定向入库: 信维通信(300136) / 京东方A(000725) / 澄星股份(600078)。

绕开被限流的 eastmoney push2his 子域(本 IP 临时封):
  - 日线改用 sina/tencent 版 stock_zh_a_daily(push2his 的 stock_zh_a_hist 被封)
  - 财务三表 + 财务指标走 sina(本就通)
  - 业绩快报 / 十大股东走 eastmoney datacenter(push2 被封, datacenter 通)

限速: monkeypatch client.fetch, min_interval 随机 2-4s; 指数退避保留在原 fetch 内。
写 live.duckdb。幂等 upsert, 可重复跑。

手动执行(代理关闭 + 直连):
  cd panwen && NO_PROXY='*' no_proxy='*' .venv/bin/python scripts/ingest_three_stocks.py
"""
from __future__ import annotations
import random
import duckdb
import akshare as ak
from panwen.data import schema
from panwen.data.ingest import specs, runner, mapping, loader, client as clientmod
from panwen.data.ingest.specs import Spec, _KEY
from panwen.data.ingest.mapping import to_sina_code

CODES = ["300136", "000725", "600078"]
NAMES = {"300136": "信维通信", "000725": "京东方A", "600078": "澄星股份"}
import os
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(_REPO, "data", "live.duckdb")

# ---- 限速注入: min_interval 随机 2-4s, 指数退避保留在原 fetch 内 ----
_orig_fetch = clientmod.fetch


def slow_fetch(func, *a, min_interval=None, retries=3, **kw):
    return _orig_fetch(func, *a, min_interval=random.uniform(2, 4), retries=retries, **kw)


clientmod.fetch = slow_fetch

# ---- sina 版日线 spec (绕开 eastmoney push2his 限流) ----
SINA_DAILY = Spec(
    name="daily_quote", table="daily_quote",
    source=lambda *a, **kw: ak.stock_zh_a_daily(*a, **kw),
    iteration="per_code",
    rename_map={"date": "date", "open": "open", "high": "high", "low": "low",
                "close": "close", "volume": "volume", "amount": "amount", "turnover": "turnover"},
    conflict_cols=["code", "date"],
    arg_builder=lambda code: {"symbol": to_sina_code(code), "adjust": ""},  # 不复权=真实成交价; hfq 后复权会叠加历史除权除息, 偏离现价十数倍(见 300136: hfq 912 vs 真实 68.58)
    const_cols={"code": _KEY},  # stock_zh_a_daily 不返回 code, 从迭代键注入
)
# daily 按两年分段, 避免单次大拉被服务端掐断(sina 稳健, 仍分段保险)
DAILY_CHUNKS = [("20150101", "20161231"), ("20170101", "20181231"), ("20190101", "20201231"),
                ("20210101", "20221231"), ("20230101", "20241231"), ("20250101", "20260813")]

# 业绩快报: 全市场按报告期批量, 入库前过滤到这 3 只(端点无单股过滤)
PERF_PERIODS = ["20240331", "20240630", "20240930", "20241231",
                "20250331", "20250630", "20250930", "20251231", "20260331", "20260630"]


def log(msg):
    print(msg, flush=True)


def main():
    conn = duckdb.connect(DB)
    for ddl in schema.TABLE_DDL.values():
        conn.execute(ddl)
    log(f"[connect] {DB} schema ready (CREATE IF NOT EXISTS)")

    # ===== A. daily_quote (sina stock_zh_a_daily, 分段) =====
    log("[A] daily_quote via stock_zh_a_daily (sina) — chunked by 2 years")
    for code in CODES:
        for s, e in DAILY_CHUNKS:
            try:
                df = clientmod.fetch(SINA_DAILY.source, symbol=to_sina_code(code),
                                     start_date=s, end_date=e, adjust="")  # 不复权: 对齐真实市价(同花顺收盘价)
                raw = len(df)
                df = mapping.map_columns(df, SINA_DAILY.rename_map)
                if raw > 0 and len(df.columns) == 0:
                    log(f"  [drift] {code} {s}-{e}: 0 cols matched rename_map")
                    continue
                df = runner._apply_const(df, SINA_DAILY.const_cols, key=code)
                df = runner._normalize_dates(df, SINA_DAILY.table)
                n = loader.upsert_df(conn, SINA_DAILY.table, df, SINA_DAILY.conflict_cols)
                log(f"  {code} {NAMES[code]} {s}-{e}: +{n}")
            except Exception as ex:
                log(f"  [warn] daily {code} {s}-{e}: {type(ex).__name__}: {ex}")

    # ===== B. 财务三表 + 财务指标 (sina, per_code, 经管线) =====
    log("[B] financial statements via sina (income/balance/cashflow/indicator)")
    for spec in [specs.INCOME_SPEC, specs.BALANCE_SPEC, specs.CASHFLOW_SPEC, specs.FIN_INDICATOR_SPEC]:
        n = runner.run_ingest(conn, spec, client=clientmod, code_source=CODES)
        log(f"  {spec.name:14s} -> {spec.table}: +{n} rows")

    # ===== C. 业绩快报 (eastmoney datacenter, 全市场按期, 过滤到 3 只) =====
    log("[C] performance_express via stock_yjbb_em (datacenter, filtered to 3 codes)")
    PERF = specs.PERFORMANCE_SPEC
    for period in PERF_PERIODS:
        try:
            df = clientmod.fetch(PERF.source, **PERF.arg_builder(period))
            df = mapping.map_columns(df, PERF.rename_map)
            if "code" in df.columns:
                df = df[df["code"].isin(CODES)]
            df = runner._normalize_dates(df, PERF.table)
            n = loader.upsert_df(conn, PERF.table, df, PERF.conflict_cols)
            log(f"  perf {period}: +{n}")
        except Exception as ex:
            log(f"  [warn] perf {period}: {type(ex).__name__}: {ex}")

    # ===== D. 十大股东 (eastmoney datacenter per_code; 代理关闭后 datacenter 可达) =====
    log("[D] top10_holders via stock_gdfx_holding_detail_em (datacenter; rename_map 待校验)")
    try:
        n = runner.run_ingest(conn, specs.TOP10_HOLDERS_SPEC, client=clientmod, code_source=CODES)
        log(f"  top10_holders -> +{n} rows (0 可能是 rename_map 漂移, 见 [drift])")
    except Exception as ex:
        log(f"  [warn] top10: {type(ex).__name__}: {ex}")

    # ===== 报告: 入库后这 3 只在各表的行数 =====
    log("\n===== 入库结果 (live.duckdb, 这 3 只) =====")

    def cnt(table, code):
        return conn.execute(
            "SELECT COUNT(*) FROM " + table + " WHERE code = ?", [code]).fetchone()[0]

    for code in CODES:
        log(f"-- {code} {NAMES[code]} --")
        log(f"   daily_quote         : {cnt('daily_quote', code)}")
        log(f"   income_statement    : {cnt('income_statement', code)}")
        log(f"   balance_sheet       : {cnt('balance_sheet', code)}")
        log(f"   cashflow_statement  : {cnt('cashflow_statement', code)}")
        log(f"   financial_indicator : {cnt('financial_indicator', code)}")
        log(f"   performance_express : {cnt('performance_express', code)}")
        log(f"   top10_holders       : {cnt('top10_holders', code)}")
        log(f"   dragon_tiger(既有)  : {cnt('dragon_tiger', code)}")
    conn.close()
    log("DONE")


if __name__ == "__main__":
    main()
