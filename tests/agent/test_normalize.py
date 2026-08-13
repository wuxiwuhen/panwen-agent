"""Task 3: ① normalize —— 规则解析 + LLM 实体/意图(强制 tool_use 取结构)。"""
from panwen.agent.normalize import normalize
from panwen.agent.types import ChatResult


class _ToolBackend:
    """固定返回 emit_norm tool_call 的假后端；记录收到的 tools/tool_choice。"""
    def __init__(self, tool_input: dict):
        self.tool_input = tool_input
        self.received = {}
    def chat(self, messages, *, tools=None, tool_choice=None, **kw):
        self.received = {"tools": tools, "tool_choice": tool_choice}
        return ChatResult(content="",
                          tool_calls=[{"id": "1", "name": "emit_norm", "input": self.tool_input}],
                          content_blocks=[], stop_reason="tool_use")


def test_normalize_reads_tool_use_input():
    be = _ToolBackend({"intent": "sql_answerable", "entities": {"code": "600519"},
                       "date_range": None, "top_k": None, "order": None, "question": "茅台ROE"})
    n = normalize("茅台ROE", be)
    assert n.intent == "sql_answerable" and n.entities == {"code": "600519"}
    assert be.received["tool_choice"] == {"type": "tool", "name": "emit_norm"}   # 强制


def test_normalize_safe_degrade_on_no_toolcall():
    class _Empty:
        def chat(self, messages, **kw):
            return ChatResult(content="", tool_calls=[], content_blocks=[], stop_reason="end_turn")
    n = normalize("x", _Empty())
    assert n.intent == "needs_clarify"      # 无 tool_use → 安全降级(同旧 json 解析失败语义)


def test_rule_parses_date_range_and_topk():
    be = _ToolBackend({"intent": "sql_answerable", "entities": {"code": "600519"}})
    n = normalize("茅台近三年的ROE", be)
    assert n.intent == "sql_answerable"
    assert n.date_range is not None   # 规则解出「近三年」
    assert n.entities.get("code") == "600519"


def test_rule_parses_topk_and_order():
    be = _ToolBackend({"intent": "sql_answerable", "entities": {}})
    n = normalize("ROE 最高的前五只股票", be)
    assert n.top_k == 5 and n.order == "desc"


def test_intent_out_of_scope_from_llm():
    be = _ToolBackend({"intent": "out_of_scope", "entities": {}})
    n = normalize("帮我写排序代码", be)
    assert n.intent == "out_of_scope"


def test_intent_needs_clarify_from_llm():
    be = _ToolBackend({"intent": "needs_clarify", "entities": {}})
    n = normalize("这只股的ROE", be)
    assert n.intent == "needs_clarify"
