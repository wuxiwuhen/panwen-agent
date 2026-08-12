"""Task 7: run_query 集成测(mock backend 确定性序列)。覆盖 §11 全分支。"""
import json
import pytest
from panwen.agent import loop, config
from panwen.agent.types import Message, ChatResult
from panwen.data import db, schema
from panwen.rag.embed import FakeEmbedder
from panwen.rag.schema_retriever import SchemaRetriever
from panwen.rag.fewshot_store import FewshotStore


class _ScriptedBackend:
    """按预设脚本依次返回 content。"""
    def __init__(self, scripts: list[str]):
        self.scripts = list(scripts)
        self.calls = 0
    def chat(self, messages, **kw):
        c = self.scripts.pop(0) if self.scripts else "{}"
        self.calls += 1
        return ChatResult(content=c, tool_calls=[], raw={})


def _setup_conn(tmp_path):
    conn = db.connect(str(tmp_path / "t.duckdb"))
    db.init_schema(conn)
    conn.execute("INSERT INTO financial_indicator VALUES ('600519','2025-12-31',30.0,25.0,90.0,45.0,30.0,NULL,NULL)")
    return conn


def _rag():
    return SchemaRetriever(embedder=FakeEmbedder(dim=16), topk=3)


def _fewshot():
    return FewshotStore([], embedder=FakeEmbedder(dim=16), k=2)


def test_out_of_scope_early_exit(tmp_path):
    be = _ScriptedBackend([json.dumps({"intent": "out_of_scope", "entities": {}})])
    res = loop.run_query("写代码", _setup_conn(tmp_path), be, _rag(), _fewshot(), config.AgentConfig())
    assert res.status == "out_of_scope"
    assert be.calls == 1  # 只调了 normalize，没往下走


def test_one_shot_success(tmp_path):
    # normalize(sql_answerable) → generate(出 SQL) → validate 过 → execute 过 → explain
    be = _ScriptedBackend([
        json.dumps({"intent": "sql_answerable", "entities": {"code": "600519"}}),
        json.dumps({"sql": "SELECT roe FROM financial_indicator WHERE code='600519' ORDER BY report_date DESC LIMIT 1"}),
        '{"assumptions":[],"confidence":0.9,"summary":"茅台最新ROE"}',
    ])
    res = loop.run_query("茅台最新ROE", _setup_conn(tmp_path), be, _rag(), _fewshot(), config.AgentConfig())
    assert res.status == "answered"
    assert res.rows is not None and len(res.rows) >= 1
    assert res.explanation is not None


def test_selfcorrect_one_round_success(tmp_path):
    # generate 先给一个不存在的列(被 ValidSQL 拦) → 自纠错给正确 SQL
    be = _ScriptedBackend([
        json.dumps({"intent": "sql_answerable", "entities": {"code": "600519"}}),
        json.dumps({"sql": "SELECT fake_col FROM financial_indicator WHERE code='600519'"}),  # 拦
        json.dumps({"sql": "SELECT roe FROM financial_indicator WHERE code='600519'"}),       # 纠对
        '{"assumptions":[],"confidence":0.7,"summary":"纠错后出结果"}',
    ])
    res = loop.run_query("茅台ROE", _setup_conn(tmp_path), be, _rag(), _fewshot(), config.AgentConfig())
    assert res.status == "answered"


def test_selfcorrect_budget_exhausted(tmp_path):
    # 连续 3 次都给错列 → 用尽预算 → status=answered 但低置信(或 failed)
    bad = json.dumps({"sql": "SELECT fake_col FROM financial_indicator"})
    be = _ScriptedBackend([
        json.dumps({"intent": "sql_answerable", "entities": {}}),
        bad, bad, bad, bad,  # 初次 + 3 轮纠错全错
        '{"assumptions":["未能生成有效SQL"],"confidence":0.1,"summary":"自纠错用尽预算"}',
    ])
    res = loop.run_query("茅台ROE", _setup_conn(tmp_path), be, _rag(), _fewshot(), config.AgentConfig())
    assert res.status in ("answered", "failed")
    assert res.explanation.confidence < 0.5
