"""Task 6: ② dispatch —— 按 intent 确定性三分支。"""
import json
from panwen.agent import clarify
from panwen.agent.normalize import NormQuery


def _norm(intent):
    return NormQuery(question="x", date_range=None, top_k=None, order=None,
                     entities={}, intent=intent)


def test_out_of_scope_early_exit():
    res = clarify.dispatch(_norm("out_of_scope"), _NoBackend())
    assert res.status == "out_of_scope"
    assert res.sql is None
    assert "不在我的能力范围" in res.reply


def test_needs_clarify_early_exit():
    res = clarify.dispatch(_norm("needs_clarify"), _ClarifyBackend("请说明是哪只股票"))
    assert res.status == "clarified"
    assert res.reply == "请说明是哪只股票"


def test_sql_answerable_returns_none_to_continue():
    res = clarify.dispatch(_norm("sql_answerable"), _NoBackend())
    assert res is None  # 继续走 ③-⑨


class _NoBackend:
    def chat(self, messages, **kw):
        raise AssertionError("sql_answerable/out_of_scope 不应调 LLM")


class _ClarifyBackend:
    def __init__(self, q): self._q = q
    def chat(self, messages, **kw):
        from panwen.agent.types import ChatResult
        return ChatResult(content=self._q, tool_calls=[], raw={})
