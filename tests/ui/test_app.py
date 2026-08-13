import pandas as pd
import pytest
from panwen.ui import app, runtime
from panwen.agent.types import AgentResult, Explanation, TraceStep


def _fake_answered(**over):
    base = dict(status="answered", sql="SELECT 1", rows=[{"a": 1}],
                reply=None, explanation=Explanation([], 0.9, "ok"),
                trace=[TraceStep("x", True, "y")])
    base.update(over)
    return AgentResult(**base)


def test_handle_query_renders_answered(monkeypatch):
    monkeypatch.setattr(runtime, "ask", lambda q, c, runtime=None: _fake_answered())
    sql, table, expl, trace, reply = app.handle_query("q", True, True, True, 5)
    assert "SELECT 1" in sql
    assert list(table.columns) == ["a"] and table.iloc[0]["a"] == 1
    assert "90%" in expl
    assert trace == [["x", "✓", "y", ""]]
    assert reply == ""


def test_handle_query_empty_question():
    sql, table, expl, trace, reply = app.handle_query("   ", True, True, True, 5)
    assert reply == "请输入问句。"
    assert table.empty


def test_handle_query_propagates_config_toggles(monkeypatch):
    seen = {}

    def fake_ask(q, c, runtime=None):
        seen["cfg"] = c
        return _fake_answered()

    monkeypatch.setattr(runtime, "ask", fake_ask)
    app.handle_query("q", use_fewshot=False, use_validsql=False, use_selfcorrect=False, schema_topk=7)
    assert seen["cfg"].use_fewshot is False and seen["cfg"].use_validsql is False
    assert seen["cfg"].use_selfcorrect is False and seen["cfg"].schema_topk == 7


def test_handle_query_backend_error_is_captured(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("no api key")
    monkeypatch.setattr(runtime, "ask", boom)
    sql, table, expl, trace, reply = app.handle_query("q", True, True, True, 5)
    assert "后端错误" in reply


def test_build_app_returns_blocks():
    gr = __import__("pytest").importorskip("gradio")
    demo = app.build_app()
    assert isinstance(demo, gr.Blocks)
