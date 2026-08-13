# tests/eval/test_task_runner.py
from panwen.eval.task_runner import score_task

def test_score_task_facet_recall():
    # run_agent 调了 profile+financials → 命中期望切面 {profile, financials}
    called = ["get_stock_profile", "get_financials"]
    score = score_task(called_tools=called, expected_facets={"profile", "financials", "quotes"})
    assert score["facet_recall"] > 0.0
    assert score["facet_recall"] < 1.0   # 缺 quotes
