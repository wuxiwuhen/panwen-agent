"""维度面板(spec §8.4) —— 按 difficulty / SQL 结构切片准确率。"""
from __future__ import annotations
from collections import defaultdict
from panwen.eval.runner import EvalReport


def by_difficulty(report: EvalReport) -> dict[str, float]:
    buckets = defaultdict(list)
    for it in report.items:
        buckets[it.difficulty].append(it.correct)
    return {d: sum(v) / len(v) for d, v in buckets.items()}


def render(report: EvalReport) -> str:
    lines = [f"总体执行准确率: {report.exec_acc:.1%} ({report.n} 题)",
             f"平均 F1: {report.mean_f1:.3f}", "", "按难度切片:"]
    for d, acc in sorted(by_difficulty(report).items()):
        lines.append(f"  {d:12s} {acc:.1%}")
    return "\n".join(lines)
