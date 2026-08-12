import argparse
from panwen.data import snapshots


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", default="data/live.duckdb")
    ap.add_argument("--eval", default="data/eval.duckdb")
    ap.add_argument("--as-of", required=True, help="冻结截止日 YYYY-MM-DD")
    a = ap.parse_args()
    snapshots.freeze_eval(a.live, a.eval, a.as_of)
    print(f"frozen → {a.eval} as_of={a.as_of}")


if __name__ == "__main__":
    main()
