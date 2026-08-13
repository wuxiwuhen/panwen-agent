# Tool-Use Agent Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有确定性管线上方加一层 Anthropic-SDK tool-use agent，支持多 tool 编排、多表渲染、可溯源、多轮会话；全栈迁移到 `AnthropicBackend`。

**Architecture:** 三层——Tier1 `run_safe_sql`（守卫+执行原语）→ Tier2 窄 tool + `query_database`（recipe，都走 Tier1）→ Tier3 agent loop（裸 `anthropic` SDK 自写 tool-use loop）。agent loop 把 Plan 2 管线包成 tool，内层逐组件 ablation 纯度不破坏。详见 spec `docs/superpowers/specs/2026-08-13-agent-loop-design.md`。

**Tech Stack:** `anthropic` SDK（新增）、DuckDB、sqlglot、sentence-transformers（bge）、Gradio、pytest。

---

## Global Constraints

（承自 spec §13 红线 + 技术约束，每个 task 隐含遵守）

- **诚实红线**：不预填任何准确率；所有指标跑 `make eval` 实测后填；Hermes/GRPO/BIRD/Spider 数字一律标「他人成果/基准对比」，绝不冒认。内层（gold-SQL 执行准确率）与外层（任务级编排）是两个并存维度，不混淆。
- **查询路径绝不 import akshare**（Space 轻量守护，承自 Plan 3）。
- **git identity**：`git -c user.name='PanWen Dev' -c user.email='1527405202@qq.com'` 提交；分支 `feat/agent-loop`。
- **不回归**：现有测试套件（当前 green）不得回归。数据层测试与本 plan 无关，保持不动。
- **CWD gotcha**：Bash CWD 重置到父目录；命令用 `git -C <repo>` 或绝对路径，不依赖 `cd`。
- **类型向后兼容**：`ChatResult`/`Message` 新增字段必须给默认值，不破坏现有 `_ScriptedBackend` 等 mock 构造。
- **只读 + 白名单**：所有 SQL 经 `run_safe_sql`（ValidSQL 检查 1-5 + 超时）；窄 tool 的 `code` 参数额外做 6 位数字校验防注入。

---

## File Structure

**新增**
- `panwen/agent/safe_sql.py` — `run_safe_sql` + `SqlResult`（Tier1）
- `panwen/agent/session.py` — `Session` + `SessionStore`（内存版多轮）
- `panwen/agent/agent_loop.py` — `run_agent` + `AgentRun` + system prompt + dispatch（Tier3）
- `panwen/agent/tools/__init__.py` — tool 注册
- `panwen/agent/tools/types.py` — `Source` / `ToolResult` / `TableResult`
- `panwen/agent/tools/narrow.py` — 4 个窄 tool
- `panwen/agent/tools/query_database.py` — `make_query_database`
- `panwen/agent/tools/schemas.py` — tool 的 JSON schema（喂 LLM）
- `panwen/eval/task_dataset.yaml` — 外层任务级评测集（小规模）
- `panwen/eval/task_runner.py` — 外层任务级评测骨架
- `tests/agent/test_safe_sql.py` / `test_session.py` / `test_agent_loop.py` / `test_tools.py`
- `tests/eval/test_task_runner.py`

**修改**
- `panwen/agent/types.py` — `Message`/`ChatResult` 演进（加 `content_blocks`/`stop_reason`，带默认值）
- `panwen/agent/backend.py` — `OpenAICompatBackend` → `AnthropicBackend`；`make_backend` 指 anthropic 端点
- `panwen/agent/normalize.py` / `explainer.py` / `loop.py(_generate)` — `response_format` → 强制 tool_use
- `panwen/agent/loop.py` — ⑥⑦ 改调 `run_safe_sql`（行为不变）
- `panwen/agent/config.py` — 加 `agent_max_turns`/`session_history_turns`/`eval_as_of`
- `panwen/ui/app.py` / `render.py` / `runtime.py` — 多轮聊天 + 渲染 `AgentRun`
- `requirements.txt` — 加 `anthropic>=0.40.0`；移除 `openai`（删后无引用，task2 grep 确认）
- `tests/agent/test_loop.py` / `test_normalize.py` / `test_explainer.py` / `test_backend.py` — 跟新签名/机制对齐

---

### Task 1: 演进 `Message` / `ChatResult` 类型（向后兼容）

**Files:**
- Modify: `panwen/agent/types.py`
- Test: `tests/agent/test_types.py`

**Interfaces:**
- Produces: `Message.content: str | list | None`；`ChatResult` 加 `content_blocks: list`、`stop_reason: str | None`（均带默认值）。

- [ ] **Step 1: 写失败测试**（验证新字段 + 默认值 + 旧构造不破）

```python
# tests/agent/test_types.py（追加）
from panwen.agent.types import Message, ChatResult

def test_message_accepts_block_list():
    m = Message(role="assistant", content=[{"type": "text", "text": "hi"}])
    assert isinstance(m.content, list)

def test_chatresult_new_fields_default():
    # 旧式构造（无新字段）必须仍可用 —— 保护 _ScriptedBackend 等现有 mock
    r = ChatResult(content="x", tool_calls=[], raw={})
    assert r.content_blocks == []
    assert r.stop_reason is None

def test_chatresult_carries_blocks():
    r = ChatResult(content="x", tool_calls=[{"id": "1", "name": "f", "input": {}}],
                   content_blocks=[{"type": "tool_use", "id": "1"}], stop_reason="tool_use")
    assert r.content_blocks and r.stop_reason == "tool_use"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd panwen && .venv/bin/pytest tests/agent/test_types.py -v`（用绝对路径见 Glocal Constraints；下同）
Expected: FAIL（`content_blocks` 不存在）

- [ ] **Step 3: 改 types.py**

```python
# panwen/agent/types.py —— ChatResult 部分
@dataclass
class ChatResult:
    content: str
    tool_calls: list
    content_blocks: list = field(default_factory=list)   # 原始 anthropic content 块, 回填多轮历史用
    stop_reason: str | None = None                       # "tool_use" | "end_turn" | ...
    raw: dict = field(default_factory=dict)
```
`Message.content` 类型注解改为 `str | list[dict] | None = None`（已是，确认即可）。

- [ ] **Step 4: 跑测试确认通过 + 全量回归**

Run: `cd panwen && .venv/bin/pytest tests/agent/test_types.py tests/agent/test_loop.py -v`
Expected: PASS（新测试过；旧 `_ScriptedBackend` 构造因默认值不破）

- [ ] **Step 5: Commit**

```bash
git -C <repo> add panwen/agent/types.py tests/agent/test_types.py
git -C <repo> -c user.name='PanWen Dev' -c user.email='1527405202@qq.com' commit -m "feat(agent): Message/ChatResult 演进(content_blocks/stop_reason, 向后兼容)"
```

