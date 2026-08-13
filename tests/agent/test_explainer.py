"""Task 3: ⑨ explainer —— 强制 tool_use 取 Explanation 结构。"""
from panwen.agent import explainer as ex
from panwen.agent.types import ChatResult


class _ToolBackend:
    """固定返回 emit_explain tool_call 的假后端。"""
    def __init__(self, tool_input: dict):
        self.tool_input = tool_input
        self.received = {}
    def chat(self, messages, *, tools=None, tool_choice=None, **kw):
        self.received = {"tools": tools, "tool_choice": tool_choice}
        return ChatResult(content="",
                          tool_calls=[{"id": "1", "name": "emit_explain", "input": self.tool_input}],
                          content_blocks=[], stop_reason="tool_use")


def test_explain_reads_tool_use_input():
    e = ex.explain("茅台ROE", "SELECT roe...", [{"roe": 30.0}], False,
                   _ToolBackend({"assumptions": ["a"], "confidence": 0.9, "summary": "ROE 30%"}))
    assert e.confidence == 0.9 and e.summary == "ROE 30%"
    assert e.assumptions == ["a"]
    assert _ToolBackend.__name__  # sanity
    # 强制 tool_use
    be = _ToolBackend({"assumptions": [], "confidence": 0.5, "summary": "x"})
    ex.explain("q", "SELECT 1", None, False, be)
    assert be.received["tool_choice"] == {"type": "tool", "name": "emit_explain"}


def test_low_confidence_caps_at_half():
    e = ex.explain("x", "SELECT 1", None, True,
                   _ToolBackend({"assumptions": [], "confidence": 0.9, "summary": "s"}))
    assert e.confidence <= 0.5


def test_explain_safe_degrade_on_no_toolcall():
    class _Empty:
        def chat(self, messages, **kw):
            return ChatResult(content="", tool_calls=[], content_blocks=[], stop_reason="end_turn")
    e = ex.explain("x", "SELECT 1", None, False, _Empty())
    assert e.confidence == 0.0 and e.summary == "解释生成失败"
