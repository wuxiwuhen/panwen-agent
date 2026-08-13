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
    gr = pytest.importorskip("gradio")
    demo = app.build_app()
    assert isinstance(demo, gr.Blocks)


# --- Task 9: render AgentRun → 多表 markdown ---
from panwen.ui.render import render_agent_run  # noqa: E402
from panwen.agent.agent_loop import AgentRun  # noqa: E402
from panwen.agent.tools.types import TableResult, Source  # noqa: E402


def test_render_agent_run_multi_tables():
    ar = AgentRun(synthesis="茅台概览如下。",
                  tables=[TableResult("基本信息", [{"name": "茅台"}], Source("duckdb", "stock_basic")),
                          TableResult("最新财务", [{"revenue": 1e9}], Source("duckdb", "income_statement"))],
                  sources=[Source("duckdb", "stock_basic")])
    md = render_agent_run(ar)
    assert "基本信息" in md and "最新财务" in md and "茅台概览" in md


def test_render_agent_run_includes_trace():
    # 多轮 Agent 必须把 trace(每步 tool 名 + ✓/✗ + 数据预览/归因) 渲染出来,
    # 否则用户看不到 agent loop 过程, 无法核验。无 trace 时不出现该小节。
    ar = AgentRun(
        synthesis="信维通信概览。",
        tables=[],
        sources=[],
        trace=[TraceStep("get_stock_profile", True, '[{"name":"信维通信"}]'),
               TraceStep("get_financials", False, "无数据", rootCause="ROOT_EMPTY")],
        turns=1,
    )
    md = render_agent_run(ar)
    assert "Agent 推理轨迹" in md
    assert "get_stock_profile" in md and "get_financials" in md
    assert "✓" in md and "✗" in md
    # 无 trace 的 AgentRun 不应出现轨迹小节
    assert "Agent 推理轨迹" not in render_agent_run(AgentRun(synthesis="x"))
