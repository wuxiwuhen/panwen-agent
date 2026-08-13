"""fewshot_store(config.use_fewshot) —— 检索 eval 集 (Q→SQL) 作 few-shot(spec §7)。

复用 embed 基建。只索引 gold_sql 非空的题(out_of_scope 不进)。
"""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np

from panwen.rag.embed import Embedder, cosine_topk


@dataclass(frozen=True)
class FewshotExample:
    question: str
    sql: str | None


class FewshotStore:
    def __init__(self, examples: list[FewshotExample], embedder: Embedder, k: int = 3):
        self.k = k
        self.embedder = embedder
        self._examples = [e for e in examples if e.sql]   # 丢 None
        self._matrix = self.embedder.embed_texts([e.question for e in self._examples]) \
            if self._examples else np.zeros((0, embedder.dim), dtype=np.float32)

    @classmethod
    def from_dataset(cls, dataset_path: str, embedder: Embedder, k: int = 3) -> "FewshotStore":
        from panwen.eval import loader
        items = loader.load_dataset(dataset_path)
        return cls([FewshotExample(question=i.question, sql=i.gold_sql) for i in items],
                   embedder=embedder, k=k)

    def retrieve(self, question: str) -> list[FewshotExample]:
        if not self._examples:
            return []
        q = self.embedder.embed_texts([question])[0]
        idx = cosine_topk(q, self._matrix, k=self.k)
        return [self._examples[i] for i in idx]
