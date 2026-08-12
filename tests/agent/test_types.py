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
