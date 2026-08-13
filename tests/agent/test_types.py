"""Task 1: Agent 数据契约。"""
from panwen.agent import types as T


def test_agent_result_status_enum():
    r = T.AgentResult(status="out_of_scope", sql=None, rows=None,
                      reply="超出范围", explanation=None, trace=[])
    assert r.status == "out_of_scope" and r.sql is None


def test_norm_query_carries_intent():
    n = T.NormQuery(question="茅台近三年ROE", date_range=("2023-01-01", "2026-03-31"),
                    top_k=None, order=None, entities={"code": "600519"},
                    intent="sql_answerable")
    assert n.intent == "sql_answerable"
    assert n.entities["code"] == "600519"


def test_tracestep_defaults():
    s = T.TraceStep(stage="validate", ok=True, detail="6 checks pass")
    assert s.rootCause is None  # 默认 None


def test_chatresult_holds_raw():
    cr = T.ChatResult(content='{"sql":"SELECT 1"}', tool_calls=[], raw={"x": 1})
    assert cr.raw["x"] == 1


# --- Task 1: Message/ChatResult 演进（向后兼容） ---
from panwen.agent.types import Message, ChatResult


def test_message_accepts_block_list():
    m = Message(role="assistant", content=[{"type": "text", "text": "hi"}])
    assert isinstance(m.content, list)


def test_chatresult_new_fields_default():
    # 旧式构造（无新字段）必须仍可用 —— 保护 _ScriptedBackend 等现有 mock
    r = ChatResult(content="x", tool_calls=[], raw={})
    assert r.content_blocks == []
    assert r.stop_reason is None


def test_chatresult_carries_blocks():
    r = ChatResult(content="x", tool_calls=[{"id": "1", "name": "f", "input": {}}],
                   content_blocks=[{"type": "tool_use", "id": "1"}], stop_reason="tool_use")
    assert r.content_blocks and r.stop_reason == "tool_use"
