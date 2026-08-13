"""AgentResult → Gradio 可渲染结构（纯函数，无 Gradio 依赖，最好测）。"""
from __future__ import annotations
from panwen.agent.types import AgentResult


def result_table(result: AgentResult) -> tuple[list[str], list[list]]:
    """(headers, rows) 供 gr.DataFrame。rows 为空/None 时返回 ([], [])。"""
    rows = result.rows or []
    if not rows:
        return [], []
    headers = list(rows[0].keys())
    return headers, [[r.get(h) for h in headers] for r in rows]


def sql_block(result: AgentResult) -> str:
    """SQL markdown 代码块；result.sql 为 None/空时返回 ''。"""
    if not result.sql:
        return ""
    return f"```sql\n{result.sql}\n```"


def trace_rows(result: AgentResult) -> list[list]:
    """[[stage, '✓'|'✗', detail, rootCause_or_''], ...]，顺序同 result.trace。"""
    return [[t.stage, "✓" if t.ok else "✗", t.detail, t.rootCause or ""]
            for t in result.trace]


def explanation_md(result: AgentResult) -> str:
    """置信度 + 假设 + summary；explanation 为 None 时返回 ''。"""
    e = result.explanation
    if e is None:
        return ""
    lines = [f"**置信度 {e.confidence:.0%}**"]
    if e.assumptions:
        lines.append("假设：" + "；".join(f"（{i+1}）{a}" for i, a in enumerate(e.assumptions)))
    if e.summary:
        lines.append(e.summary)
    return "\n\n".join(lines)


def status_reply(result: AgentResult) -> str:
    """status != 'answered' 返回 result.reply；answered 返回 ''（失败步 rootCause 由 trace_rows 展示）。"""
    if result.status == "answered":
        return ""
    return result.reply or ""