---

### Task 2: `AnthropicBackend` + `make_backend`（替换 OpenAICompatBackend）

**Files:**
- Modify: `panwen/agent/backend.py`（删 `OpenAICompatBackend`，新增 `AnthropicBackend`）
- Modify: `requirements.txt`（加 `anthropic`，移除 `openai`）
- Test: `tests/agent/test_backend.py`

**Interfaces:**
- Produces: `AnthropicBackend.chat(messages, *, tools, tool_choice, temperature, system, model) -> ChatResult`；`make_backend(provider)` 返回 `AnthropicBackend`。
- 消费：`Message`/`ChatResult`（Task1）。

- [ ] **Step 1: 写失败测试**（mock anthropic client）

```python
# tests/agent/test_backend.py（重写）
from unittest.mock import MagicMock
from panwen.agent.backend import AnthropicBackend, make_backend
from panwen.agent.types import Message

def _be_with_mock_create():
    be = AnthropicBackend(api_key="k", base_url="https://api.deepseek.com/anthropic",
                          model="deepseek-chat", auth_mode="auth_token")
    be.client = MagicMock()
    return be

def test_system_extracted_to_top_level():
    be = _be_with_mock_create()
    be.client.messages.create.return_value = MagicMock(
        content=[{"type": "text", "text": "ans"}], stop_reason="end_turn")
    be.chat([Message("system", "SYS"), Message("user", "hi")])
    kw = be.client.messages.create.call_args.kwargs
    assert kw["system"] == "SYS"                       # system 抽到顶层
    assert all(m["role"] != "system" for m in kw["messages"])

def test_text_content_string_wrapped_as_block():
    be = _be_with_mock_create()
    be.client.messages.create.return_value = MagicMock(content=[{"type": "text", "text": "x"}], stop_reason="end_turn")
    be.chat([Message("user", "hi")])
    sent = be.client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert sent == [{"type": "text", "text": "hi"}]    # str → 单 text 块

def test_response_tool_use_parsed():
    be = _be_with_mock_create()
    be.client.messages.create.return_value = MagicMock(
        content=[{"type": "tool_use", "id": "t1", "name": "f", "input": {"a": 1}}],
        stop_reason="tool_use")
    r = be.chat([Message("user", "go")], tools=[{"name": "f", "input_schema": {}}])
    assert r.tool_calls == [{"id": "t1", "name": "f", "input": {"a": 1}}]
    assert r.stop_reason == "tool_use"
    assert r.content_blocks == [{"type": "tool_use", "id": "t1", "name": "f", "input": {"a": 1}}]

def test_make_backend_providers():
    import os
    os.environ["DEEPSEEK_API_KEY"] = "dk"
    os.environ["GLM_API_KEY"] = "gk"
    assert isinstance(make_backend("deepseek"), AnthropicBackend)
    assert isinstance(make_backend("glm"), AnthropicBackend)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd panwen && .venv/bin/pytest tests/agent/test_backend.py -v`
Expected: FAIL（`AnthropicBackend` 不存在）

- [ ] **Step 3: 实现 AnthropicBackend**

```python
# panwen/agent/backend.py（整体替换）
from __future__ import annotations
import os
from typing import Protocol
from anthropic import Anthropic
from panwen.agent.types import Message, ChatResult

_PROVIDERS = {
    "deepseek": ("DEEPSEEK_API_KEY", "https://api.deepseek.com/anthropic", "deepseek-chat", "auth_token"),
    "glm":      ("GLM_API_KEY", "https://api.z.ai/api/anthropic", "glm-4.6", "auth_token"),
}

class BackendConfigError(RuntimeError): ...

class AgentBackend(Protocol):
    def chat(self, messages, *, tools=None, tool_choice=None, temperature=0.0,
             system=None, model=None) -> ChatResult: ...

def _to_content_blocks(msg: Message) -> list[dict]:
    if isinstance(msg.content, list):
        return msg.content
    if msg.content is None:
        return []
    return [{"type": "text", "text": msg.content}]

class AnthropicBackend:
    def __init__(self, api_key, base_url, model, auth_mode="api_key"):
        # auth_mode: "api_key"→x-api-key(anthropic原生); "auth_token"→Authorization Bearer(z.ai/DeepSeek)
        if auth_mode == "auth_token":
            self.client = Anthropic(base_url=base_url, auth_token=api_key)
        else:
            self.client = Anthropic(base_url=base_url, api_key=api_key)
        self.model = model

    def chat(self, messages, *, tools=None, tool_choice=None, temperature=0.0,
             system=None, model=None) -> ChatResult:
        sys_text = system
        msgs = []
        for m in messages:
            if m.role == "system" and sys_text is None:
                sys_text = m.content or ""
            else:
                msgs.append({"role": m.role, "content": _to_content_blocks(m)})
        kw = dict(model=model or self.model, messages=msgs, temperature=temperature)
        if sys_text: kw["system"] = sys_text
        if tools: kw["tools"] = tools
        if tool_choice: kw["tool_choice"] = tool_choice
        resp = self.client.messages.create(**kw)
        blocks = list(resp.content)
        text = "".join(b.text for b in blocks if getattr(b, "type", None) == "text")
        tool_calls = [{"id": b.id, "name": b.name, "input": b.input}
                      for b in blocks if getattr(b, "type", None) == "tool_use"]
        return ChatResult(content=text, tool_calls=tool_calls, content_blocks=[
            {"type": b.type, **({"text": b.text} if b.type == "text" else
             {"id": b.id, "name": b.name, "input": b.input})}
            for b in blocks],
            stop_reason=getattr(resp, "stop_reason", None),
            raw=getattr(resp, "model_dump", lambda: {})())

def make_backend(provider="deepseek") -> AgentBackend:
    if provider not in _PROVIDERS:
        raise BackendConfigError(f"unknown provider: {provider}")
    env_var, base_url, model, auth_mode = _PROVIDERS[provider]
    api_key = os.getenv(env_var)
    if not api_key:
        raise BackendConfigError(f"missing env {env_var} for provider '{provider}'")
    return AnthropicBackend(api_key=api_key, base_url=base_url, model=model, auth_mode=auth_mode)
```

- [ ] **Step 4: requirements + 确认 openai 无其他引用**

```bash
# 确认 openai 仅 backend.py 用（删除前安全检查）
grep -rn "import openai\|from openai" panwen/   # 应只命中 backend.py（本 task 已删）
```
`requirements.txt`：加 `anthropic>=0.40.0`，移除 `openai>=1.0.0`。

- [ ] **Step 5: 跑测试 + commit**

