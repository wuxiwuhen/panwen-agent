import argparse
from datetime import datetime
from panwen.data import snapshots


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", default="data/live.duckdb")
    ap.add_argument("--eval", default="data/eval.duckdb")
    ap.add_argument("--as-of", required=True, help="冻结截止日 YYYY-MM-DD")
    a = ap.parse_args()
    # Fix 2: 校验 as_of 为合法 YYYY-MM-DD。snapshots.freeze_eval 会把它 f-string
    # 内插进 DELETE SQL;畸形日期会静默改变比较语义(且为注入面)。strptime 在非法
    # 输入上抛 ValueError(argparse 会将其呈现给用户),守护 eval 可复现性
    # (eval.duckdb 支撑 Plan-3 全部指标)。
    datetime.strptime(a.as_of, "%Y-%m-%d")
    snapshots.freeze_eval(a.live, a.eval, a.as_of)
    print(f"frozen → {a.eval} as_of={a.as_of}")


if __name__ == "__main__":
    main()
