# panwen/agent/session.py
from dataclasses import dataclass, field
from panwen.agent.types import Message

SYSTEM_SEED = ""  # 由 agent_loop 注入实际 system prompt（见 Task8）；store 只负责结构

@dataclass
class Session:
    sid: str
    messages: list[Message] = field(default_factory=list)
    created_at: str = ""

class SessionStore:
    def __init__(self, system_prompt: str = ""):
        self._system = system_prompt
        self._sessions: dict[str, Session] = {}
    def get_or_create(self, sid: str) -> Session:
        # 始终种子一条 system 消息：作为稳定锚点(messages[0])，_window 依赖它。
        # (brief 原写法 `[...] if self._system else []` 会使空 system 下 messages 为空，
        #  test_get_or_create_seeds_system 会 IndexError —— 故此处去掉该门控。)
        if sid not in self._sessions:
            self._sessions[sid] = Session(sid=sid, created_at="",
                                          messages=[Message("system", self._system)])
        return self._sessions[sid]
    def append(self, sid: str, msg: Message) -> None:
        self.get_or_create(sid).messages.append(msg)

def _is_tool_result(msg: Message) -> bool:
    """tool_result 回填消息: role='user' + content 是含 tool_result 块的 list。
    这类消息不开启新轮——它归属前一条 assistant(tool_use)。"""
    return (isinstance(msg.content, list) and bool(msg.content)
            and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in msg.content))

def _window(session: Session, keep_turns: int) -> None:
    """整轮裁剪: 保留首条 system + 最近 keep_turns 轮。
    一「轮」= 一条真实 user 输入(非 tool_result)起，到下一条真实 user 输入前。
    tool_result(user 角色)不切轮 → 避免裁剪产生 tool_use/tool_result 孤儿(破坏 API 约定)。"""
    msgs = session.messages
    system = [m for m in msgs if m.role == "system"]
    convo = [m for m in msgs if m.role != "system"]
    turns, cur = [], []
    for m in convo:
        if m.role == "user" and not _is_tool_result(m) and cur:
            turns.append(cur); cur = []    # 真实新问题 → 切轮
        cur.append(m)
    if cur: turns.append(cur)
    if keep_turns == 0:                     # turns[-0:]==turns[0:]==全部; 显式短路仅留 system
        session.messages = system
        return
    kept = turns[-keep_turns:] if keep_turns >= 0 else turns
    session.messages = system + [m for t in kept for m in t]
