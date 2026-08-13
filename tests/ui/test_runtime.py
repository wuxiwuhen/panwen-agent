from panwen.ui import runtime
from panwen.rag.embed import FakeEmbedder


def test_get_runtime_caches_singleton(monkeypatch):
    """懒单例：第二次 get 直接复用，build 只调一次。"""
    runtime.reset_runtime()
    calls = []

    def fake_build(**kw):
        calls.append(kw)
        return object()  # sentinel，不触发真实构造

    monkeypatch.setattr(runtime, "build_runtime", fake_build)
    r1 = runtime.get_runtime()
    r2 = runtime.get_runtime()
    assert r1 is r2
    assert len(calls) == 1
    runtime.reset_runtime()


def test_reset_runtime_clears_singleton(monkeypatch):
    runtime.reset_runtime()
    n = {"i": 0}

    def fake_build(**kw):
        n["i"] += 1
        return object()

    monkeypatch.setattr(runtime, "build_runtime", fake_build)
    runtime.get_runtime()
    runtime.reset_runtime()
    runtime.get_runtime()
    assert n["i"] == 2  # reset 后重新构造
    runtime.reset_runtime()


def test_ask_delegates_to_run_query_with_runtime(monkeypatch):
    """ask 把 runtime 的四个组件 + config 原样传给 run_query。"""
    from panwen.agent.types import AgentResult
    from panwen.agent import config

    rt = runtime.Runtime(conn="CONN", backend="BE", rag="RAG", fewshot="FS")
    captured = {}

    def fake_run_query(question, conn, backend, rag, fewshot, config):
        captured.update(question=question, conn=conn, backend=backend,
                        rag=rag, fewshot=fewshot, config=config)
        return AgentResult(status="answered", sql="SELECT 1", rows=[{"a": 1}],
                           reply=None, explanation=None, trace=[])

    monkeypatch.setattr(runtime, "run_query", fake_run_query)
    cfg = config.AgentConfig()
    res = runtime.ask("茅台ROE", cfg, runtime=rt)
    assert captured["conn"] == "CONN" and captured["backend"] == "BE"
    assert captured["rag"] == "RAG" and captured["fewshot"] == "FS"
    assert captured["config"] is cfg
    assert res.status == "answered"


def test_build_runtime_wires_components_with_fake_embedder(monkeypatch, tmp_path):
    """集成：FakeEmbedder + dummy key + 真实 eval.duckdb 只读，组件齐备、不抛。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "dummy-for-test")
    rt = runtime.build_runtime(db_path="data/eval.duckdb",
                               embedder=FakeEmbedder(dim=8),
                               cache_dir=str(tmp_path / "cache"))
    assert rt.backend is not None
    assert rt.rag is not None and rt.fewshot is not None
    assert rt.conn is not None
