"""AgentBackend —— OpenAI 兼容后端(DeepSeek + GLM 同接口)。

复用 ggb-fable 的「Backend 注入」：chat() 接受 list[Message]，返回 ChatResult。
不实现自主工具循环(那是 loop.py 的职责)。
"""
from __future__ import annotations
import os
from typing import Protocol
from openai import OpenAI

from panwen.agent.types import Message, ChatResult

# provider → (env var, base_url, model)
_PROVIDERS = {
    "deepseek": ("DEEPSEEK_API_KEY", "https://api.deepseek.com", "deepseek-chat"),
    "glm":      ("GLM_API_KEY", "https://open.bigmodel.cn/api/paas/v4", "glm-4.6"),
}


class BackendConfigError(RuntimeError):
    pass


class AgentBackend(Protocol):
    def chat(self, messages: list[Message], *, tools: list | None = None,
             temperature: float = 0.0, response_format: dict | None = None,
             model: str | None = None) -> ChatResult: ...


class OpenAICompatBackend:
    """DeepSeek 与 GLM 均兼容 OpenAI Chat Completions API，一个类覆盖。"""

    def __init__(self, api_key: str, base_url: str, model: str):
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.base_url = base_url
        self.model = model

    def chat(self, messages: list[Message], *, tools: list | None = None,
             temperature: float = 0.0, response_format: dict | None = None,
             model: str | None = None) -> ChatResult:
        payload = {
            "model": model or self.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": temperature,
        }
        if response_format is not None:
            payload["response_format"] = response_format
        if tools is not None:
            payload["tools"] = tools
        resp = self.client.chat.completions.create(**payload)
        msg = resp.choices[0].message
        return ChatResult(
            content=msg.content or "",
            tool_calls=getattr(msg, "tool_calls", None) or [],
            raw=getattr(resp, "model_dump", lambda: {})(),
        )


def make_backend(provider: str = "deepseek") -> AgentBackend:
    """从环境变量读 key(trial 模式)。"""
    if provider not in _PROVIDERS:
        raise BackendConfigError(f"unknown provider: {provider}")
    env_var, base_url, model = _PROVIDERS[provider]
    api_key = os.getenv(env_var)
    if not api_key:
        raise BackendConfigError(f"missing env {env_var} for provider '{provider}'")
    return OpenAICompatBackend(api_key=api_key, base_url=base_url, model=model)
