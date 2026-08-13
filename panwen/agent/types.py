"""Agent 数据契约（spec §9）。所有结构是 dataclass，无业务逻辑。"""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Message:
    role: str                       # "system" | "user" | "assistant"
    content: str | list[dict] | None = None
    tool_calls: list | None = None


@dataclass
class ChatResult:
    content: str                    # LLM 原始文本(可能含 JSON)
    tool_calls: list
    content_blocks: list = field(default_factory=list)   # 原始 anthropic content 块, 回填多轮历史用
    stop_reason: str | None = None                       # "tool_use" | "end_turn" | ...
    raw: dict = field(default_factory=dict)              # 透传 provider 原始响应片段


@dataclass
class Explanation:
    assumptions: list[str]
    confidence: float               # 0.0 .. 1.0
    summary: str


@dataclass
class TraceStep:
    stage: str                      # "normalize"|"dispatch"|"rag"|"generate"|"validate"|"execute"|"selfcorrect"|"explain"
    ok: bool
    detail: str
    rootCause: str | None = None    # 失败时归因码(ROOT_UNKNOWN_COL 等)


@dataclass
class AgentResult:
    status: str                     # "answered" | "clarified" | "out_of_scope" | "failed"
    sql: str | None
    rows: list[dict] | None
    reply: str | None               # status != "answered" 时的非 SQL 回复
    explanation: Explanation | None # status == "answered" 时非空
    trace: list[TraceStep] = field(default_factory=list)


@dataclass(frozen=True)
class NormQuery:
    """① normalize 产出。"""
    question: str
    date_range: tuple[str, str] | None
    top_k: int | None
    order: str | None               # "asc" | "desc" | None
    entities: dict                  # {"code":"600519","board":"白酒",...}
    intent: str                     # "sql_answerable"|"needs_clarify"|"out_of_scope"
