"""Task 5: fewshot_store 检索 top-k (Q→SQL)。"""
from panwen.rag import fewshot_store as fs
from panwen.rag.embed import FakeEmbedder


def _toy_examples():
    return [
        fs.FewshotExample(question="茅台净利润", sql="SELECT net_profit FROM income_statement WHERE code='600519'"),
        fs.FewshotExample(question="CPI 同比", sql="SELECT value FROM macro_series WHERE name LIKE '%CPI%'"),
    ]


def test_retrieve_returns_topk_sql():
    examples = _toy_examples()
    store = fs.FewshotStore(examples, embedder=FakeEmbedder(dim=32), k=1)
    out = store.retrieve("贵州茅台的利润")
    assert len(out) == 1                  # returns k items
    assert out[0] in examples             # returned item is from the store
    assert store.retrieve("贵州茅台的利润") == out   # deterministic


def test_skips_none_sql():
    # gold_sql=None 的 out_of_scope 题不进 fewshot
    ex = _toy_examples() + [fs.FewshotExample(question="写代码", sql=None)]
    store = fs.FewshotStore(ex, embedder=FakeEmbedder(dim=32), k=5)
    assert len(store.retrieve("任意")) <= 2  # 只有 2 条非 None


def test_from_dataset_loads_real_yaml_and_filters_none():
    from pathlib import Path
    ROOT = Path(__file__).resolve().parents[2]
    dataset = str(ROOT / "panwen" / "eval" / "dataset" / "questions.yaml")
    store = fs.FewshotStore.from_dataset(dataset, embedder=FakeEmbedder(dim=32), k=100)
    # k=100 > total examples → retrieve returns ALL indexed (non-None) examples
    out = store.retrieve("任意查询")
    assert len(out) == 21   # 21 gold_sql non-None; the 4 out_of_scope (None) filtered out
