"""评测集 loader(spec §8.1)。读 dataset/*.yaml → list[EvalItem]。"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import yaml


@dataclass(frozen=True)
class EvalItem:
    question: str
    gold_sql: str | None       # None = out_of_scope 题无 gold
    difficulty: str            # simple | join | aggregate | domain
    tags: list[str]
    answerable_on: str         # 冻结 as-of (Task 0 实测 2026-06-30)


def load_dataset(path: str) -> list[EvalItem]:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return [EvalItem(
        question=r["question"],
        gold_sql=r.get("gold_sql"),
        difficulty=r["difficulty"],
        tags=list(r.get("tags", [])),
        answerable_on=r["answerable_on"],
    ) for r in raw]
