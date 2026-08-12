"""② dispatch —— 按 intent 确定性三分支(spec §5 ②)。

返回 AgentResult(早退) 或 None(继续 ③-⑨)。
"""
from __future__ import annotations
from pathlib import Path

from panwen.agent.backend import AgentBackend
from panwen.agent.types import NormQuery, AgentResult, Message

# Bug-fix 1: parents[1] = 包根 panwen/(prompts/ 在此)；brief 里的 parents[2] 指向 repo 根，会 FileNotFoundError。
_CLARIFY_PROMPT = (Path(__file__).resolve().parents[1] / "prompts" / "v1" / "clarify.txt").read_text(encoding="utf-8")
_OUT_OF_SCOPE_REPLY = ("这不在我的能力范围（我只能查 A 股结构化数据：行情/财务/板块/资金面/宏观），"
                       "试试问『茅台近三年 ROE』？")


def dispatch(norm: NormQuery, backend: AgentBackend) -> AgentResult | None:
    if norm.intent == "out_of_scope":
        return AgentResult(status="out_of_scope", sql=None, rows=None,
                           reply=_OUT_OF_SCOPE_REPLY, explanation=None, trace=[])
    if norm.intent == "needs_clarify":
        resp = backend.chat(
            [Message(role="system", content=_CLARIFY_PROMPT),
             Message(role="user", content=norm.question)],
            temperature=0.0)
        return AgentResult(status="clarified", sql=None, rows=None,
                           reply=resp.content.strip(), explanation=None, trace=[])
    return None  # sql_answerable → 继续 ③-⑨
