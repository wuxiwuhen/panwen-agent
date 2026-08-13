# tests/eval/test_task_runner.py
from panwen.eval.task_runner import score_task

def test_score_task_facet_recall():
    # run_agent 调了 profile+financials → 命中期望切面 {stock_profile, financials};
    # 缺 recent_quotes → recall 2/3, 满足 >0 且 <1。切面词汇须与 TOOL_FACET 一致。
    called = ["get_stock_profile", "get_financials"]
    score = score_task(called_tools=called, expected_facets={"stock_profile", "financials", "recent_quotes"})
    assert score["facet_recall"] > 0.0
    assert score["facet_recall"] < 1.0   # 缺 recent_quotes
