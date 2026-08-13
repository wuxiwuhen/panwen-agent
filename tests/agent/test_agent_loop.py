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
    # 第1轮并行 2 个 tool_use 的 tool_result 必须合并到【单条】user 消息(Anthropic 契约:
    # 一条含 N 个 tool_use 的 assistant 消息, 紧跟一条含 N 个 tool_result 的 user 消息),
    # 否则 API 400 "tool_use ids were found without tool_result blocks immediately after"。
    tr_msgs = [m for m in sess.messages if m.role == "user" and isinstance(m.content, list)]
    assert len(tr_msgs) == 1, "并行 tool_result 必须合并为单条 user 消息, 不能拆成多条"
    ids = {b["tool_use_id"] for b in tr_msgs[0].content
           if isinstance(b, dict) and b.get("type") == "tool_result"}
    assert ids == {"1", "2"}

def test_parallel_tool_results_batched_in_one_user_message(tmp_path):
    # 回归(用户实测输入 "告诉我信维通信的所有信息"): 助手一轮并行返回 3 个 tool_use 时,
    # 回填必须是【单条 user 消息含 3 个 tool_result】, 而非 3 条各含 1 个 tool_result 的
    # user 消息。后者违反 Anthropic 契约 → 400
    # "tool_use ids were found without tool_result blocks immediately after: call_01, call_02, call_03".
    from unittest.mock import patch
    from panwen.data import db
    conn = db.connect(str(tmp_path / "t.duckdb")); db.init_schema(conn)
    conn.execute("INSERT INTO stock_basic VALUES ('300136','信维通信','2010-11-05','创业板','消费电子','N',NULL)")
    seen = []

    class _CapBE(_FakeBE):
        def chat(self, messages, **kw):
            seen.append(list(messages))   # 快照本次发给 backend 的 messages(浅拷贝列表)
            return super().chat(messages, **kw)

    be = _CapBE([
        {"tool_calls": [{"id": "call_01", "name": "get_stock_profile", "input": {"code": "300136"}},
                        {"id": "call_02", "name": "get_financials", "input": {"code": "300136"}},
                        {"id": "call_03", "name": "get_recent_quotes", "input": {"code": "300136"}}]},
        {"text": "信维通信: 基本信息/财务/行情见下。"},
    ])
    rag, fs = _deps()
    store = SessionStore(system_prompt="你是盘问")
    with patch("panwen.agent.tools.query_database.run_query"):
        run_agent("告诉我信维通信的所有信息", "s1", conn, be, rag, fs, AgentConfig(), store)
    # 第 2 次 chat(综合轮) 看到的 messages: [..., assistant(tool_use×3), user(tool_result×3)]
    second = seen[1]
    roles = [m.role for m in second]
    ai = roles.index("assistant")            # 助手 tool_use 那条
    user_after = [m for m in second[ai + 1:] if m.role == "user"]
    assert len(user_after) == 1, "并行 tool_result 必须合并到紧跟的单条 user 消息, 不能拆成多条"
    trs = [b for b in user_after[0].content
           if isinstance(b, dict) and b.get("type") == "tool_result"]
    assert {b["tool_use_id"] for b in trs} == {"call_01", "call_02", "call_03"}


def test_max_turns_cap(tmp_path):
    from panwen.data import db
    conn = db.connect(str(tmp_path/"t.duckdb")); db.init_schema(conn)
    loop_resp = {"tool_calls": [{"id":"x","name":"get_stock_profile","input":{"code":"600519"}}]}
    be = _FakeBE([loop_resp]*10)   # 永远调 tool，永不综合
    rag, fs = _deps()
    cfg = AgentConfig(agent_max_turns=3)
    ar = run_agent("q", "s", conn, be, rag, fs, cfg, SessionStore("S"))
    assert ar.turns == 3           # 被 max_turns 兜底