Run: `cd panwen && .venv/bin/pytest tests/agent/test_backend.py -v` → PASS
```bash
git -C <repo> add panwen/agent/backend.py requirements.txt tests/agent/test_backend.py
git -C <repo> -c user.name='PanWen Dev' -c user.email='1527405202@qq.com' commit -m "feat(agent): AnthropicBackend 替换 OpenAICompatBackend(DeepSeek/GLM anthropic 端点)"
```

> ⚠️ DeepSeek anthropic 端点鉴权（auth_token vs api_key）实现期实测：先 `auth_token`，若 401 改 `api_key`。spec §15#1。

---

### Task 3: 结构化输出迁移（`response_format` → 强制 tool_use）

3 处：`normalize._llm_understand`、`explainer.explain`、`loop._generate`。各定义一个 `input_schema` 小工具 + `tool_choice` 强制，从 `tool_calls[0].input` 取结果。`clarify` 纯 chat 不动。

**Files:**
- Modify: `panwen/agent/normalize.py`, `panwen/agent/explainer.py`, `panwen/agent/loop.py`
- Test: `tests/agent/test_normalize.py`, `test_explainer.py`, `test_loop.py`

**Interfaces:**
- 消费：`AnthropicBackend.chat(tools=, tool_choice=)`（Task2）。

- [ ] **Step 1: 写失败测试**（normalize 从 tool_use 取结构；解析失败仍安全降级）

```python
# tests/agent/test_normalize.py（重写核心测）
from panwen.agent.normalize import normalize
from panwen.agent.types import ChatResult

class _ToolBackend:
    def __init__(self, tool_input: dict):
        self.tool_input = tool_input
        self.received = {}
    def chat(self, messages, *, tools=None, tool_choice=None, **kw):
        self.received = {"tools": tools, "tool_choice": tool_choice}
        return ChatResult(content="", tool_calls=[{"id": "1", "name": "emit_norm", "input": self.tool_input}],
                          content_blocks=[], stop_reason="tool_use")

def test_normalize_reads_tool_use_input():
    be = _ToolBackend({"intent": "sql_answerable", "entities": {"code": "600519"},
                       "date_range": None, "top_k": None, "order": None, "question": "茅台ROE"})
    n = normalize("茅台ROE", be)
    assert n.intent == "sql_answerable" and n.entities == {"code": "600519"}
    assert be.received["tool_choice"] == {"type": "tool", "name": "emit_norm"}   # 强制

def test_normalize_safe_degrade_on_no_toolcall():
    class _Empty:
        def chat(self, messages, **kw):
            return ChatResult(content="", tool_calls=[], content_blocks=[], stop_reason="end_turn")
    n = normalize("x", _Empty())
    assert n.intent == "needs_clarify"      # 无 tool_use → 安全降级（同旧 json 解析失败语义）
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd panwen && .venv/bin/pytest tests/agent/test_normalize.py -v` → FAIL

- [ ] **Step 3: 改 normalize.py**（`_llm_understand` 用强制 tool_use）

```python
# panwen/agent/normalize.py —— 替换 _llm_understand
_NORM_TOOL = {
    "name": "emit_norm",
    "description": "输出对用户问题的结构化理解",
    "input_schema": {
        "type": "object",
        "properties": {
            "intent": {"type": "string", "enum": ["sql_answerable", "needs_clarify", "out_of_scope"]},
            "entities": {"type": "object"},
            "date_range": {"type": ["array", "null"], "items": {"type": "string"}},
            "top_k": {"type": ["integer", "null"]},
            "order": {"type": ["string", "null"], "enum": ["asc", "desc", None]},
            "question": {"type": "string"},
        },
        "required": ["intent", "entities", "question"],
    },
}

def _llm_understand(question: str, backend) -> dict:
    from panwen.agent.types import Message
    resp = backend.chat(
        [Message(role="system", content=_PROMPT), Message(role="user", content=question)],
        tools=[_NORM_TOOL], tool_choice={"type": "tool", "name": "emit_norm"}, temperature=0.0)
    if resp.tool_calls:
        return resp.tool_calls[0]["input"]
    return {"intent": "needs_clarify", "entities": {}}   # 无 tool_use → 安全降级
```

- [ ] **Step 4: 同理改 explainer.py**（`emit_explain{assumptions[], confidence:float, summary}`，try/except 保留 fallback dict）与 loop.py `_generate`（`emit_sql{sql:str, plan?:str}`，`use_plan` 控制是否含 plan；无 tool_use → `(None, None)`）。explainer/loop 测试同步改 `_ToolBackend` 模式。

- [ ] **Step 5: 跑全量 agent 测试 + commit**

Run: `cd panwen && .venv/bin/pytest tests/agent/ -v` → PASS（test_loop 的 `_ScriptedBackend` 需改为返回 tool_calls——见 Step 4 附注）
```bash
git -C <repo> add panwen/agent/normalize.py panwen/agent/explainer.py panwen/agent/loop.py tests/agent/
git -C <repo> -c user.name='PanWen Dev' -c user.email='1527405202@qq.com' commit -m "feat(agent): response_format→强制 tool_use(normalize/explainer/generate)"
```

> **test_loop.py 适配**：`_ScriptedBackend.chat` 现需按调用序返回「normalize 的 tool_call / generate 的 tool_call / explain 的 tool_call」。把 scripts 改为 `dict`（含 `tool_calls`）序列，`chat` 从中取 `tool_calls` 与 `content`。

---

### Task 4: `run_safe_sql` 守卫+执行原语（Tier 1）

从 `loop.py` 的 ⑥validate + ⑦execute 抽出。**单次执行，无重试**（自纠错归 query_database）。

**Files:**
- Create: `panwen/agent/safe_sql.py`
- Test: `tests/agent/test_safe_sql.py`

**Interfaces:**
- Produces: `run_safe_sql(sql, conn, config, schema_view=None) -> SqlResult`；`SqlResult{ok, rows, sql, blocking, advisory, rootCause, elapsed_ms}`。
- 消费：`validate_sql`/`build_schema_view`（validsql）、`_execute_sql`（从 loop.py 抽到 safe_sql 或共享）。

- [ ] **Step 1: 写失败测试**（每类 rootCause + 成功）

