"""AgentResult / AgentRun → Gradio 可渲染结构（纯函数，无 Gradio 依赖，最好测）。"""
from __future__ import annotations
from panwen.agent.types import AgentResult


def _rows_to_md(rows) -> str:
    """list[dict] → GitHub-markdown 表格。兼容三种实际形态：
    - list[dict]: 按 keys 的并集建表（保持首行字段顺序，后续新字段追加）。
    - [] / None: 空表 → 返回 ""。
    - str: ToolResult.data 的错误/rootCause 兜底字符串 → 原样放入代码块，避免误当表格。
    """
    if not rows:
        return ""
    if isinstance(rows, str):
        return f"```\n{rows}\n```"
    if not isinstance(rows, list):
        # 未知形态：转字符串兜底，绝不崩。
        return f"```\n{rows!r}\n```"
    # 汇总字段：以首行顺序为主，后续行新字段追加（稳定列序）。
    headers: list[str] = []
    for r in rows:
        if isinstance(r, dict):
            for k in r.keys():
                if k not in headers:
                    headers.append(k)
    if not headers:
        return ""
    header_line = "| " + " | ".join(headers) + " |"
    sep_line = "| " + " | ".join("---" for _ in headers) + " |"
    body_lines = []
    for r in rows:
        cells = []
        for h in headers:
            v = r.get(h, "") if isinstance(r, dict) else ""
            cells.append("" if v is None else str(v))
        body_lines.append("| " + " | ".join(cells) + " |")
    return "\n".join([header_line, sep_line, *body_lines])


def _trace_md(ar) -> str:
    """AgentRun.trace → 编号列表：每步 tool 名 + ✓/✗ + 数据预览/归因。
    用于核验 agent loop 过程（调了哪些 tool、成功与否、返回什么）。空 trace 返回 ''。"""
    tr = getattr(ar, "trace", None) or []
    if not tr:
        return ""
    turns = getattr(ar, "turns", 0)
    lines = [f"**Agent 推理轨迹**（{turns} 轮 · {len(tr)} 个 tool）"]
    for i, t in enumerate(tr, 1):
        mark = "✓" if getattr(t, "ok", False) else "✗"
        stage = getattr(t, "stage", "?")
        tail = getattr(t, "rootCause", None) or getattr(t, "detail", "") or ""
        lines.append(f"{i}. `{stage}` {mark}" + (f" — {tail}" if tail else ""))
    return "\n".join(lines)


def render_agent_run(ar) -> str:
    """AgentRun → 多节 markdown：synthesis + 每张表(标题+rows markdown) + 来源溯源 + 推理轨迹。
    纯函数，仅读 ar 的属性，对任意 TableResult.rows 形态不崩（_rows_to_md 兜底）。
    """
    parts = [ar.synthesis] if ar.synthesis else []
    for t in ar.tables:
        parts.append(f"**{t.title}**")
        md = _rows_to_md(t.rows)
        if md:
            parts.append(md)
    if ar.sources:
        parts.append("**来源**: " + ", ".join(
            f"{s.table or s.kind}" for s in ar.sources))
    tr_md = _trace_md(ar)
    if tr_md:
        parts.append(tr_md)
    return "\n\n".join(parts)


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
