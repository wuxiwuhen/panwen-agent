"""逐组件 ablation(spec §8.3) —— 遍历 AgentConfig 开关组合 → 边际贡献表。

数字 make eval 实测填，绝不编造。

注：use_plan 不作为 ablation 维度——plan+generate 按 spec §2 锁定决策为单次 fused
调用（_generate 始终输出 {plan, sql}，不存在"直出 SQL"分支），故 use_plan 不可独立
消融。AgentConfig.use_plan 保留（默认 True，fused always-on），但不入 config_matrix。
"""
from __future__ import annotations
from panwen.agent.config import AgentConfig


def agent_config(use_fewshot: bool, use_validsql: bool, use_selfcorrect: bool) -> AgentConfig:
    """构造 ablation 用配置。use_plan 不入参（fused always-on，取 AgentConfig 默认 True）。"""
    return AgentConfig(use_fewshot=use_fewshot,
                       use_validsql=use_validsql, use_selfcorrect=use_selfcorrect)


def config_matrix() -> list[AgentConfig]:
    """4 行配置：1-shot baseline → +Few-shot → +ValidSQL → +自纠错（全开）。

    use_plan 不入矩阵（fused always-on，见模块 docstring）。
    """
    return [
        agent_config(False, False, False),  # 1-shot baseline
        agent_config(True,  False, False),  # + Few-shot
        agent_config(True,  True,  False),  # + ValidSQL
        agent_config(True,  True,  True),   # + 自纠错 (全开)
    ]


def run_ablation(dataset_path: str, eval_db: str, run_with_config) -> list[dict]:
    """run_with_config(config) -> EvalReport。返回边际贡献表(dict 列表)。

    边际贡献 = 当行 acc - 上一行 acc。
    """
    matrix = config_matrix()
    rows = []
    prev_acc = None
    labels = ["1-shot baseline", "+Few-shot", "+ValidSQL", "+自纠错"]
    for label, cfg in zip(labels, matrix):
        rep = run_with_config(cfg)
        marginal = None if prev_acc is None else rep.exec_acc - prev_acc
        rows.append({"config": label, "exec_acc": rep.exec_acc,
                     "mean_f1": rep.mean_f1, "marginal": marginal, "n": rep.n})
        prev_acc = rep.exec_acc
    return rows
