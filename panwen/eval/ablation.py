"""逐组件 ablation(spec §8.3) —— 遍历 AgentConfig 开关组合 → 边际贡献表。

数字 make eval 实测填，绝不编造。
"""
from __future__ import annotations
from panwen.agent.config import AgentConfig


def agent_config(use_plan: bool, use_fewshot: bool, use_validsql: bool, use_selfcorrect: bool) -> AgentConfig:
    return AgentConfig(use_plan=use_plan, use_fewshot=use_fewshot,
                       use_validsql=use_validsql, use_selfcorrect=use_selfcorrect)


def config_matrix() -> list[AgentConfig]:
    """§8.3 五行配置(1-shot baseline → 逐组件叠加 → 全开)。"""
    return [
        agent_config(False, False, False, False),  # 1-shot baseline
        agent_config(False, True,  False, False),  # + Few-shot
        agent_config(True,  True,  False, False),  # + Plan
        agent_config(True,  True,  True,  False),  # + ValidSQL
        agent_config(True,  True,  True,  True),   # + 自纠错 (全开)
    ]


def run_ablation(dataset_path: str, eval_db: str, run_with_config) -> list[dict]:
    """run_with_config(config) -> EvalReport。返回边际贡献表(dict 列表)。

    边际贡献 = 当行 acc - 上一行 acc。
    """
    matrix = config_matrix()
    rows = []
    prev_acc = None
    labels = ["1-shot baseline", "+Few-shot", "+Plan", "+ValidSQL", "+自纠错"]
    for label, cfg in zip(labels, matrix):
        rep = run_with_config(cfg)
        marginal = None if prev_acc is None else rep.exec_acc - prev_acc
        rows.append({"config": label, "exec_acc": rep.exec_acc,
                     "mean_f1": rep.mean_f1, "marginal": marginal, "n": rep.n})
        prev_acc = rep.exec_acc
    return rows
