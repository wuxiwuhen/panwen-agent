"""AgentBackend —— Anthropic SDK 原生后端(DeepSeek + GLM 均提供 anthropic 兼容端点)。

chat() 接受 list[Message]，返回 ChatResult。不实现自主工具循环(那是 loop.py 的职责)。
"""
from __future__ import annotations
import os
from typing import Protocol
from anthropic import Anthropic

from panwen.agent.types import Message, ChatResult

# provider → (env var, base_url, model, auth_mode)
_PROVIDERS = {
    "deepseek": ("DEEPSEEK_API_KEY", "https://api.deepseek.com/anthropic", "deepseek-chat", "auth_token"),
    "glm":      ("GLM_API_KEY", "https://api.z.ai/api/anthropic", "glm-4.6", "auth_token"),
}

# anthropic Messages API 必填; 缺省会触发客户端 "Missing required arguments: max_tokens"。
# 4096 对两家的 anthropic 兼容端点都安全(deepseek-chat 输出上限 8192, glm-4.6 更宽)。
DEFAULT_MAX_TOKENS = 4096


class BackendConfigError(RuntimeError): ...


class AgentBackend(Protocol):
    def chat(self, messages, *, tools=None, tool_choice=None, temperature=0.0,
             system=None, model=None, max_tokens=DEFAULT_MAX_TOKENS) -> ChatResult: ...


def _to_content_blocks(msg: Message) -> list[dict]:
    if isinstance(msg.content, list):
        return msg.content
    if msg.content is None:
        return []
    return [{"type": "text", "text": msg.content}]


def _bget(b, name, default=None):
    """Read a field off a content block that may be a dict (mock) or a pydantic
    block object (real anthropic SDK). Robust to both so the same code path
    serves tests and live responses."""
    if isinstance(b, dict):
        return b.get(name, default)
    return getattr(b, name, default)


class AnthropicBackend:
    """DeepSeek 与 GLM 均暴露 Anthropic Messages 兼容端点，直接用 anthropic SDK。"""

    def __init__(self, api_key, base_url, model, auth_mode="api_key"):
        # auth_mode: "api_key"→x-api-key(anthropic原生); "auth_token"→Authorization Bearer(z.ai/DeepSeek)
        if auth_mode == "auth_token":
            self.client = Anthropic(base_url=base_url, auth_token=api_key)
        else:
            self.client = Anthropic(base_url=base_url, api_key=api_key)
        self.model = model

    def chat(self, messages, *, tools=None, tool_choice=None, temperature=0.0,
             system=None, model=None, max_tokens=DEFAULT_MAX_TOKENS) -> ChatResult:
        sys_text = system
        msgs = []
        for m in messages:
            if m.role == "system":
                if sys_text is None:
                    sys_text = m.content or ""
                # else: 显式 system= kwarg 优先; 从 msgs 中丢弃 system 消息
                # (Anthropic Messages API 拒绝 messages 内的 role=system, 400)
            else:
                msgs.append({"role": m.role, "content": _to_content_blocks(m)})
        kw = dict(model=model or self.model, messages=msgs, temperature=temperature,
                  max_tokens=max_tokens)
        if sys_text: kw["system"] = sys_text
        if tools: kw["tools"] = tools
        if tool_choice: kw["tool_choice"] = tool_choice
        resp = self.client.messages.create(**kw)
        blocks = list(resp.content)
        text = "".join(_bget(b, "text", "") for b in blocks if _bget(b, "type") == "text")
        tool_calls = [{"id": _bget(b, "id"), "name": _bget(b, "name"), "input": _bget(b, "input")}
                      for b in blocks if _bget(b, "type") == "tool_use"]
        return ChatResult(content=text, tool_calls=tool_calls, content_blocks=[
            {"type": _bget(b, "type"), **({"text": _bget(b, "text")} if _bget(b, "type") == "text" else
             {"id": _bget(b, "id"), "name": _bget(b, "name"), "input": _bget(b, "input")})}
            for b in blocks],
            stop_reason=getattr(resp, "stop_reason", None),
            raw=getattr(resp, "model_dump", lambda: {})())


def make_backend(provider="deepseek") -> AgentBackend:
    """从环境变量读 key(trial 模式)。"""
    if provider not in _PROVIDERS:
        raise BackendConfigError(f"unknown provider: {provider}")
    env_var, base_url, model, auth_mode = _PROVIDERS[provider]
    api_key = os.getenv(env_var)
    if not api_key:
        raise BackendConfigError(f"missing env {env_var} for provider '{provider}'")
    return AnthropicBackend(api_key=api_key, base_url=base_url, model=model, auth_mode=auth_mode)
