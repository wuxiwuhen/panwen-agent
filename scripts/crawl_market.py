#!/usr/bin/env python
"""全市场(或样本)爬取: 不复权日线(1 次/只) + 4 张财务表(带 raw JSON 全字段保留)。

设计要点:
  - 日线: ak.stock_zh_a_daily(adjust="") 一次拉全段(实测不截断), 不复权=真实成交价。
  - 财务: 利润/资产负债/现金流(stock_financial_report_sina) + 财务指标, 各 1 次/只;
          在 canonical 列之外加 raw JSON 列, 保留 akshare 返回的全部 83-147 字段
          (零额外请求 —— 数据已在响应里, 只是原本被 rename_map 丢弃)。
  - 限速: 全局最小调用间隔(跨线程), 默认 0.5s; 并发 worker 默认 2。
  - 断点续爬: 已完成 code 记入 data/.crawl_progress.json, 重跑自动跳过。
  - 错误隔离: 单只失败只记 error, 不中断整批。
  - 线程安全: 每个 worker 线程独立 DuckDB 连接(threading.local); 写事务由 DuckDB 串行。

proxy 关闭直连。写 data/live.duckdb。

用法:
  cd panwen && NO_PROXY='*' no_proxy='*' .venv/bin/python scripts/crawl_market.py --limit 50      # 50 只测试
  cd panwen && NO_PROXY='*' no_proxy='*' .venv/bin/python scripts/crawl_market.py                   # 全市场
  cd panwen && NO_PROXY='*' no_proxy='*' .venv/bin/python scripts/crawl_market.py --min-interval 1.0 --workers 1   # 保守档
"""
from __future__ import annotations
import os, sys, json, time, threading, argparse, importlib.util
from concurrent.futures import ThreadPoolExecutor, as_completed

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
DB = os.path.join(REPO, "data", "live.duckdb")
PROGRESS = os.path.join(REPO, "data", ".crawl_progress.json")

import akshare as ak
import duckdb
import pandas as pd
from panwen.data import schema
from panwen.data.ingest.specs import (INCOME_SPEC, BALANCE_SPEC, CASHFLOW_SPEC,
                                      FIN_INDICATOR_SPEC)
from panwen.data.ingest.mapping import to_sina_code, map_columns
from panwen.data.ingest.loader import upsert_df
from panwen.data.ingest import runner

DAILY_RENAME = {"date": "date", "open": "open", "high": "high", "low": "low",
                "close": "close", "volume": "volume", "amount": "amount", "turnover": "turnover"}
FIN_SPECS = [INCOME_SPEC, BALANCE_SPEC, CASHFLOW_SPEC, FIN_INDICATOR_SPEC]
FIN_TABLES = [s.table for s in FIN_SPECS]

# ---- 全局限速(跨线程) ----
_rate_lock = threading.Lock()
_last_call = [0.0]
_MIN_INTERVAL = 0.5


def throttled(func, *a, **kw):
    with _rate_lock:
        wait = _MIN_INTERVAL - (time.monotonic() - _last_call[0])
        if wait > 0:
            time.sleep(wait)
        _last_call[0] = time.monotonic()
    return func(*a, **kw)


# ---- 每线程独立 DuckDB 连接 ----
_tls = threading.local()


def setup_schema(conn):
    """建表 + 给 4 张财务表加 raw JSON 列。只在主线程单连接执行一次,
    避免多 worker 线程各自 ALTER 同一表触发 'Catalog write-write conflict'。"""
    for ddl in schema.TABLE_DDL.values():
        conn.execute(ddl)
    for t in FIN_TABLES:
        conn.execute(f"ALTER TABLE {t} ADD COLUMN IF NOT EXISTS raw JSON")


def get_conn():
    """每线程独立读写连接(表与 raw 列已由 setup_schema 在主线程建好,此处不再 DDL)。"""
    if not hasattr(_tls, "conn"):
        _tls.conn = duckdb.connect(DB)
    return _tls.conn


def _row_json(df_full: pd.DataFrame) -> list[str]:
    """整行 → JSON 字符串(NaN→null, 非法值→str)。保留 akshare 全部原始字段。"""
    out = []
    for rec in df_full.to_dict(orient="records"):
        clean = {}
        for k, v in rec.items():
            if isinstance(v, float) and v != v:      # NaN
                clean[k] = None
            else:
                clean[k] = v
        out.append(json.dumps(clean, ensure_ascii=False, default=str))
    return out


