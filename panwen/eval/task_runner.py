"""外层任务级评测(spec §8.3) —— 度量 agent loop 的编排质量，而非执行准确率。

与内层 runner.py 共存、互补：
  - 内层(runner.run_eval)    : 度量 query_database 的 gold-SQL 执行准确率 + F1。
  - 外层(task_runner.run_task_eval): 度量 run_agent 的切面覆盖(facet recall)
                                      + 客观产出量(表数 / 溯源数)。

切面(facet)词汇 = 窄 tool 名去掉 `get_` 前缀：
    stock_profile / financials / recent_quotes / performance
query_database 不属于任何窄切面，映射为 "sql"（仅作记录，不计入上述词汇）。

判定(人工 or LLM-judge，spec §15#2)暂缓实现 —— 本模块只产出三个客观量：
facet_recall、table_count、source_count。
"""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
import yaml


# tool 名 → 切面。query_database 记为 "sql"，不与窄切面词汇混淆。
TOOL_FACET: dict[str, str] = {
    "get_stock_profile": "stock_profile",
    "get_financials":    "financials",
    "get_recent_quotes": "recent_quotes",
    "get_performance":   "performance",
    "query_database":    "sql",
}


@dataclass(frozen=True)
class TaskItem:
    id: str
    question: str
    expected_facets: list[str]


@dataclass
class TaskResult:
    id: str
    question: str
    expected_facets: list[str]
    called_tools: list[str]
    facet_recall: float
    hit_facets: list[str]
    missed_facets: list[str]
    table_count: int
    source_count: int


@dataclass
class TaskReport:
    mean_facet_recall: float
    n: int
    total_tables: int
    total_sources: int
    items: list[TaskResult] = field(default_factory=list)


def load_task_dataset(path: str) -> list[TaskItem]:
    """读 task_dataset.yaml → list[TaskItem]。"""
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return [TaskItem(
        id=r["id"],
        question=r["question"],
        expected_facets=list(r["expected_facets"]),
    ) for r in raw]


def score_task(called_tools: list[str], expected_facets: set[str]) -> dict:
    """把 agent 调过的 tool 名映射到切面，计算相对期望切面的召回率。

    facet_recall = |hit ∩ expected| / |expected|
    """
    hit = {TOOL_FACET[t] for t in called_tools if t in TOOL_FACET} & set(expected_facets)
    expected = set(expected_facets)
    recall = len(hit) / len(expected) if expected else 0.0
    missed = sorted(expected - hit)
    return {
        "facet_recall":  recall,
        "hit_facets":    sorted(hit),
        "missed_facets": missed,
    }


def run_task_eval(dataset, run_agent_fn) -> TaskReport:
    """跑外层任务级评测。

    dataset       : list[TaskItem] (load_task_dataset 的产物)
    run_agent_fn  : callable(question) -> AgentRun
                    (panwen.agent.agent_loop.run_agent 的签名更宽，调用方可用
                     functools.partial 绑定 conn/backend/rag/... 后传入)

    对每题：抓 AgentRun.trace 里每个 TraceStep.stage(= tool 名) → 映射切面
    → score_task；并记录客观产出量 table_count(= len(ar.tables))、
    source_count(= len(ar.sources))。
    """
    results: list[TaskResult] = []
    for it in dataset:
        ar = run_agent_fn(it.question)
        # Task 8 中每次 tool 调用 append TraceStep(tc["name"], ...)，
        # 故 trace_step.stage 即为被调 tool 名。
        called_tools = [s.stage for s in (ar.trace or [])]
        score = score_task(called_tools, set(it.expected_facets))
        results.append(TaskResult(
            id=it.id,
            question=it.question,
            expected_facets=list(it.expected_facets),
            called_tools=called_tools,
            facet_recall=score["facet_recall"],
            hit_facets=score["hit_facets"],
            missed_facets=score["missed_facets"],
            table_count=len(getattr(ar, "tables", []) or []),
            source_count=len(getattr(ar, "sources", []) or []),
        ))
    n = len(results)
    return TaskReport(
        mean_facet_recall=(sum(r.facet_recall for r in results) / n) if n else 0.0,
        n=n,
        total_tables=sum(r.table_count for r in results),
        total_sources=sum(r.source_count for r in results),
        items=results,
    )
