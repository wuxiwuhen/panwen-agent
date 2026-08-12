"""双路 RAG 共享的 embedding 基建(spec §7)。

- BgeEmbedder: BAAI/bge-large-zh-v1.5(本地、离线、免费)，懒加载。
- FakeEmbedder: 确定性哈希向量，单测离线用(零下载)。
预计算缓存到 data/rag_cache/(gitignore)。
"""
from __future__ import annotations
import hashlib
from pathlib import Path
from typing import Protocol

import numpy as np

MODEL_NAME = "BAAI/bge-large-zh-v1.5"
CACHE_DIR = Path("data/rag_cache")


class Embedder(Protocol):
    dim: int
    def embed_texts(self, texts: list[str]) -> np.ndarray: ...   # (n, dim)


class FakeEmbedder:
    """确定性哈希向量(单测用)。相同文本 → 相同向量，无语义，但可调用且离线。"""
    def __init__(self, dim: int = 64):
        self.dim = dim

    def embed_texts(self, texts: list[str]) -> np.ndarray:
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for i, t in enumerate(texts):
            h = hashlib.sha256(t.encode("utf-8")).digest()
            for j in range(self.dim):
                out[i, j] = (h[j % len(h)] / 255.0) * 2 - 1
        # L2 归一化
        n = np.linalg.norm(out, axis=1, keepdims=True)
        n[n == 0] = 1.0
        return out / n


class BgeEmbedder:
    """bge-large-zh-v1.5。模型在首次 embed 时懒加载(避免单测下载)。"""
    def __init__(self, model_name: str = MODEL_NAME):
        self.model_name = model_name
        self._model = None
        self.dim = 1024  # bge-large-zh-v1.5 输出维度

    def _load(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self.model_name)
            self.dim = self._model.get_sentence_embedding_dimension()
        return self._model

    def embed_texts(self, texts: list[str]) -> np.ndarray:
        model = self._load()
        vecs = model.encode(texts, normalize_embeddings=True, convert_to_numpy=True)
        return np.asarray(vecs, dtype=np.float32)


def cosine_topk(query_vec: np.ndarray, doc_matrix: np.ndarray, k: int) -> list[int]:
    """返回最相似的 k 个文档下标(降序)。向量已 L2 归一化时点积即 cosine。"""
    q = query_vec / (np.linalg.norm(query_vec) + 1e-9)
    d = doc_matrix / (np.linalg.norm(doc_matrix, axis=1, keepdims=True) + 1e-9)
    sims = d @ q
    k = min(k, len(sims))
    return list(np.argsort(-sims)[:k])