def _daily_symbol(code: str) -> str:
    """stock_zh_a_daily 的 symbol。北交所(43/83/87/88/92 开头)需 'bj' 前缀,沪深沿用 to_sina_code。
    注意: 财报接口 stock_financial_report_sina 对北交所仍用 'sh'(新浪财报库不分 bj),故此函数
    仅服务于日线,不替换 to_sina_code —— 否则会破坏财报入库。"""
    c = code.zfill(6)
    if c.startswith(("43", "83", "87", "88", "92")):
        return "bj" + c
    return to_sina_code(c)


def ingest_daily(conn, code, start_date, end_date) -> int:
    df = throttled(ak.stock_zh_a_daily, symbol=_daily_symbol(code),
                   start_date=start_date, end_date=end_date, adjust="")  # 不复权
    if df is None or len(df) == 0:
        return 0
    df = map_columns(df, DAILY_RENAME)
    df["code"] = code
    df = runner._normalize_dates(df, "daily_quote")
    return upsert_df(conn, "daily_quote", df, ["code", "date"])


def ingest_financial(conn, code, end_date) -> dict:
    """4 张财务表: canonical 列 + raw JSON 全字段。返回 {table: rows 或 'ERR:...'}。
    每张表独立 try: 单表失败记 ERR 不影响其他表, 也不向上抛 FATAL —— 否则一格卡死整批断点续传
    (且 done 误记: FATAL 路径 out={} 会被当成功)。ERR 仍计入返回值, 由调用方报告。"""
    counts = {}
    # 三大报表: 同一端点 stock_financial_report_sina, symbol=报表名
    for stmt, spec in [("利润表", INCOME_SPEC), ("资产负债表", BALANCE_SPEC), ("现金流量表", CASHFLOW_SPEC)]:
        try:
            df_full = throttled(ak.stock_financial_report_sina, stock=to_sina_code(code), symbol=stmt)
            if df_full is None or len(df_full) == 0:
                counts[spec.table] = 0
                continue
            df_full = df_full.reset_index(drop=True)
            df_cur = map_columns(df_full, spec.rename_map).copy()
            df_cur["code"] = code
            df_cur = runner._normalize_dates(df_cur, spec.table)  # report_date "YYYYMMDD"→"YYYY-MM-DD"(DATE 列要求)
            df_cur["raw"] = _row_json(df_full)  # raw 存 df_full 原始字段(未经规范化, 忠实保留 akshare 返回)
            counts[spec.table] = upsert_df(conn, spec.table, df_cur, spec.conflict_cols)
        except Exception as ex:
            counts[spec.table] = f"ERR:{type(ex).__name__}:{ex}"
    # 财务指标: 不同端点 (end_date 由调用方传入, 用于推算 start_year 回溯 5 年)
    spec = FIN_INDICATOR_SPEC
    try:
        df_full = throttled(ak.stock_financial_analysis_indicator, symbol=code,
                            start_year=str(int(end_date[:4]) - 5))
        if df_full is not None and len(df_full) > 0:
            df_full = df_full.reset_index(drop=True)
            df_cur = map_columns(df_full, spec.rename_map).copy()
            df_cur["code"] = code
            df_cur = runner._normalize_dates(df_cur, spec.table)
            df_cur["raw"] = _row_json(df_full)
            counts[spec.table] = upsert_df(conn, spec.table, df_cur, spec.conflict_cols)
        else:
            counts[spec.table] = 0
    except Exception as ex:
        counts[spec.table] = f"ERR:{type(ex).__name__}:{ex}"
    return counts


def ingest_code(code, start_date, end_date, daily_only=False) -> tuple[str, dict]:
    conn = get_conn()
    out = {}
    try:
        out["daily"] = ingest_daily(conn, code, start_date, end_date)
    except Exception as ex:
        out["daily"] = f"ERR:{type(ex).__name__}:{ex}"
    if not daily_only:
        out.update(ingest_financial(conn, code, end_date))
    return code, out


