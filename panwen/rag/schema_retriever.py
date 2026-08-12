"""schema_retriever(常开) —— 问题 embedding × schema 文档 embedding → top-k 表/列子集。

目的：控进 prompt 的 token + 降列幻觉(只给相关列)。
"""
from __future__ import annotations
from pathlib import Path
import numpy as np

from panwen.rag.embed import Embedder, cosine_topk
from panwen.rag.schema_docs import SchemaDocEntry, build_schema_docs


class SchemaRetriever:
    def __init__(self, embedder: Embedder, topk: int = 5, cache_dir: str | None = None):
        self.embedder = embedder
        self.topk = topk
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self._entries: list[SchemaDocEntry] | None = None
        self._matrix: np.ndarray | None = None

    def ensure_indexed(self) -> None:
        if self._matrix is not None:
            return
        cache = self.cache_dir / "schema_docs.npy" if self.cache_dir else None
        if cache and cache.exists():
            self._matrix = np.load(cache)
            self._entries = build_schema_docs()  # 文本可重建(代码即数据)
            return
        self._entries = build_schema_docs()
        docs = [f"{e.table}{'.'+e.column if e.column else ''} {e.doc}" for e in self._entries]
        self._matrix = self.embedder.embed_texts(docs)
        if cache:
            cache.parent.mkdir(parents=True, exist_ok=True)
            np.save(cache, self._matrix)

    def retrieve(self, question: str) -> list[SchemaDocEntry]:
        self.ensure_indexed()
        q = self.embedder.embed_texts([question])[0]
        idx = cosine_topk(q, self._matrix, k=self.topk)
        return [self._entries[i] for i in idx]