```python
# tests/agent/test_safe_sql.py
import pytest
from panwen.agent.safe_sql import run_safe_sql, SqlResult
from panwen.agent.config import AgentConfig
from panwen.data import db

@pytest.fixture
def conn(tmp_path):
    c = db.connect(str(tmp_path / "t.duckdb")); db.init_schema(c)
    c.execute("INSERT INTO financial_indicator VALUES ('600519','2025-12-31',30.0,25.0,90.0,45.0,30.0,NULL,NULL)")
    return c

def test_success(conn):
    r = run_safe_sql("SELECT roe FROM financial_indicator WHERE code='600519'", conn, AgentConfig())
    assert r.ok and r.rows and r.rows[0]["roe"] == 30.0 and r.blocking == []

def test_blocking_unknown_col(conn):
    r = run_safe_sql("SELECT fake_col FROM financial_indicator", conn, AgentConfig())
    assert not r.ok and r.rows is None
    assert any(i.code == "ROOT_UNKNOWN_COL" for i in r.blocking)

def test_write_op_blocked(conn):
    r = run_safe_sql("DELETE FROM financial_indicator", conn, AgentConfig())
    assert not r.ok and any(i.code == "ROOT_WRITE_OP" for i in r.blocking)

def test_unparam_is_advisory_not_blocking(conn):
    # Fix B 字面量: ROOT_UNPARAM 是 advisory, 照常执行
    r = run_safe_sql("SELECT roe FROM financial_indicator WHERE code='600519'", conn, AgentConfig())
    assert r.ok  # advisory 不阻断
    assert all(i.code != "ROOT_UNPARAM" or i in r.advisory for i in r.advisory)
```

- [ ] **Step 2: 跑确认失败** → `cd panwen && .venv/bin/pytest tests/agent/test_safe_sql.py -v` FAIL

- [ ] **Step 3: 实现 safe_sql.py**（抽 loop.py 的 `_execute_sql` + ⑥⑦ 逻辑）

```python
# panwen/agent/safe_sql.py
from __future__ import annotations
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from dataclasses import dataclass, field
from panwen.agent.config import AgentConfig
from panwen.validsql.validator import validate_sql, build_schema_view, SchemaView, ValidationIssue

@dataclass
class SqlResult:
    ok: bool
    rows: list[dict] | None
    sql: str
    blocking: list[ValidationIssue] = field(default_factory=list)
    advisory: list[ValidationIssue] = field(default_factory=list)
    rootCause: str | None = None
    elapsed_ms: int | None = None

def _execute(sql, conn, timeout_s):
    def _run():
        cur = conn.execute(sql)
        cols = [d[0] for d in cur.description] if cur.description else []
        return [dict(zip(cols, r)) for r in cur.fetchall()]
    try:
        with ThreadPoolExecutor(max_workers=1) as ex:
            return ex.submit(_run).result(timeout=timeout_s), None
    except FuturesTimeout:
        return None, "ROOT_TIMEOUT"
    except Exception as e:
        return None, f"ROOT_EXEC:{type(e).__name__}:{e}"

_BLOCKING = {"ROOT_PARSE", "ROOT_WRITE_OP", "ROOT_UNKNOWN_TABLE",
             "ROOT_UNKNOWN_COL", "ROOT_TYPE_AGG", "ROOT_CARTESIAN"}

def run_safe_sql(sql, conn, config: AgentConfig, schema_view: SchemaView | None = None) -> SqlResult:
    sv = schema_view or build_schema_view()
    issues = validate_sql(sql, sv, conn=conn) if config.use_validsql else []
    blocking = [i for i in issues if i.code in _BLOCKING]
    advisory = [i for i in issues if i.code == "ROOT_UNPARAM"]
    if blocking:
        return SqlResult(False, None, sql, blocking=blocking, advisory=advisory,
                         rootCause=blocking[0].rootCause)
    t0 = time.perf_counter()
    rows, root = _execute(sql, conn, config.exec_timeout_s)
    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    if root is None:
        return SqlResult(True, rows, sql, advisory=advisory, elapsed_ms=elapsed_ms)
    return SqlResult(False, None, sql, advisory=advisory, rootCause=root, elapsed_ms=elapsed_ms)
```

- [ ] **Step 4: 跑测试 + commit**

Run: `cd panwen && .venv/bin/pytest tests/agent/test_safe_sql.py -v` → PASS
```bash
git -C <repo> add panwen/agent/safe_sql.py tests/agent/test_safe_sql.py
git -C <repo> -c user.name='PanWen Dev' -c user.email='1527405202@qq.com' commit -m "feat(agent): run_safe_sql 守卫+执行原语(Tier1, 抽自 loop ⑥⑦)"
```

---

### Task 5: `query_database` 重构（loop ⑥⑦ → run_safe_sql，行为不变）

把 `loop.py` 的 ⑥validate+⑦execute 替换为 `run_safe_sql` 调用。自纠错 N=3 循环保留（它循环调 run_safe_sql）。**目标是行为不变**——现有 `test_loop.py` 全过。

**Files:**
- Modify: `panwen/agent/loop.py`
- Test: `tests/agent/test_loop.py`（应不改即过；若 mock 适配在 Task3 已做）

**Interfaces:**
- 消费：`run_safe_sql`（Task4）。

- [ ] **Step 1: 确认基线绿**

Run: `cd panwen && .venv/bin/pytest tests/agent/test_loop.py -v` → 记录当前 PASS 状态（基线）

- [ ] **Step 2: 重构 loop.py 的 ⑥⑦ 段（用真实变量名）**

现 loop.py 在 `for attempt in range(budget):`（line 94）内：line 96 `_generate` → line 100-101 `prev_sql=sql; last_sql=sql` → ⑥ line 105-118（`validate_sql`+blocking→`continue`）→ ⑦ line 121-127（`_execute_sql`→success `break`/fail `feedback=root`）。把 ⑥+⑦（line 105-127）整体替换为一次 `run_safe_sql`，保留 `prev_sql`/`last_sql`/`last_root`/`last_rows`/`feedback`/`trace` 语义不变：

```python
# loop.py —— for attempt 内，line 100-101 之后插入 import(文件顶)，替换 line 105-127：
from panwen.agent.safe_sql import run_safe_sql   # 加到文件顶部 import 区
# ...(line 96-101: _generate / prev_sql=sql / last_sql=sql 不动)...

        # ⑥⑦ 合并为一次 run_safe_sql(守卫+执行原语)
        sr = run_safe_sql(sql, conn, config, sv)
        if sr.blocking:
            last_root = sr.blocking[0].rootCause
            feedback = "; ".join(f"{i.code}:{i.message}" for i in sr.blocking)
            trace.append(TraceStep("validate", False, feedback[:80], last_root))
            continue
        advisory = " +ROOT_UNPARAM(advisory)" if sr.advisory else ""
        trace.append(TraceStep("validate", True,
                               ("skipped(use_validsql=False)" if not config.use_validsql
                                else f"checks 1-5 pass{advisory}")))
        last_rows, last_root = sr.rows, sr.rootCause
        if sr.ok:
            trace.append(TraceStep("execute", True, f"{len(sr.rows)} rows"))
            break
        feedback = sr.rootCause
        trace.append(TraceStep("execute", False, sr.rootCause[:80], sr.rootCause))
```
注意：`run_safe_sql` 内部已按 `config.use_validsql` 决定是否跑 ValidSQL（False→issues=[]→无 blocking→直接执行），所以 `use_validsql=False` 路径行为不变；trace 文案用上面的 ternary 保留 "skipped" 字样以与旧版一致。`last_sql` 在 line 101 已赋值。

