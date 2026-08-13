"""Task 1: OpenAICompatBackend —— 消息装配 + 结构化解析，mock openai 客户端。

注意：brief 原版的 _fake_openai / _Spy 把 choices 写成「带 __getitem__ 的内嵌类」，
但 resp.choices[0] 在类对象上会走 metaclass(type)，而 type 无 __getitem__，
会抛 TypeError。这里改写为忠实的 SDK 形状(choices 是 list)，断言不削弱反增强。
"""
import pytest
from panwen.agent import backend as B
from panwen.agent.types import Message, ChatResult


def _make_resp(content="{}", tool_calls=None):
    """构造一个 OpenAI SDK ChatCompletion-like 响应对象。

    忠实点：choices 是 list(真 SDK 就是 list[Choice])，message 有 content/tool_calls，
    resp 有 model_dump() -> dict。backend.py 访问 resp.choices[0].message 与
    getattr(resp, "model_dump", lambda: {})() 均能命中。
    """
    msg = type("Msg", (), {"content": content, "tool_calls": tool_calls})()
    choice = type("Choice", (), {"message": msg})()
    return type("Resp", (), {
        "choices": [choice],
        "model_dump": lambda self: {"role": "assistant", "content": content},
    })()


def _fake_client(return_content: str, captured: dict | None = None):
    """造一个假的 OpenAI 客户端：chat.completions.create 返回固定 content。

    若提供 captured，则把 create 收到的 kwargs 灌进去(用于断言消息装配/透传)。
    """
    class _Completions:
        def create(self, **kw):
            if captured is not None:
                captured.update(kw)
            return _make_resp(content=return_content)
    class _Chat:
        completions = _Completions()
    class _Client:
        chat = _Chat()
    return _Client()


def test_chat_assembles_messages_and_returns_content(mocker):
    captured = {}
    be = B.OpenAICompatBackend(api_key="x", base_url="https://api.deepseek.com",
                               model="deepseek-chat")
    be.client = _fake_client('{"sql":"SELECT 1"}', captured)
    msgs = [Message(role="system", content="s"), Message(role="user", content="u")]
    cr = be.chat(msgs)
    # (a) messages 装配为 [{"role","content"}]
    assert captured["messages"] == [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "u"},
    ]
    # (c) 返回 ChatResult(content, tool_calls, raw)
    assert isinstance(cr, ChatResult)
    assert cr.content == '{"sql":"SELECT 1"}'
    assert isinstance(cr.tool_calls, list)
    assert isinstance(cr.raw, dict)


def test_chat_response_format_passed_through(mocker):
    be = B.OpenAICompatBackend(api_key="x", base_url="https://api.deepseek.com",
                               model="m")
    captured = {}
    be.client = _fake_client("{}", captured)
    be.chat([Message(role="user", content="hi")],
            response_format={"type": "json_object"}, temperature=0.0)
    # (b) response_format / temperature / model 透传
    assert captured.get("response_format") == {"type": "json_object"}
    assert captured.get("temperature") == 0.0
    assert captured.get("model") == "m"


def test_make_backend_reads_env_deepseek(mocker):
    mocker.patch.dict("os.environ", {"DEEPSEEK_API_KEY": "sk-test"})
    be = B.make_backend("deepseek")
    assert be.model == "deepseek-chat"
    assert "deepseek.com" in be.base_url


def test_make_backend_missing_key_raises(mocker):
    mocker.patch.dict("os.environ", {}, clear=True)
    with pytest.raises(B.BackendConfigError):
        B.make_backend("deepseek")
