"""① normalize —— 规则(日期/单位/top-k) + LLM(实体/意图) 混合(spec §5 ①)。

意图分类折叠进同一次 LLM 调用(零额外成本)。
"""
from __future__ import annotations
import re
from pathlib import Path

from panwen.agent.backend import AgentBackend
from panwen.agent.types import NormQuery

# Bug-fix 1: parents[1] = 包根 panwen/(prompts/ 在此)；brief 里的 parents[2] 指向 repo 根，会 FileNotFoundError。
_PROMPT = (Path(__file__).resolve().parents[1] / "prompts" / "v1" / "normalize.txt").read_text(encoding="utf-8")

# 冻结数据的 as-of 年份(Task 0：eval.duckdb 截至 2026-06-30)。
_FROZEN_YEAR = 2026
_FROZEN_END = f"{_FROZEN_YEAR}-06-30"


# --- 中文数字 → int (Bug-fix 2: 原 regex 只认阿拉伯数字，无法匹配「三年」「前五」) ---
_CN_DIGITS = {"零": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
              "六": 6, "七": 7, "八": 8, "九": 9}


def _cn_to_int(s: str) -> int | None:
    """中文数字→int (五/十/十五/二十/三十二)；阿拉伯数字直通；不可解析返回 None。"""
    if not s:
        return None
    if s.isdigit():
        return int(s)
    if not all(c in _CN_DIGITS or c == "十" for c in s):
        return None
    if "十" in s:
        left, _, right = s.partition("十")
        tens = _CN_DIGITS.get(left, 1) if left else 1
        ones = _CN_DIGITS.get(right, 0) if right else 0
        return tens * 10 + ones
    return _CN_DIGITS.get(s) if len(s) == 1 else None


# --- 规则层 ---
def _parse_date_range(q: str) -> tuple[str, str] | None:
    # Bug-fix 2: 字符类 [一二三四五六七八九十\d]+ 同时认中文与阿拉伯数字。
    # Bug-fix 3: 用 int 数学(_FROZEN_YEAR - n)，brief 里 f"{'2026'-int(...)}" 是 str-int TypeError。
    m = re.search(r"近(?:期|几)?([一二三四五六七八九十\d]+)\s*年", q)
    if m:
        n = _cn_to_int(m.group(1))
        if n:
            start = _FROZEN_YEAR - n
            return (f"{start}-01-01", _FROZEN_END)
    if "最近一年" in q or "近一年" in q:
        return (f"{_FROZEN_YEAR - 1}-01-01", _FROZEN_END)
    return None


def _parse_topk(q: str) -> tuple[int | None, str | None]:
    # Bug-fix 2: 同样接纳中文数字「前五」「前十」。
    m = re.search(r"(?:前|top\s*)([一二三四五六七八九十\d]+)", q, re.IGNORECASE)
    if m:
        k = _cn_to_int(m.group(1))
        if k:
            order = "desc" if re.search(r"最高|最大|最多", q) else ("asc" if re.search(r"最低|最小|最少", q) else "desc")
            return k, order
    return None, None


# --- LLM 层 ---
_NORM_TOOL = {
    "name": "emit_norm",
    "description": "输出对用户问题的结构化理解",
    "input_schema": {
        "type": "object",
        "properties": {
            "intent": {"type": "string", "enum": ["sql_answerable", "needs_clarify", "out_of_scope"]},
            "entities": {"type": "object"},
            "date_range": {"type": ["array", "null"], "items": {"type": "string"}},
            "top_k": {"type": ["integer", "null"]},
            "order": {"type": ["string", "null"], "enum": ["asc", "desc", None]},
            "question": {"type": "string"},
        },
        "required": ["intent", "entities", "question"],
    },
}


def _llm_understand(question: str, backend: AgentBackend) -> dict:
    from panwen.agent.types import Message
    resp = backend.chat(
        [Message(role="system", content=_PROMPT), Message(role="user", content=question)],
        tools=[_NORM_TOOL], tool_choice={"type": "tool", "name": "emit_norm"}, temperature=0.0)
    if resp.tool_calls:
        return resp.tool_calls[0]["input"]
    return {"intent": "needs_clarify", "entities": {}}   # 无 tool_use → 安全降级


def normalize(question: str, backend: AgentBackend) -> NormQuery:
    dr = _parse_date_range(question)
    topk, order = _parse_topk(question)
    llm = _llm_understand(question, backend)
    intent = llm.get("intent", "needs_clarify")
    if intent not in {"sql_answerable", "needs_clarify", "out_of_scope"}:
        intent = "needs_clarify"
    return NormQuery(
        question=question, date_range=dr, top_k=topk, order=order,
        entities=llm.get("entities", {}), intent=intent,
    )
