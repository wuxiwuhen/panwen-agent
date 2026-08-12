"""Task 8: ablation 开关组合矩阵(spec §8.3)。"""
from panwen.eval import ablation as ab


def test_config_matrix_has_baseline_and_full():
    matrix = ab.config_matrix()
    # 第一行 = 全关 baseline, 最后一行 = 全开
    assert matrix[0] == ab.agent_config(False, False, False, False)
    assert matrix[-1] == ab.agent_config(True, True, True, True)
    assert len(matrix) == 5  # §8.3 五行


def test_agent_config_fields():
    c = ab.agent_config(use_plan=True, use_fewshot=True, use_validsql=False, use_selfcorrect=False)
    assert c.use_plan and c.use_fewshot
    assert not c.use_validsql and not c.use_selfcorrect
