"""从 eval 集取 answerable 问句做 UI 示例按钮。"""
from __future__ import annotations
from panwen.eval.loader import load_dataset

DATASET = "panwen/eval/dataset/questions.yaml"


def example_questions(path: str = DATASET, limit: int = 8) -> list[str]:
    """返回前 limit 个 answerable（gold_sql 非空）问句，按 dataset 原顺序。"""
    items = load_dataset(path)
    return [it.question for it in items if it.gold_sql is not None][:limit]
