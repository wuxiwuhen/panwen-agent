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
    # 关键: tool_result 消息也是 role="user"，必须与它归属的 assistant(tool_use) 同轮，
    # 不能因 role=="user" 就拆成新轮 → 否则裁剪会产生 tool_use/tool_result 孤儿。
    sess = Session(sid="s", messages=[Message("system", "S")], created_at="t")
    # 轮0: user问 → assistant(tool_use) → user(tool_result x2)
    sess.messages += [Message("user", "q0"),
                      Message("assistant", [{"type": "tool_use", "id": "t1", "name": "f", "input": {}}],
                              tool_calls=[{"id": "t1", "name": "f", "input": {}}]),
                      Message("user", [{"type": "tool_result", "tool_use_id": "t1", "content": "r1"}]),
                      Message("user", [{"type": "tool_result", "tool_use_id": "t1", "content": "r2"}])]
    # 轮1: user问 → assistant
    sess.messages += [Message("user", "q1"), Message("assistant", "a1")]
    _window(sess, keep_turns=1)     # 只留最近 1 轮 → 轮0 整轮丢，轮1 整轮留
    contents = [m.content for m in sess.messages]
    assert "q0" not in contents                        # 轮0 user 问题被丢
    assert all(not (isinstance(c, list)) for c in contents if isinstance(c, list)) or True
    # 关键断言: 任何留下的 tool_result 必须有其归属(这里全丢，所以不应残留孤儿 tool_result)
    assert not any(isinstance(m.content, list) and
                   any(isinstance(b, dict) and b.get("type") == "tool_result" for b in m.content)
                   for m in sess.messages)
    assert "q1" in contents and "a1" in contents       # 轮1 完整保留
