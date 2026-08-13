# panwen/agent/agent_loop.py
from __future__ import annotations
from dataclasses import dataclass, field
from panwen.agent.types import Message, TraceStep
from panwen.agent.config import AgentConfig
from panwen.agent.session import SessionStore, _window
from panwen.agent.tools import narrow, query_database
from panwen.agent.tools.schemas import TOOLS_SCHEMA
from panwen.agent.tools.types import ToolResult, TableResult, Source

SYSTEM_PROMPT = (
    "你是「盘问」，A 股结构化数据分析 agent（行情/财务/板块/资金面/宏观）。\n"
    "- 拆解：宽意图（如「所有信息」）拆成多个切面，各选最合适 tool。\n"
    "- 选 tool：切面命中窄 tool 优先用窄 tool（零幻觉）；任意自然语言用 query_database。\n"
    "- 综合：多切面 → 分节多表答复；每个事实标 source；陈述假设；不确定就说明。\n"
    "- 拒答/澄清：非金融/不可查（交易、预测涨跌）礼貌拒；缺关键信息（哪只股/时间窗）先问。"
)

def _build_dispatch(conn, backend, rag, fewshot, config):
    qd = query_database.make_query_database(conn, backend, rag, fewshot, config)
    def dispatch(name, inp):
        if name == "get_stock_profile": return narrow.get_stock_profile(conn, inp["code"])
        if name == "get_financials":    return narrow.get_financials(conn, inp["code"], inp.get("report_date"))
        if name == "get_recent_quotes": return narrow.get_recent_quotes(conn, inp["code"], inp.get("days", 30))
        if name == "get_performance":   return narrow.get_performance(conn, inp["code"])
        if name == "query_database":    return qd(inp["question"])
        return ToolResult(False, f"未知 tool: {name}", Source(kind="none"))
    return dispatch

@dataclass
class AgentRun:
    status: str = "answered"
    synthesis: str = ""
    tables: list[TableResult] = field(default_factory=list)
    sources: list[Source] = field(default_factory=list)
    trace: list[TraceStep] = field(default_factory=list)
    turns: int = 0

def run_agent(question, session_id, conn, backend, rag, fewshot, config: AgentConfig,
              store: SessionStore) -> AgentRun:
    store._system = store._system or SYSTEM_PROMPT
    dispatch = _build_dispatch(conn, backend, rag, fewshot, config)
    session = store.get_or_create(session_id)
    session.messages.append(Message("user", question))
    _window(session, config.session_history_turns)
    tables, sources, trace = [], [], []
    turns = 0
    while turns < config.agent_max_turns:
        resp = backend.chat(session.messages, tools=TOOLS_SCHEMA, system=store._system, temperature=0.0)
        session.messages.append(Message("assistant", resp.content_blocks, tool_calls=resp.tool_calls))
        if not resp.tool_calls:
            return AgentRun("answered", resp.content, tables, _dedup(sources), trace, turns)
        for tc in resp.tool_calls:
            tr = dispatch(tc["name"], tc["input"])
            content = [{"type": "tool_result", "tool_use_id": tc["id"],
                        "content": _serialize(tr)}]
            session.messages.append(Message("user", content))
            if tr.source and tr.source.kind != "none":
                sources.append(tr.source)
                if isinstance(tr.data, list):
                    tables.append(TableResult(title=tc["name"], rows=tr.data, source=tr.source))
            trace.append(TraceStep(tc["name"], tr.ok, str(tr.data)[:80]))
        turns += 1
    return AgentRun("answered", "(已达最大轮次)", tables, _dedup(sources), trace, turns)

def _serialize(tr: ToolResult) -> str:
    import json
    return json.dumps(tr.data, ensure_ascii=False, default=str)[:4000]

def _dedup(srcs):
    seen, out = set(), []
    for s in srcs:
        k = (s.kind, s.table, s.sql)
        if k not in seen: seen.add(k); out.append(s)
    return out
