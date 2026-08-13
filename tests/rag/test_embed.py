"""Task 3: embedding 基建。FakeEmbedder 确定性、离线。"""
import numpy as np
from panwen.rag import embed


def test_fake_embedder_is_deterministic():
    e = embed.FakeEmbedder(dim=8)
    a = e.embed_texts(["茅台", "茅台"])
    assert np.allclose(a[0], a[1])  # 相同文本相同向量


def test_cosine_topk_returns_nearest():
    e = embed.FakeEmbedder(dim=16)
    q = e.embed_texts(["白酒股的ROE"])[0]
    docs = e.embed_texts(["贵州茅台净利润", "CPI 同比", "白酒行业 ROE"])
    idx = embed.cosine_topk(q, docs, k=1)
    # cosine_topk should return the true argmax of cosine similarity,
    # independent of what the FakeEmbedder's vectors happen to be.
    expected = int(np.argmax(docs @ q))
    assert idx[0] == expected
    # determinism: same inputs → same result (the test's stated "确定性" intent)
    assert embed.cosine_topk(q, docs, k=1) == idx


def test_bge_embedder_lazy_load_not_required_for_unit():
    # 单测不触发 HF 下载：BgeEmbedder 仅在实例化后调 embed 才下载
    assert hasattr(embed, "BgeEmbedder")
