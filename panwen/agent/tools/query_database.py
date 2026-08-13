# panwen/agent/tools/query_database.py
"""通用自然语言兜底 tool —— 包装 run_query 9 步管线。

make_query_database 为闭包工厂，捕获 conn/backend/rag/fewshot/config，
返回只接受 question 的 query_database(question) -> ToolResult。
供 Task 8 agent-loop 把任意子问题路由到完整 Text-to-SQL 管线。
"""
from __future__ import annotations

from panwen.agent.loop import run_query
from panwen.agent.tools.types import ToolResult, Source


def make_query_database(conn, backend, rag, fewshot, config):
    def query_database(question: str) -> ToolResult:
        res = run_query(question, conn, backend, rag, fewshot, config)
        return ToolResult(
            ok=(res.status == "answered"),
            data=(res.rows if res.rows is not None
                  else (res.reply
                        or (res.explanation.summary if res.explanation else ""))),
            source=Source(
                kind="duckdb",
                sql=res.sql,
                as_of=getattr(config, "eval_as_of", None),
            ),
        )

    return query_database
