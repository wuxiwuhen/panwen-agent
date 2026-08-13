"""UI toggle 布尔值 → AgentConfig。use_plan 恒 True（plan+generate fused always-on，非 toggle）。"""
from __future__ import annotations
from panwen.agent.config import AgentConfig


def to_config(use_fewshot: bool, use_validsql: bool, use_selfcorrect: bool,
              schema_topk: int | None = None) -> AgentConfig:
    """从 UI toggle 构造 AgentConfig。schema_topk 为 None 时取 AgentConfig 默认(5)。"""
    kwargs = dict(use_fewshot=use_fewshot, use_validsql=use_validsql,
                  use_selfcorrect=use_selfcorrect, use_plan=True)
    if schema_topk is not None:
        kwargs["schema_topk"] = schema_topk
    return AgentConfig(**kwargs)