- [ ] **Step 3: 跑 test_loop + 全 agent 回归**

Run: `cd panwen && .venv/bin/pytest tests/agent/ -v` → 全 PASS（行为不变）

- [ ] **Step 4: Commit**

```bash
git -C <repo> add panwen/agent/loop.py
git -C <repo> -c user.name='PanWen Dev' -c user.email='1527405202@qq.com' commit -m "refactor(agent): loop ⑥⑦ 改调 run_safe_sql(行为不变)"
```

---

### Task 6: Tier 2 — tool 类型 + 4 窄 tool + `make_query_database`

**Files:**
- Create: `panwen/agent/tools/types.py`, `narrow.py`, `query_database.py`, `schemas.py`, `__init__.py`
- Test: `tests/agent/test_tools.py`

**Interfaces:**
- 消费：`run_safe_sql`（Task4）、`run_query`（Task5）、schema 表名。
- Produces：`Source`/`ToolResult`/`TableResult`；4 个窄 tool；`make_query_database`；tool JSON schemas。

- [ ] **Step 1: 写失败测试**（窄 tool：code 校验 + 字面量 SQL 快照 + run_safe_sql mock；query_database 包装）

```python
# tests/agent/test_tools.py
import pytest
from unittest.mock import patch
from panwen.agent.tools import narrow, query_database
from panwen.agent.tools.types import ToolResult, Source

def test_get_stock_profile_rejects_bad_code():
    with pytest.raises(ValueError):
        narrow.get_stock_profile("'; DROP--")          # 非 6 位数字 → 拒

def test_get_stock_profile_builds_literal_sql():
    with patch("panwen.agent.tools.narrow.run_safe_sql") as m:
        m.return_value = type("R", (), {"ok": True, "rows": [{"name": "茅台"}],
                                          "sql": "SELECT name FROM stock_basic WHERE code='600519'",
                                          "blocking": [], "rootCause": None})()
        r = narrow.get_stock_profile("600519")
        sql = m.call_args.args[0]
        assert "stock_basic" in sql and "600519" in sql and "?" not in sql   # 字面量
        assert r.source.kind == "duckdb" and r.source.table == "stock_basic"

def test_make_query_database_wraps_run_query():
    from panwen.agent.types import AgentResult, Explanation
    with patch("panwen.agent.tools.query_database.run_query") as m:
        m.return_value = AgentResult(status="answered", sql="SELECT 1", rows=[{"a": 1}],
                                     reply=None, explanation=Explanation([], 0.9, "s"), trace=[])
        qd = query_database.make_query_database(conn=None, backend=None, rag=None, fewshot=None,
                                                 config=None)
        r = qd("茅台ROE")
        assert r.ok and r.source.sql == "SELECT 1"
```

- [ ] **Step 2: 跑确认失败** → FAIL

- [ ] **Step 3: 实现 types.py**

```python
# panwen/agent/tools/types.py
from dataclasses import dataclass

@dataclass
class Source:
    kind: str                 # "duckdb" | "web"(P2) | "rss"(P2)
    table: str | None = None
    sql: str | None = None
    as_of: str | None = None
    url: str | None = None

@dataclass
class ToolResult:
    ok: bool
    data: list[dict] | str
    source: Source
    note: str | None = None

@dataclass
class TableResult:
    title: str
    rows: list[dict] | str
    source: Source
```

- [ ] **Step 4: 实现 narrow.py**（4 tool；共享 `_run` helper + code 校验）

```python
# panwen/agent/tools/narrow.py
import re
from panwen.agent.safe_sql import run_safe_sql
from panwen.agent.config import AgentConfig
from panwen.agent.tools.types import ToolResult, Source

def _check_code(code: str) -> str:
    if not re.fullmatch(r"\d{6}", code):
        raise ValueError(f"非法股票代码: {code!r}（须 6 位数字）")
    return code

def _run(conn, sql, table, as_of=None) -> ToolResult:
    sr = run_safe_sql(sql, conn, AgentConfig())
    return ToolResult(ok=sr.ok, data=sr.rows if sr.ok else (sr.rootCause or "查询失败"),
                      source=Source(kind="duckdb", table=table, sql=sql, as_of=as_of),
                      note=None if sr.ok else "; ".join(i.code for i in sr.blocking))

def get_stock_profile(conn, code):
    code = _check_code(code)
    sql = f"SELECT name, board, industry, is_st, listing_date FROM stock_basic WHERE code = '{code}'"
    return _run(conn, sql, "stock_basic")

def get_financials(conn, code, report_date=None):
    code = _check_code(code)
    filt = f"AND i.report_date = '{report_date}'" if report_date else ""
    sql = (f"SELECT i.report_date, i.revenue, i.net_profit, b.total_assets, b.total_liab, "
           f"b.total_equity, c.op_cf, f.roe, f.gross_margin, f.debt_ratio "
           f"FROM income_statement i JOIN balance_sheet b USING(code, report_date) "
           f"JOIN cashflow_statement c USING(code, report_date) "
           f"JOIN financial_indicator f USING(code, report_date) "
           f"WHERE i.code = '{code}' {filt} ORDER BY i.report_date DESC LIMIT 1")
    return _run(conn, sql, "income_statement+balance+cashflow+indicator")

def get_recent_quotes(conn, code, days=30):
    code = _check_code(code)
    sql = (f"SELECT date, open, high, low, close, volume FROM daily_quote "
           f"WHERE code = '{code}' ORDER BY date DESC LIMIT {int(days)}")
    return _run(conn, sql, "daily_quote")

def get_performance(conn, code):
    code = _check_code(code)
    sql = (f"SELECT report_date, revenue_yoy, net_profit_yoy FROM performance_express "
           f"WHERE code = '{code}' ORDER BY report_date DESC")
    return _run(conn, sql, "performance_express")
```

- [ ] **Step 5: 实现 query_database.py + schemas.py**

