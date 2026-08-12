"""Task 6: ① normalize —— 规则解析 + LLM 实体/意图(用固定响应 mock)。"""
import json
from panwen.agent import normalize as nz
from panwen.agent.types import Message


class _StubBackend:
    """固定返回 intent/entities JSON 的假后端。"""
    def __init__(self, payload: dict):
        self._payload = payload
    def chat(self, messages, **kw):
        from panwen.agent.types import ChatResult
        return ChatResult(content=json.dumps(self._payload, ensure_ascii=False),
                          tool_calls=[], raw={})


def test_rule_parses_date_range_and_topk():
    be = _StubBackend({"intent": "sql_answerable", "entities": {"code": "600519"}})
    n = nz.normalize("茅台近三年的ROE", be)
    assert n.intent == "sql_answerable"
    assert n.date_range is not None   # 规则解出「近三年」
    assert n.entities.get("code") == "600519"


def test_rule_parses_topk_and_order():
    be = _StubBackend({"intent": "sql_answerable", "entities": {}})
    n = nz.normalize("ROE 最高的前五只股票", be)
    assert n.top_k == 5 and n.order == "desc"


def test_intent_out_of_scope_from_llm():
    be = _StubBackend({"intent": "out_of_scope", "entities": {}})
    n = nz.normalize("帮我写排序代码", be)
    assert n.intent == "out_of_scope"


def test_intent_needs_clarify_from_llm():
    be = _StubBackend({"intent": "needs_clarify", "entities": {}})
    n = nz.normalize("这只股的ROE", be)
    assert n.intent == "needs_clarify"
