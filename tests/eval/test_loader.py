"""Task 4: 评测集 loader。"""
import pytest
from panwen.eval import loader as L


def test_load_dataset_returns_items(tmp_path):
    yaml_text = """
- question: 茅台近三年ROE
  gold_sql: SELECT roe FROM financial_indicator WHERE code='600519' ORDER BY report_date DESC LIMIT 3
  difficulty: simple
  tags: [单股, 财务, 时序]
  answerable_on: "2026-06-30"
- question: 今天天气
  gold_sql: null
  difficulty: simple
  tags: [out_of_scope]
  answerable_on: "2026-06-30"
"""
    p = tmp_path / "q.yaml"
    p.write_text(yaml_text, encoding="utf-8")
    items = L.load_dataset(str(p))
    assert len(items) == 2
    assert items[0].question == "茅台近三年ROE"
    assert items[0].difficulty == "simple"
    assert items[1].gold_sql is None  # out_of_scope 题无 gold


def test_stratification_counts(tmp_path):
    """starter 集覆盖 4 难度层(执行期补到 §8.1 配额)。

    强化断言: starter 真实跨越 simple/join/aggregate/domain 全部 4 层 +
    至少 1 条 out_of_scope 陷阱题(用于 Task 8 范围门增益 ablation)。
    """
    from pathlib import Path
    ROOT = Path(__file__).resolve().parents[2]
    items = L.load_dataset(str(ROOT / "panwen" / "eval" / "dataset" / "questions.yaml"))
    diffs = {i.difficulty for i in items}
    # 4 个难度层都必须出现
    assert {"simple", "join", "aggregate", "domain"} <= diffs
    # 至少 1 条 out_of_scope 陷阱题 (gold_sql 为 None)
    oos = [i for i in items if i.gold_sql is None]
    assert len(oos) >= 1
    # 所有题目 answerable_on 已对齐冻结日 2026-06-30
    assert all(i.answerable_on == "2026-06-30" for i in items)
