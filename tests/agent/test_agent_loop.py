# tests/agent/test_agent_loop.py
import pytest
from unittest.mock import patch
from panwen.agent.agent_loop import run_agent, AgentRun
from panwen.agent.types import ChatResult, Message
from panwen.agent.session import SessionStore
from panwen.agent.config import AgentConfig
from panwen.rag.embed import FakeEmbedder
from panwen.rag.schema_retriever import SchemaRetriever
from panwen.rag.fewshot_store import FewshotStore

class _FakeBE:
    """依次返回预设 tool_calls / 最终文本。"""
    def __init__(self, responses):
        self.responses = list(responses)   # 每个: {"tool_calls":[...] | None, "text": "..."}
    def chat(self, messages, **kw):
        r = self.responses.pop(0)
        blocks = ([{"type": "tool_use", "id": tc["id"], "name": tc["name"], "input": tc["input"]}
                   for tc in r["tool_calls"]] if r.get("tool_calls") else
                  [{"type": "text", "text": r["text"]}])
        return ChatResult(content=r.get("text", ""), tool_calls=r.get("tool_calls") or [],
                          content_blocks=blocks, stop_reason="tool_use" if r.get("tool_calls") else "end_turn")

def _deps():
    rag = SchemaRetriever(embedder=FakeEmbedder(dim=16), topk=3)
    fs = FewshotStore([], embedder=FakeEmbedder(dim=16), k=2)
    return rag, fs

def test_multi_tool_then_synthesis(tmp_path):
    from unittest.mock import patch
    from panwen.data import db
    from panwen.agent.types import AgentResult, Explanation
    conn = db.connect(str(tmp_path/"t.duckdb")); db.init_schema(conn)
    # stock_basic 列序(COLUMN_CLASS): code, name, listing_date, board, industry, is_st, delist_date
    conn.execute("INSERT INTO stock_basic VALUES ('600519','贵州茅台','1990-01-01','主板','白酒','N',NULL)")
    be = _FakeBE([
        {"tool_calls": [{"id":"1","name":"get_stock_profile","input":{"code":"600519"}},
                        {"id":"2","name":"query_database","input":{"question":"最新ROE"}}]},  # 第1轮: 并行2 tool
        {"text": "茅台是白酒板块，最新 ROE 见下表。"},                                        # 第2轮: 综合
    ])
    rag, fs = _deps()
    store = SessionStore(system_prompt="你是盘问")
    # query_database 内部走 run_query → 会多次调 backend.chat(normalize/generate/explain)，
    # 会吃掉 _FakeBE 给外层 loop 的脚本 → 必须把 run_query 整体 mock 掉，隔离内外层 backend。
    with patch("panwen.agent.tools.query_database.run_query") as mq:
        mq.return_value = AgentResult(status="answered",
                                      sql="SELECT roe FROM financial_indicator WHERE code='600519'",
                                      rows=[{"roe": 30.0}], reply=None,
                                      explanation=Explanation([], 0.9, "s"), trace=[])
        ar = run_agent("茅台所有信息", "s1", conn, be, rag, fs, AgentConfig(), store)
    assert ar.synthesis == "茅台是白酒板块，最新 ROE 见下表。"
    assert len(ar.tables) == 2                          # profile + query_database 各产一表
    sess = store.get_or_create("s1")
    assert any(m.role == "user" and m.content == "茅台所有信息" for m in sess.messages)
    # 第1轮的 2 个 tool 都有 tool_result 回填
    assert sum(1 for m in sess.messages if m.role == "user" and isinstance(m.content, list)) >= 2

def test_max_turns_cap(tmp_path):
    from panwen.data import db
    conn = db.connect(str(tmp_path/"t.duckdb")); db.init_schema(conn)
    loop_resp = {"tool_calls": [{"id":"x","name":"get_stock_profile","input":{"code":"600519"}}]}
    be = _FakeBE([loop_resp]*10)   # 永远调 tool，永不综合
    rag, fs = _deps()
    cfg = AgentConfig(agent_max_turns=3)
    ar = run_agent("q", "s", conn, be, rag, fs, cfg, SessionStore("S"))
    assert ar.turns == 3           # 被 max_turns 兜底
