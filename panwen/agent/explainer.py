"""⑨ explainer —— LLM 出 Explanation{assumptions,confidence,summary}。"""
from __future__ import annotations
import json
from pathlib import Path

from panwen.agent.backend import AgentBackend
from panwen.agent.types import Explanation, Message

# Directive 1: parents[1] = panwen/(prompts/ 在此)；brief 的 parents[2] 指向 repo 根 → FileNotFoundError。
_PROMPT = (Path(__file__).resolve().parents[1] / "prompts" / "v1" / "explain.txt").read_text(encoding="utf-8")


def explain(question: str, sql: str | None, rows: list | None,
            low_confidence: bool, backend: AgentBackend) -> Explanation:
    ctx = f"问题: {question}\nSQL: {sql}\n结果行数: {len(rows) if rows else 0}"
    try:
        resp = backend.chat(
            [Message(role="system", content=_PROMPT), Message(role="user", content=ctx)],
            temperature=0.0, response_format={"type": "json_object"})
        d = json.loads(resp.content)
    except Exception:
        d = {"assumptions": [], "confidence": 0.0, "summary": "解释生成失败"}
    conf = float(d.get("confidence", 0.0))
    if low_confidence:
        conf = min(conf, 0.5)
    return Explanation(assumptions=list(d.get("assumptions", [])),
                       confidence=conf, summary=str(d.get("summary", "")))
