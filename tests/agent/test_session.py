# tests/agent/test_session.py
from panwen.agent.session import SessionStore, _window, Session
from panwen.agent.types import Message

def test_get_or_create_seeds_system():
    s = SessionStore()
    sess = s.get_or_create("s1")
    assert sess.messages[0].role == "system"           # 创建时种子 system

def test_append_and_persist_across_calls():
    s = SessionStore(); s.append("s1", Message("user", "hi"))
    assert s.get_or_create("s1").messages[-1].content == "hi"

def test_window_drops_oldest_whole_turns_keeps_system():
    # system + 8 轮(user/assistant 对)，keep 6 → 保留 system + 最近 6 轮，丢最旧 2 轮
    sess = Session(sid="s", messages=[Message("system", "S")], created_at="t")
    for i in range(8):
        sess.messages.append(Message("user", f"u{i}"))
        sess.messages.append(Message("assistant", f"a{i}"))
    _window(sess, keep_turns=6)
    contents = [m.content for m in sess.messages]
    assert sess.messages[0].role == "system"          # system 始终保留
    assert "u0" not in contents and "a0" not in contents   # 最旧 2 轮被丢
    assert "u2" in contents and "a7" in contents       # 最近 6 轮保留
    assert contents[-1] == "a7"

def test_window_keeps_tool_results_with_their_assistant():
    # 回归守卫: tool_result(role=user) 必须与归属的 assistant(tool_use) 同轮。
    # 让含 tool_use→tool_result 对的轮【留在窗口里】(keep_turns=2)，再断言
    # 窗口内每个 tool_result 都有其匹配的 tool_use —— 否则 naive splitter 会让
    # tool_result 因 role=user 被拆进新轮、其 tool_use 被裁掉，留下孤儿 tool_result。
    # 注意: 检测器必须【独立内联】，不能复用被测函数 _is_tool_result —— 否则
    # 把 _is_tool_result 改坏会同时破坏 _window 分组与这里的检测，使断言空洞。
    msgs = [
        Message("system", "S"),
        Message("user", "q1"),
        Message("assistant", None,
                tool_calls=[{"type": "tool_use", "id": "tu1", "name": "x", "input": {}}]),
        Message("user", [{"type": "tool_result", "tool_use_id": "tu1", "content": "r"}]),
        Message("assistant", "text1"),
        Message("user", "q2"),
        Message("assistant", "text2"),
    ]
    sess = Session(sid="s", created_at="", messages=msgs)
    _window(sess, keep_turns=2)
    kept = sess.messages
    # 独立内联检测: 不依赖 session._is_tool_result
    use_ids = {b["id"] for m in kept if m.role == "assistant" and m.tool_calls
               for b in m.tool_calls if isinstance(b, dict) and b.get("type") == "tool_use"}
    result_ids = {b["tool_use_id"] for m in kept if isinstance(m.content, list)
                  for b in m.content
                  if isinstance(b, dict) and b.get("type") == "tool_result"}
    # 不变式: 窗口内每个 tool_result 必须有其匹配的 tool_use 也在窗口内(无孤儿)
    assert result_ids <= use_ids


def test_window_keep_zero_keeps_only_system():
    # 回归: turns[-0:]==turns[0:]==全部 → keep_turns=0 旧实现会保留全部轮次。
    # 正确语义: keep_turns=0 仅保留 system 消息, 丢弃所有会话轮次。
    sess = Session(sid="s", messages=[Message("system", "S")], created_at="t")
    for i in range(3):
        sess.messages.append(Message("user", f"u{i}"))
        sess.messages.append(Message("assistant", f"a{i}"))
    _window(sess, keep_turns=0)
    assert len(sess.messages) == 1
    assert sess.messages[0].role == "system"