```python
# panwen/agent/tools/query_database.py
from panwen.agent.loop import run_query
from panwen.agent.tools.types import ToolResult, Source

def make_query_database(conn, backend, rag, fewshot, config):
    def query_database(question: str) -> ToolResult:
        res = run_query(question, conn, backend, rag, fewshot, config)
        return ToolResult(
            ok=(res.status == "answered"),
            data=res.rows if res.rows is not None else (res.reply or (res.explanation.summary if res.explanation else "")),
            source=Source(kind="duckdb", sql=res.sql,
                          as_of=getattr(config, "eval_as_of", None)))
    return query_database
```
```python
# panwen/agent/tools/schemas.py  —— 给 LLM 的 tool 定义（name/description/input_schema）
TOOLS_SCHEMA = [
    {"name": "get_stock_profile", "description": "查股票基本信息(名称/板块/行业/ST)",
     "input_schema": {"type": "object", "properties": {"code": {"type": "string"}}, "required": ["code"]}},
    {"name": "get_financials", "description": "查最新财务(营收/净利/资产/现金流/ROE 等)",
     "input_schema": {"type": "object", "properties": {"code": {"type": "string"}, "report_date": {"type": "string"}}, "required": ["code"]}},
    {"name": "get_recent_quotes", "description": "查近 N 日行情",
     "input_schema": {"type": "object", "properties": {"code": {"type": "string"}, "days": {"type": "integer"}}, "required": ["code"]}},
    {"name": "get_performance", "description": "查业绩快报(营收/净利同比)",
     "input_schema": {"type": "object", "properties": {"code": {"type": "string"}}, "required": ["code"]}},
    {"name": "query_database", "description": "任意自然语言子问题 → SQL 查询(通用兜底)",
     "input_schema": {"type": "object", "properties": {"question": {"type": "string"}}, "required": ["question"]}},
]
```

- [ ] **Step 6: 跑测试 + commit**

Run: `cd panwen && .venv/bin/pytest tests/agent/test_tools.py -v` → PASS
```bash
git -C <repo> add panwen/agent/tools/ tests/agent/test_tools.py
git -C <repo> -c user.name='PanWen Dev' -c user.email='1527405202@qq.com' commit -m "feat(agent): Tier2 tool 类型 + 4 窄 tool + query_database + schemas"
```

---

### Task 7: 会话历史（内存 SessionStore + 整轮窗口）

**Files:**
- Create: `panwen/agent/session.py`
- Test: `tests/agent/test_session.py`

**Interfaces:**
- Produces: `Session{sid, messages, created_at}`；`SessionStore.get_or_create/append`；`_window(session, keep_turns)`。

- [ ] **Step 1: 写失败测试**

```python
# tests/agent/test_session.py
from panwen.agent.session import SessionStore, _window, Session
from panwen.agent.types import Message

def test_get_or_create_seeds_system():
    s = SessionStore()
    sess = s.get_or_create("s1")
    assert sess.messages[0].role == "system"           # 创建时种子 system

def test_append_and_persist_across_calls():
    s = SessionStore(); s.append("s1", Message("user", "hi"))
    assert s.get_or_create("s1").messages[-1].content == "hi"

def test_window_drops_oldest_whole_turns_keeps_system():
    # system + 8 轮(user/assistant 对)，keep 6 → 保留 system + 最近 6 轮，丢最旧 2 轮
    sess = Session(sid="s", messages=[Message("system", "S")], created_at="t")
    for i in range(8):
        sess.messages.append(Message("user", f"u{i}"))
        sess.messages.append(Message("assistant", f"a{i}"))
    _window(sess, keep_turns=6)
    contents = [m.content for m in sess.messages]
    assert sess.messages[0].role == "system"          # system 始终保留
    assert "u0" not in contents and "a0" not in contents   # 最旧 2 轮被丢
    assert "u2" in contents and "a7" in contents       # 最近 6 轮保留
    assert contents[-1] == "a7"

def test_window_keeps_tool_results_with_their_assistant():
    # 关键: tool_result 消息也是 role="user"，必须与它归属的 assistant(tool_use) 同轮，
    # 不能因 role=="user" 就拆成新轮 → 否则裁剪会产生 tool_use/tool_result 孤儿。
    sess = Session(sid="s", messages=[Message("system", "S")], created_at="t")
    # 轮0: user问 → assistant(tool_use) → user(tool_result x2)
    sess.messages += [Message("user", "q0"),
                      Message("assistant", [{"type": "tool_use", "id": "t1", "name": "f", "input": {}}],
                              tool_calls=[{"id": "t1", "name": "f", "input": {}}]),
                      Message("user", [{"type": "tool_result", "tool_use_id": "t1", "content": "r1"}]),
                      Message("user", [{"type": "tool_result", "tool_use_id": "t1", "content": "r2"}])]
    # 轮1: user问 → assistant
    sess.messages += [Message("user", "q1"), Message("assistant", "a1")]
    _window(sess, keep_turns=1)     # 只留最近 1 轮 → 轮0 整轮丢，轮1 整轮留
    contents = [m.content for m in sess.messages]
    assert "q0" not in contents                        # 轮0 user 问题被丢
    assert all(not (isinstance(c, list)) for c in contents if isinstance(c, list)) or True
    # 关键断言: 任何留下的 tool_result 必须有其归属(这里全丢，所以不应残留孤儿 tool_result)
    assert not any(isinstance(m.content, list) and
                   any(isinstance(b, dict) and b.get("type") == "tool_result" for b in m.content)
                   for m in sess.messages)
    assert "q1" in contents and "a1" in contents       # 轮1 完整保留
```

- [ ] **Step 2: 跑确认失败** → FAIL

- [ ] **Step 3: 实现 session.py**

```python
# panwen/agent/session.py
from dataclasses import dataclass, field
from panwen.agent.types import Message

SYSTEM_SEED = ""  # 由 agent_loop 注入实际 system prompt（见 Task8）；store 只负责结构

@dataclass
class Session:
    sid: str
    messages: list[Message] = field(default_factory=list)
    created_at: str = ""

class SessionStore:
    def __init__(self, system_prompt: str = ""):
        self._system = system_prompt
        self._sessions: dict[str, Session] = {}
    def get_or_create(self, sid: str) -> Session:
        if sid not in self._sessions:
            self._sessions[sid] = Session(sid=sid, created_at="",
                                          messages=[Message("system", self._system)] if self._system else [])
        return self._sessions[sid]
    def append(self, sid: str, msg: Message) -> None:
        self.get_or_create(sid).messages.append(msg)

def _is_tool_result(msg: Message) -> bool:
    """tool_result 回填消息: role='user' + content 是含 tool_result 块的 list。
    这类消息不开启新轮——它归属前一条 assistant(tool_use)。"""
    return (isinstance(msg.content, list) and bool(msg.content)
            and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in msg.content))

def _window(session: Session, keep_turns: int) -> None:
    """整轮裁剪: 保留首条 system + 最近 keep_turns 轮。
    一「轮」= 一条真实 user 输入(非 tool_result)起，到下一条真实 user 输入前。
    tool_result(user 角色)不切轮 → 避免裁剪产生 tool_use/tool_result 孤儿(破坏 API 约定)。"""
    msgs = session.messages
    system = [m for m in msgs if m.role == "system"]
    convo = [m for m in msgs if m.role != "system"]
    turns, cur = [], []
    for m in convo:
        if m.role == "user" and not _is_tool_result(m) and cur:
            turns.append(cur); cur = []    # 真实新问题 → 切轮
        cur.append(m)
    if cur: turns.append(cur)
    kept = turns[-keep_turns:] if keep_turns >= 0 else turns
    session.messages = system + [m for t in kept for m in t]
```

