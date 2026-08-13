from panwen.ui import config_bridge as cb
from panwen.agent.config import AgentConfig


def test_to_config_maps_three_toggles():
    c = cb.to_config(use_fewshot=True, use_validsql=False, use_selfcorrect=True)
    assert c.use_fewshot is True
    assert c.use_validsql is False
    assert c.use_selfcorrect is True


def test_use_plan_always_true():
    c = cb.to_config(use_fewshot=False, use_validsql=False, use_selfcorrect=False)
    assert c.use_plan is True  # fused always-on，非 toggle


def test_returns_agentconfig():
    assert isinstance(cb.to_config(True, True, True), AgentConfig)


def test_schema_topk_override_and_default():
    assert cb.to_config(True, True, True, schema_topk=8).schema_topk == 8
    assert cb.to_config(True, True, True).schema_topk == 5  # AgentConfig 默认
