"""AgentConfig —— ablation 开关 + 预算 + 检索 k（spec §2/§9）。frozen。"""
from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class AgentConfig:
    use_plan: bool = True
    use_fewshot: bool = True
    use_validsql: bool = True
    use_selfcorrect: bool = True
    selfcorrect_budget: int = 3
    fewshot_k: int = 3
    schema_topk: int = 5
    exec_timeout_s: int = 30
    cartesian_row_warn: int = 10_000