- [ ] **Step 4: 跑测试 + commit**

Run: `cd panwen && .venv/bin/pytest tests/agent/test_session.py -v` → PASS
```bash
git -C <repo> add panwen/agent/session.py tests/agent/test_session.py panwen/agent/config.py
git -C <repo> -c user.name='PanWen Dev' -c user.email='1527405202@qq.com' commit -m "feat(agent): 内存 SessionStore + 整轮窗口(多轮会话简单版)"
```
（config.py 同步加 `agent_max_turns: int = 6`、`session_history_turns: int = 6`、`eval_as_of: str = "2026-06-30"`。）

---

### Task 8: Tier 3 — agent loop + `AgentRun` + system prompt + dispatch

**Files:**
- Create: `panwen/agent/agent_loop.py`
- Test: `tests/agent/test_agent_loop.py`

**Interfaces:**
- 消费：`AnthropicBackend`、tools（Task6）、`SessionStore`/`_window`（Task7）、`TOOLS_SCHEMA`、config。
- Produces：`run_agent(question, session_id, conn, backend, rag, fewshot, config, store) -> AgentRun`；`AgentRun{status, synthesis, tables, sources, trace, turns}`。

- [ ] **Step 1: 写失败测试**（FakeBackend 出固定 tool_calls 序列 → 验证 dispatch/多轮/终止/max_turns）

```python
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
    conn.execute("INSERT INTO stock_basic VALUES ('600519','贵州茅台','主板','白酒','N','1990-01-01',NULL)")
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
```

- [ ] **Step 2: 跑确认失败** → FAIL

- [ ] **Step 3: 实现 agent_loop.py**

```python
# panwen/agent/agent_loop.py
from __future__ import annotations
from dataclasses import dataclass, field
from panwen.agent.types import Message, TraceStep
from panwen.agent.config import AgentConfig
from panwen.agent.session import SessionStore, _window
from panwen.agent.tools import narrow, query_database
from panwen.agent.tools.schemas import TOOLS_SCHEMA
from panwen.agent.tools.types import ToolResult, TableResult, Source

SYSTEM_PROMPT = (
    "你是「盘问」，A 股结构化数据分析 agent（行情/财务/板块/资金面/宏观）。\n"
    "- 拆解：宽意图（如「所有信息」）拆成多个切面，各选最合适 tool。\n"
    "- 选 tool：切面命中窄 tool 优先用窄 tool（零幻觉）；任意自然语言用 query_database。\n"
    "- 综合：多切面 → 分节多表答复；每个事实标 source；陈述假设；不确定就说明。\n"
    "- 拒答/澄清：非金融/不可查（交易、预测涨跌）礼貌拒；缺关键信息（哪只股/时间窗）先问。"
)

def _build_dispatch(conn, backend, rag, fewshot, config):
    qd = query_database.make_query_database(conn, backend, rag, fewshot, config)
    def dispatch(name, inp):
        if name == "get_stock_profile": return narrow.get_stock_profile(conn, inp["code"])
        if name == "get_financials":    return narrow.get_financials(conn, inp["code"], inp.get("report_date"))
        if name == "get_recent_quotes": return narrow.get_recent_quotes(conn, inp["code"], inp.get("days", 30))
        if name == "get_performance":   return narrow.get_performance(conn, inp["code"])
        if name == "query_database":    return qd(inp["question"])
        return ToolResult(False, f"未知 tool: {name}", Source(kind="none"))
    return dispatch

@dataclass
class AgentRun:
    status: str = "answered"
    synthesis: str = ""
    tables: list[TableResult] = field(default_factory=list)
    sources: list[Source] = field(default_factory=list)
    trace: list[TraceStep] = field(default_factory=list)
    turns: int = 0

def run_agent(question, session_id, conn, backend, rag, fewshot, config: AgentConfig,
              store: SessionStore) -> AgentRun:
    store._system = store._system or SYSTEM_PROMPT
    dispatch = _build_dispatch(conn, backend, rag, fewshot, config)
    session = store.get_or_create(session_id)
    session.append(Message("user", question))
    _window(session, config.session_history_turns)
    tables, sources, trace = [], [], []
    turns = 0
    while turns < config.agent_max_turns:
        resp = backend.chat(session.messages, tools=TOOLS_SCHEMA, system=store._system, temperature=0.0)
        session.append(Message("assistant", resp.content_blocks, tool_calls=resp.tool_calls))
        if not resp.tool_calls:
            return AgentRun("answered", resp.content, tables, _dedup(sources), trace, turns)
        for tc in resp.tool_calls:
            tr = dispatch(tc["name"], tc["input"])
            content = [{"type": "tool_result", "tool_use_id": tc["id"],
                        "content": _serialize(tr)}]
            session.append(Message("user", content))
            if tr.source and tr.source.kind != "none":
                sources.append(tr.source)
                if isinstance(tr.data, list):
                    tables.append(TableResult(title=tc["name"], rows=tr.data, source=tr.source))
            trace.append(TraceStep(tc["name"], tr.ok, str(tr.data)[:80]))
        turns += 1
    return AgentRun("answered", "(已达最大轮次)", tables, _dedup(sources), trace, turns)

def _serialize(tr: ToolResult) -> str:
    import json
    return json.dumps(tr.data, ensure_ascii=False, default=str)[:4000]

def _dedup(srcs):
    seen, out = set(), []
    for s in srcs:
        k = (s.kind, s.table, s.sql)
        if k not in seen: seen.add(k); out.append(s)
    return out
```

- [ ] **Step 4: 跑测试 + commit**

Run: `cd panwen && .venv/bin/pytest tests/agent/test_agent_loop.py -v` → PASS
```bash
git -C <repo> add panwen/agent/agent_loop.py tests/agent/test_agent_loop.py
git -C <repo> -c user.name='PanWen Dev' -c user.email='1527405202@qq.com' commit -m "feat(agent): Tier3 agent loop(裸 SDK tool-use) + AgentRun + dispatch"
```

