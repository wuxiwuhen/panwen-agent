"""Task 3: schema_retriever 在固定小语料上测召回排序(用 FakeEmbedder)。"""
from panwen.rag import schema_retriever as sr
from panwen.rag.embed import FakeEmbedder


def test_retrieve_returns_topk_entries():
    r = sr.SchemaRetriever(embedder=FakeEmbedder(dim=32), topk=3)
    out = r.retrieve("茅台近三年 ROE")
    assert len(out) <= 3
    assert all(hasattr(e, "table") for e in out)


def test_retrieve_uses_cache(tmp_path):
    r = sr.SchemaRetriever(embedder=FakeEmbedder(dim=32), topk=3,
                           cache_dir=str(tmp_path))
    r.ensure_indexed()
    assert (tmp_path / "schema_docs.npy").exists()
    # 第二次构造应命中缓存(不重算)
    r2 = sr.SchemaRetriever(embedder=FakeEmbedder(dim=32), topk=3,
                            cache_dir=str(tmp_path))
    r2.ensure_indexed()
    out = r2.retrieve("某问题")
    assert len(out) <= 3
