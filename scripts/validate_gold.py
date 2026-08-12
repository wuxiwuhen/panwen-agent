"""校验评测集 gold_sql 在冻结 eval.duckdb 上可执且返回确定行(spec §12.3)。

用法: python scripts/validate_gold.py [--eval data/eval.duckdb] [--dataset panwen/eval/dataset/questions.yaml]
退出码 0 = 全部 gold 可执；非 0 = 有 gold 失败(打印哪条)。
"""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from panwen.data import db
from panwen.eval import loader


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
                rows = conn.execute(it.gold_sql).fetchall()
                print(f"[ok] {it.difficulty:10s} {it.question[:30]:30s} → {len(rows)} 行")
            except Exception as e:
                failures += 1
                print(f"[FAIL] {it.question[:40]}\n       {e}")
    finally:
        conn.close()
    print(f"\n{'全部 gold 可执' if failures == 0 else f'{failures} 条 gold 失败'}"
          f"（跳过 {skipped} 条 out_of_scope）")
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
