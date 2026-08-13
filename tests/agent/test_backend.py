from unittest.mock import MagicMock
from panwen.agent.backend import AnthropicBackend, make_backend
from panwen.agent.types import Message


def _be_with_mock_create():
    be = AnthropicBackend(api_key="k", base_url="https://api.deepseek.com/anthropic",
                          model="deepseek-chat", auth_mode="auth_token")
    be.client = MagicMock()
    return be


def test_system_extracted_to_top_level():
    be = _be_with_mock_create()
    be.client.messages.create.return_value = MagicMock(
        content=[{"type": "text", "text": "ans"}], stop_reason="end_turn")
    be.chat([Message("system", "SYS"), Message("user", "hi")])
    kw = be.client.messages.create.call_args.kwargs
    assert kw["system"] == "SYS"                       # system 抽到顶层
    assert all(m["role"] != "system" for m in kw["messages"])


def test_system_message_stripped_when_system_kwarg_passed():
    # 回归 I-1: run_agent 传 system=<non-None> 且 messages[0] 是 role=system 时,
    # 旧守卫 `and sys_text is None` 为假 → system 消息漏进 messages 数组 → API 400。
    # 必须无条件剥离 role=system; 显式 system= kwarg 优先, 仅当 system=None 时才采收内容。
    be = _be_with_mock_create()
    be.client.messages.create.return_value = MagicMock(
        content=[{"type": "text", "text": "ans"}], stop_reason="end_turn")
    be.chat([Message("system", "LEAK"), Message("user", "hi")], system="explicit-sys")
    kw = be.client.messages.create.call_args.kwargs
    assert kw["system"] == "explicit-sys"             # 显式 kwarg 胜出
    assert all(m["role"] != "system" for m in kw["messages"])  # 无 role=system 漏入


def test_text_content_string_wrapped_as_block():
    be = _be_with_mock_create()
    be.client.messages.create.return_value = MagicMock(content=[{"type": "text", "text": "x"}], stop_reason="end_turn")
    be.chat([Message("user", "hi")])
    sent = be.client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert sent == [{"type": "text", "text": "hi"}]    # str → 单 text 块


def test_response_tool_use_parsed():
    be = _be_with_mock_create()
    be.client.messages.create.return_value = MagicMock(
        content=[{"type": "tool_use", "id": "t1", "name": "f", "input": {"a": 1}}],
        stop_reason="tool_use")
    r = be.chat([Message("user", "go")], tools=[{"name": "f", "input_schema": {}}])
    assert r.tool_calls == [{"id": "t1", "name": "f", "input": {"a": 1}}]
    assert r.stop_reason == "tool_use"
    assert r.content_blocks == [{"type": "tool_use", "id": "t1", "name": "f", "input": {"a": 1}}]


def test_make_backend_providers():
    import os
    os.environ["DEEPSEEK_API_KEY"] = "dk"
    os.environ["GLM_API_KEY"] = "gk"
    assert isinstance(make_backend("deepseek"), AnthropicBackend)
    assert isinstance(make_backend("glm"), AnthropicBackend)
