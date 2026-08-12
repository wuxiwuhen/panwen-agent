"""Task 8: ablation 开关组合矩阵(spec §8.3)。

use_plan 不作为 ablation 维度（plan+generate 为 fused 单次调用，不可独立消融），
故 config_matrix 为 4 行：baseline → +Few-shot → +ValidSQL → +自纠错。
"""
from panwen.eval import ablation as ab


def test_config_matrix_has_baseline_and_full():
    matrix = ab.config_matrix()
    # 第一行 = baseline, 最后一行 = 全开
    assert matrix[0] == ab.agent_config(False, False, False)
    assert matrix[-1] == ab.agent_config(True, True, True)
    assert len(matrix) == 4  # baseline → +Few-shot → +ValidSQL → +自纠错


def test_agent_config_fields():
    c = ab.agent_config(use_fewshot=True, use_validsql=False, use_selfcorrect=False)
    assert c.use_fewshot
    assert not c.use_validsql and not c.use_selfcorrect
    assert c.use_plan is True  # fused always-on，非 ablation 维度


def test_each_row_adds_exactly_one_component():
    """每行相对上一行只翻一个真实组件（边际消融的必要条件）。"""
    matrix = ab.config_matrix()
    for prev, cur in zip(matrix, matrix[1:]):
        deltas = [prev.use_fewshot != cur.use_fewshot,
                  prev.use_validsql != cur.use_validsql,
                  prev.use_selfcorrect != cur.use_selfcorrect]
        assert sum(deltas) == 1