def load_done() -> set:
    if os.path.exists(PROGRESS):
        try:
            return set(json.load(open(PROGRESS, encoding="utf-8")))
        except Exception:
            return set()
    return set()


def save_done(done: set):
    tmp = PROGRESS + ".tmp"
    json.dump(sorted(done), open(tmp, "w", encoding="utf-8"), ensure_ascii=False)
    os.replace(tmp, PROGRESS)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="只爬前 N 只(0=全市场)")
    ap.add_argument("--min-interval", type=float, default=0.5, help="全局最小调用间隔(秒)")
    ap.add_argument("--workers", type=int, default=2, help="并发 worker 数")
    ap.add_argument("--years", type=int, default=5, help="日线回溯年数")
    ap.add_argument("--no-daily", action="store_true")
    ap.add_argument("--no-fin", action="store_true")
    ap.add_argument("--daily-only", action="store_true", help="只补日线(跳过财务, 用于补北交所/偶发缺失)")
    args = ap.parse_args()

    global _MIN_INTERVAL
    _MIN_INTERVAL = args.min_interval

    import datetime
    today = datetime.date.today()
    end_date = today.strftime("%Y%m%d")
    start_year = today.year - args.years
    start_date = f"{start_year}0101"
    print(f"[crawl] DB={DB} years={args.years}({start_date}~{end_date}) "
          f"min_interval={_MIN_INTERVAL}s workers={args.workers}", flush=True)

    # 股票清单
    basic = throttled(ak.stock_info_a_code_name)
    codes = sorted(basic["code"].tolist())
    done = load_done()
    todo = [c for c in codes if c not in done]
    if args.limit:
        todo = todo[:args.limit]
    print(f"[crawl] 全市场 {len(codes)} 只, 已完成 {len(done)}, 本次待爬 {len(todo)}", flush=True)
    if not todo:
        print("[crawl] 无待爬, 退出。", flush=True); return

    # 建表 + raw 列: 单连接执行一次(在 worker 拉起前), 杜绝并发 DDL 冲突
    _setup = duckdb.connect(DB)
    setup_schema(_setup)
    _setup.close()
    print("[crawl] schema 就绪 (建表 + 财务表 raw JSON 列)", flush=True)

    t0 = time.monotonic()
    done_new, errors = set(), []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futs = {pool.submit(ingest_code, c, start_date, end_date, args.daily_only): c for c in todo}
        for i, fut in enumerate(as_completed(futs), 1):
            code = futs[fut]
            out = None
            try:
                _, out = fut.result()
            except Exception as ex:
                errors.append((code, f"FATAL:{type(ex).__name__}:{ex}"))
            if out is not None:
                # 非致命: 收集各表 ERR 供报告; 只要 daily 没挂就记 done
                # (断点续传不为单张财务表的持久失败卡死——那类数据本就"能爬才留")
                err_in = [f"{k}={v}" for k, v in out.items()
                          if isinstance(v, str) and str(v).startswith("ERR")]
                if err_in:
                    errors.append((code, "; ".join(err_in)))
                daily_ok = not (isinstance(out.get("daily"), str) and str(out["daily"]).startswith("ERR"))
                if daily_ok:
                    done_new.add(code)
                    done.add(code)
                # else: daily 挂 → 不记 done, 下次重试(已在 errors 报告)
            if i % 10 == 0 or i == len(todo):
                el = time.monotonic() - t0
                rate = i / el if el > 0 else 0
                eta = (len(todo) - i) / rate if rate > 0 else 0
                save_done(done)
                print(f"  [{i}/{len(todo)}] {code} | {out} | "
                      f"{rate:.2f} 只/s | ETA {eta/60:.0f}min | err {len(errors)}", flush=True)

    save_done(done)
    el = time.monotonic() - t0
    print(f"\n[crawl] DONE 本次 {len(done_new)} 只, 用时 {el/60:.1f}min, 错误 {len(errors)} 只", flush=True)
    if errors:
        print("  错误样本(前 20):", flush=True)
        for c, e in errors[:20]:
            print(f"    {c}: {e}", flush=True)
        print(f"  (共 {len(errors)} 只失败, 可重跑本脚本自动续爬)", flush=True)


if __name__ == "__main__":
    main()
