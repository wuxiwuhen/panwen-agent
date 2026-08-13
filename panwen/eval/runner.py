"""eval runner(spec §8.2) —— 单配置跑全集 → exec_acc + F1。

执行准确率(主): pred 与 gold 在 eval.duckdb 上结果集一致。
F1 软评分: 部分行匹配给 0..1。
"""
from __future__ import annotations
from dataclasses import dataclass
from panwen.data import db
from panwen.eval.loader import load_dataset, EvalItem


@dataclass
class ItemResult:
    question: str
    difficulty: str
    correct: bool
    f1: float


@dataclass
class EvalReport:
    exec_acc: float
    mean_f1: float
    n: int
    items: list[ItemResult]


def _exec(conn, sql: str | None) -> list[dict]:
    """执行 SQL → dict 行列表(用 cursor.description 取列名)。"""
    if not sql:
        return []
    cur = conn.execute(sql)
    cols = [d[0] for d in cur.description] if cur.description else []
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def row_sets_equal(a: list[dict], b: list[dict]) -> bool:
    return sorted(map(tuple, (sorted(d.items()) for d in a))) == \
           sorted(map(tuple, (sorted(d.items()) for d in b)))


def pr_f1(gold: list[dict], pred: list[dict]) -> tuple[float, float, float]:
    g = {tuple(sorted(d.items())) for d in gold}
    p = {tuple(sorted(d.items())) for d in pred}
    if not p:
        return 0.0, 0.0, 0.0
    tp = len(g & p)
    prec = tp / len(p)
    rec = tp / len(g) if g else 0.0
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
    return prec, rec, f1


def run_eval(dataset_path: str, eval_db: str, predict_fn, tags_filter: list[str] | None = None) -> EvalReport:
    """predict_fn(question) -> (pred_sql, pred_rows). gold 从 eval_db 跑。"""
    items = load_dataset(dataset_path)
    if tags_filter:
        items = [i for i in items if any(t in i.tags for t in tags_filter)]
    conn = db.connect(eval_db, read_only=True)
    results: list[ItemResult] = []
    try:
        for it in items:
            gold_rows = _exec(conn, it.gold_sql)
            pred_sql, pred_rows = predict_fn(it.question)
            correct = row_sets_equal(gold_rows, pred_rows or [])
            _, _, f1 = pr_f1(gold_rows, pred_rows or [])
            results.append(ItemResult(it.question, it.difficulty, correct, f1))
    finally:
        conn.close()
    n = len(results)
    acc = sum(r.correct for r in results) / n if n else 0.0
    mf1 = sum(r.f1 for r in results) / n if n else 0.0
    return EvalReport(exec_acc=acc, mean_f1=mf1, n=n, items=results)