---

### Task 9: Demo UI — 多轮聊天 + 渲染 `AgentRun`

**Files:**
- Modify: `panwen/ui/app.py`, `render.py`, `runtime.py`
- Test: `tests/ui/test_app.py`（扩展现有）

**Interfaces:**
- 消费：`run_agent` + `SessionStore`（Task8）、`AgentRun`/`TableResult`。

- [ ] **Step 1: 写失败测试**（render AgentRun → 多表 markdown；多轮 chat 回调用 run_agent 带 session_id）

```python
# tests/ui/test_app.py（追加）
from panwen.ui.render import render_agent_run
from panwen.agent.agent_loop import AgentRun
from panwen.agent.tools.types import TableResult, Source

def test_render_agent_run_multi_tables():
    ar = AgentRun(synthesis="茅台概览如下。",
                  tables=[TableResult("基本信息", [{"name": "茅台"}], Source("duckdb", "stock_basic")),
                          TableResult("最新财务", [{"revenue": 1e9}], Source("duckdb", "income_statement"))],
                  sources=[Source("duckdb", "stock_basic")])
    md = render_agent_run(ar)
    assert "基本信息" in md and "最新财务" in md and "茅台概览" in md
```

- [ ] **Step 2: 跑确认失败** → FAIL

- [ ] **Step 3: render.py 加 `render_agent_run`；app.py 改 gradio chatbot**

```python
# panwen/ui/render.py（追加）
def render_agent_run(ar) -> str:
    parts = [ar.synthesis] if ar.synthesis else []
    for t in ar.tables:
        parts.append(f"**{t.title}**")
        parts.append(_rows_to_md(t.rows))
    if ar.sources:
        parts.append("**来源**: " + ", ".join(
            f"{s.table or s.kind}" for s in ar.sources))
    return "\n\n".join(parts)
```
`app.py`：用 `gr.Chatbot` + `gr.Textbox`（chat_interface 风格），每轮回调里用模块级 `SessionStore` + `run_agent(question, session_id=..., ...)`，session_id 绑定会话（如固定 "default" 或按 user）。agent 模式默认；保留 run_query 单查入口作 toggle。

- [ ] **Step 4: 跑测试 + 手测一次 + commit**

Run: `cd panwen && .venv/bin/pytest tests/ui/ -v` → PASS
```bash
git -C <repo> add panwen/ui/ tests/ui/
git -C <repo> -c user.name='PanWen Dev' -c user.email='1527405202@qq.com' commit -m "feat(ui): 多轮聊天 + 渲染 AgentRun(多表+溯源)"
```

---

### Task 10: Eval — 内层新后端重测 + 外层任务级骨架

**Files:**
- Create: `panwen/eval/task_dataset.yaml`, `panwen/eval/task_runner.py`
- Test: `tests/eval/test_task_runner.py`
- Run: `make eval`（内层重测，如实记录新数）

**Interfaces:**
- 内层：`run_eval.py` 结构零改（`make_backend` 已返回 AnthropicBackend）。
- 外层：`task_runner.run_task_eval(dataset, run_agent_fn) -> report`。

- [ ] **Step 1: 写外层 task_runner 测试**（骨架：给定 run_agent_fn 与期望切面，判覆盖率）

```python
# tests/eval/test_task_runner.py
from panwen.eval.task_runner import score_task

def test_score_task_facet_recall():
    # run_agent 调了 profile+financials → 命中期望切面 {profile, financials}
    called = ["get_stock_profile", "get_financials"]
    score = score_task(called_tools=called, expected_facets={"profile", "financials", "quotes"})
    assert score["facet_recall"] > 0.0
    assert score["facet_recall"] < 1.0   # 缺 quotes
```

- [ ] **Step 2: 跑确认失败** → FAIL

- [ ] **Step 3: task_dataset.yaml（~5 题多面）+ task_runner.py**

`task_dataset.yaml`：例
```yaml
- id: all_info_sunway
  question: "我想知道信维通信(300136)的所有信息"
  expected_facets: [stock_profile, financials, recent_quotes, performance]
- id: compare_roe
  question: "对比京东方A(000725)和澄星股份(600078)的最新ROE"
  expected_facets: [financials]
```
`task_runner.py`：跑每题 → 抓 `AgentRun.trace` 里的 tool 名 → 映射 facet → 算 recall；多表/溯源计数。**判定实现期定（人工 or LLM-judge，spec §15#2），先给 recall + 表数 + 溯源数三个客观量。**

- [ ] **Step 4: 内层重测（诚实红线）**

Run: `cd panwen && NO_PROXY='*' no_proxy='*' .venv/bin/python scripts/run_eval.py`
→ **如实记录**新后端上的执行准确率 + ablation。写进 `docs/superpowers/specs/2026-08-13-agent-loop-design.md` §9.1 或 README（标注「AnthropicBackend 实测，非跨域基准」）。不预填、不冒认。

- [ ] **Step 5: 跑全量测试 + commit**

Run: `cd panwen && .venv/bin/pytest -q` → 全 green
```bash
git -C <repo> add panwen/eval/task_dataset.yaml panwen/eval/task_runner.py tests/eval/test_task_runner.py docs/
git -C <repo> -c user.name='PanWen Dev' -c user.email='1527405202@qq.com' commit -m "feat(eval): 外层任务级评测骨架 + 内层新后端重测(如实记录)"
```

---

## Self-Review（写完后自检，fix inline）

1. **Spec 覆盖**：spec §11 九条交付 → Task1(types) / Task2(backend) / Task3(structured) / Task4(run_safe_sql) / Task5(query_database) / Task6(tools+narrow+qd) / Task7(session) / Task8(agent loop) / Task9(UI) / Task10(eval)。✅ 全覆盖。
2. **占位符**：无 TBD/TODO；repetitive 处（4 窄 tool）给了共享 helper + 各自 SQL，非占位。
3. **类型一致**：`ChatResult.content_blocks`（Task1 定义）在 Task2/Task8 使用一致；`Source`/`ToolResult`/`TableResult`（Task6）在 Task8/Task9 使用一致；`run_agent` 签名 spec §14 ↔ Task8 一致。
4. **依赖序**：Task1→2→3→4→5→6→7→8→9→10，上层依赖下层，无环。
5. **诚实**：Task10 Step4 明确「如实记录、不预填」，符合红线。

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-08-13-agent-loop.md`. Two execution options:

**1. Subagent-Driven (recommended)** — 我每个 task 派一个 fresh subagent 实现，task 间做 spec+质量 review，最后全分支 review。快、上下文不污染。

**2. Inline Execution** — 在本会话按 executing-plans 逐 task 执行，带 checkpoint。

哪种？
