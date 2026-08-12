"""校验评测集 gold_sql 在冻结 eval.duckdb 上可执且返回确定行(spec §12.3)。

用法: python scripts/validate_gold.py [--eval data/eval.duckdb] [--dataset panwen/eval/dataset/questions.yaml]
退出码 0 = 全部 gold 可执且值非空；非 0 = 有 gold 失败(可执异常 / 全-NULL / 0 行)。

双重诚实保证(2026-08-13 review hardening):
  1. 旧检查: gold_sql 必须可执,返回 N 行(N 可能为 0)。
  2. 新检查: 若结果含 ≥1 个 value 列(非键列),则该列集合在返回行里必须存在 ≥1 个非-NULL 值。
     —— 抓住 "可执但每行 value 都是 NULL" 的静默 bug(如选了 gross_margin 但该列只 2019 前有数据)。
     键列(identity/dimension,非"答案值")不参与非空判定: code/report_date/date/trade_date/
     name/board_name/indicator/market/symbol/ts_code。
"""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from panwen.data import db
from panwen.eval import loader

# 这些列是身份/维度键,不是"答案值"。其余列才视为 value 列,需有非-NULL 值。
KEY_COLS = {
    "code", "report_date", "date", "trade_date", "name", "board_name",
    "indicator", "market", "symbol", "ts_code",
}


def _value_col_indices(cols: list[str]) -> list[int]:
    """返回非键列的索引列表(用于非空检查)。"""
    return [i for i, c in enumerate(cols) if c.lower() not in KEY_COLS]


def main(eval_path: str = "data/eval.duckdb",
         dataset: str = "panwen/eval/dataset/questions.yaml") -> int:
    items = loader.load_dataset(dataset)
    conn = db.connect(eval_path, read_only=True)
    failures = 0
    skipped = 0
    try:
        for it in items:
            if it.gold_sql is None:
                skipped += 1
                continue  # out_of_scope 题跳过
            try:
                cur = conn.execute(it.gold_sql)
                rows = cur.fetchall()
                cols = [d[0] for d in cur.description] if cur.description else []
            except Exception as e:
                failures += 1
                print(f"[FAIL] {it.question[:40]}\n       {e}")
                continue

            # 可执但 0 行 — 标记可疑(可执但无答案,可能是 schema 失配或过严过滤)
            if not rows:
                failures += 1
                print(f"[FAIL 0-row] {it.difficulty:10s} {it.question[:30]:30s} → 0 行")
                continue

            # 值非空检查: 在 value 列里必须有 ≥1 个非-NULL 值
            val_idx = _value_col_indices(cols)
            if val_idx:
                non_null = sum(1 for r in rows for i in val_idx if r[i] is not None)
                if non_null == 0:
                    failures += 1
                    val_names = [cols[i] for i in val_idx]
                    print(f"[FAIL all-NULL] {it.difficulty:10s} {it.question[:30]:30s} "
                          f"→ {len(rows)} 行 但 value 列全 NULL: {val_names}")
                    continue
                print(f"[ok] {it.difficulty:10s} {it.question[:30]:30s} "
                      f"→ {len(rows)} 行 (值非空)")
            else:
                # 只选了键列(如 SELECT code,name FROM ...)——跳过非空检查
                print(f"[ok] {it.difficulty:10s} {it.question[:30]:30s} "
                      f"→ {len(rows)} 行 (仅键列,跳过非空检查)")
    finally:
        conn.close()
    status = "全部 gold 可执且值非空" if failures == 0 else f"{failures} 条 gold 失败"
    print(f"\n{status}（跳过 {skipped} 条 out_of_scope）")
    return 1 if failures else 0


if __name__ == "__main__":
    args = sys.argv[1:]
    kwargs = {}
    while args:
        flag = args.pop(0)
        if flag == "--eval" and args:
            kwargs["eval_path"] = args.pop(0)
        elif flag == "--dataset" and args:
            kwargs["dataset"] = args.pop(0)
    sys.exit(main(**kwargs))
