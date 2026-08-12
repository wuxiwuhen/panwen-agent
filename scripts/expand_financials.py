"""Task 0: sina 财务定向扩量 —— 把 4 张财务表从 2 股扩到 eval_codes 种子股。

只跑 sina 端点(income/balance/cashflow/fin_indicator)，避开 eastmoney 限流。
写入 data/live.duckdb(已存在则 upsert，幂等)。
用法: python scripts/expand_financials.py
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from panwen.data import db
from panwen.data.ingest import client, runner, specs
from panwen.eval.seeds import load_codes

LIVE = "data/live.duckdb"
SEED = "panwen/seeds/eval_codes.txt"

# 只用 sina 的 4 个财务 spec —— 绝不带 eastmoney PERFORMANCE_SPEC
SINA_FINANCIAL_SPECS = [
    specs.INCOME_SPEC, specs.BALANCE_SPEC, specs.CASHFLOW_SPEC, specs.FIN_INDICATOR_SPEC,
]


def main() -> None:
    codes = load_codes(SEED)
    print(f"[task0] 扩量财务: {len(codes)} 只种子股 → {LIVE}")
    conn = db.connect(LIVE)
    db.init_schema(conn)
    try:
        for spec in SINA_FINANCIAL_SPECS:
            n = runner.run_ingest(conn, spec, client=client, code_source=codes)
            print(f"[task0] {spec.name:14s} upsert 完成 ({n} 行受影响)")
    finally:
        conn.close()
    print("[task0] 完成。下一步: make eval-freeze 冻结。")


if __name__ == "__main__":
    main()
