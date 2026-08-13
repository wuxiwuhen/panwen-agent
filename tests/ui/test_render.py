from panwen.ui import render
from panwen.agent.types import AgentResult, Explanation, TraceStep


def _answered():
    return AgentResult(
        status="answered",
        sql="SELECT roe FROM financial_indicator WHERE code='600519'",
        rows=[{"report_date": "2025-12-31", "roe": 30.0}],
        reply=None,
        explanation=Explanation(assumptions=["近一年=最近报告期"], confidence=0.82, summary="茅台最新ROE"),
        trace=[TraceStep("normalize", True, "ok"), TraceStep("execute", True, "1 row")],
    )


def test_result_table_answered():
    headers, rows = render.result_table(_answered())
    assert headers == ["report_date", "roe"]
    assert rows == [["2025-12-31", 30.0]]


def test_result_table_empty_when_no_rows():
    r = AgentResult("failed", None, None, "err", None, [])
    assert render.result_table(r) == ([], [])


def test_sql_block_and_empty():
    assert render.sql_block(_answered()).startswith("```sql")
    assert render.sql_block(AgentResult("failed", None, None, "x", None, [])) == ""


def test_trace_rows_marks_and_rootcause():
    r = AgentResult("failed", None, None, "err", None,
                    [TraceStep("validate", False, "bad col", "ROOT_UNKNOWN_COL")])
    assert render.trace_rows(r) == [["validate", "✗", "bad col", "ROOT_UNKNOWN_COL"]]
    assert render.trace_rows(_answered())[0] == ["normalize", "✓", "ok", ""]


def test_explanation_md_and_none():
    md = render.explanation_md(_answered())
    assert "82%" in md and "假设" in md
    assert render.explanation_md(AgentResult("failed", None, None, "x", None, [])) == ""


def test_status_reply_branches():
    assert render.status_reply(_answered()) == ""
    assert render.status_reply(AgentResult("clarified", None, None, "请问你指哪只股票？", None, [])) == "请问你指哪只股票？"
    assert render.status_reply(AgentResult("out_of_scope", None, None, "超出A股数据范围", None, [])) == "超出A股数据范围"
