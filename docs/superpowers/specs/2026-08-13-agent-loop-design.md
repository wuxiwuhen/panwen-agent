# 盘问 PanWen · Plan 4「Tool-Use Agent Loop」设计 spec

> **范围**：本 spec 覆盖 **Plan 4 = 在现有确定性管线上方加一层 Anthropic-SDK tool-use agent 编排**，把管线 + 窄查询包成 tool，让 agent 能对「所有信息」这类宽意图做**多 tool 编排、多表渲染、可溯源**的答复。
> **与既有 spec 的关系**：
> - `docs/design.md` = 项目总体单一事实源（数据层 / Phase 划分 / 红线）。冲突时数据层与红线以 design.md 为准。
> - `2026-08-12-agent-core-design.md`（Plan 2，Agent 核心）——**本 spec 与之共存**：Plan 2 的 9 步管线 / ValidSQL / 双路 RAG / eval+ablation **原样保留为内层**（被包成 tool）；**§9 的 backend 部分（OpenAICompatBackend → AnthropicBackend）与 §3 的「确定性 vs agentic」张力由本 spec 取代/调和**。
> - `2026-08-13-demo-ui-design.md`（Plan 3，Demo UI）——共存；UI 渲染结构从单 `AgentResult` 演进为多表 `AgentRun`（§10）。
> **日期**：2026-08-13　**状态**：设计定稿，待用户复审 → writing-plans

---

## 1. 背景与动机

Plan 2 的 `run_query` 是**确定性单 SQL 管线**，返回单个 `AgentResult(sql, rows, ...)`。用户用 Demo UI 测「我想知道信维通信股票的所有信息」时，agent 只能出**一张薄表**（单 SQL / 单 rows）——体验差。根因是架构天花板：没有"拆解宽意图 → 多次查询 → 多表汇总"的能力。

Plan 4 不重写管线，而是**在管线上方加一层 agentic 编排**：agent（裸 `anthropic` SDK + 自写 tool-use loop）把用户输入拆成子问题，调用一组 tool（窄查询 recipe + 通用 `query_database`） gathering 数据，再汇总成多表 + 可溯源答案。能力随 tool 增长（后续加图表 / 选股 / RSSHub 等tool 即长出新体验）。

---

## 2. 已锁定决策（不再征询）

| 维度 | 决策 |
|---|---|
| SDK / loop | **裸 `anthropic` Python SDK + 自写 tool-use loop**（不用 Claude Agent SDK，loop 不黑箱、可演示、贴合现有 trace） |
| Provider 桥接 | **两个 provider 都有原生 Anthropic 兼容端点**：DeepSeek `https://api.deepseek.com/anthropic`、GLM `https://api.z.ai/api/anthropic`。`anthropic` SDK 换 `base_url` + 鉴权即可直连，无 hub / LiteLLM / 翻译层 |
| 后端一致性 | **全栈一个 `AnthropicBackend`**（删除 `OpenAICompatBackend`）。内层 `_generate`/`normalize`/`explainer` 与外层 agent loop 用**同一后端、同一 Messages 模型、同一 tool_use 机制**。`AgentBackend` Protocol 保留（测试 mock + 未来 provider） |
| 结构化输出 | `response_format={"type":"json_object"}`（OpenAI 专属）→ **强制 tool_use**（`input_schema` = 输出形状 + `tool_choice` 强制）。validated，且与编排 tool 同机制 |
| 架构 | **三层**：Tier1 `run_safe_sql`（守卫+执行原语）→ Tier2 窄 tool + `query_database`（recipe，都走 Tier1）→ Tier3 agent loop（裸 SDK 编排） |
| 与 Plan 2 的关系 | **共存不替代**：agent loop 把 Plan 2 管线包成 `query_database` tool。管线的逐组件 ablation 纯度**不破坏**（§4 调和 §3 张力） |
| eval 口径 | **两层不混淆**：内层复用冻结集（gold-SQL 执行准确率 + ablation，在新后端重测）；外层新增小规模**任务级**评测（编排成功，非执行准确率） |
| 可溯源 | **Phase 1 钉死 tool 结果的 `source` 契约**；Phase 2 加 web/RSSHub tool 时同契约，溯源自然延续 |
| 会话历史 | **Phase 1 做简单版多轮会话**（内存 `SessionStore` + 整轮窗口裁剪，§8.4）；增强（摘要/持久化/跨会话）推迟 |
| Phase 范围 | 见 §11（交付 / 推迟） |

---

## 3. §3 张力的调和（确定性 vs agentic）

Plan 2 spec §3 当初**为 ablation 纯度明确否决了自主工具循环**（"LLM 会隐式跳过/合并步骤，ablation 数字不可信"）。本 spec 不推翻该结论，而是**分层**：

- **内层（`query_database` = Plan 2 九步管线）**：保持**确定性 + 逐组件可开关**。逐组件 ablation 在此层有效——它测的是「单 NL 子问题 → 单 SQL → 单 rows」的生成+守卫+自纠质量。**ablation 纯度不破坏。**
- **外层（agent loop）**：是 agentic 编排，**不参与组件 ablation**（agentic 本质不可逐组件开关）。它有自己独立的**任务级**评测（§9）。

两层在 **tool 接口**处解耦：agent loop 不知道 `query_database` 内部是确定性管线；`query_database` 不知道自己被 agentic loop 调用。这是「ReAct 式 + 逐组件可测」同时满足的关键。

---

## 4. 架构总览

```
用户输入
   │
   ▼
┌─────────────────────────────────────────────────────────┐
│  Tier 3 · agent loop (agent/agent_loop.py)              │
│  裸 anthropic SDK + 自写 tool-use loop (DeepSeek/GLM)    │
│  拆解 → 选 tool → 汇总(多表 + 溯源)                       │
│      │ tools: get_stock_profile / get_financials /       │
│      │        get_recent_quotes / get_performance /      │
│      │        query_database(通用兜底)                    │
└─────────────┬───────────────────────────────────────────┘
              │ 每个 tool 内部都调用 ▼
┌─────────────────────────────────────────────────────────┐
│  Tier 2 · tools (agent/tools/*.py)                      │
│  · 窄 tool: 写死 SQL → run_safe_sql (零幻觉)             │
│  · query_database(nl): Plan 2 九步管线 (RAG→generate→    │
│    run_safe_sql→自纠 N=3→explain), ⑥⑦ 改调 run_safe_sql  │
└─────────────┬───────────────────────────────────────────┘
              │ 都调用 ▼
┌─────────────────────────────────────────────────────────┐
│  Tier 1 · run_safe_sql (agent/safe_sql.py)              │
│  全局唯一安全执行路径: ValidSQL(检查1-5) → 只读执行(检查6) │
│  从 loop.py 的 ⑥⑦ 抽出。无重试(重试归 query_database)     │
└─────────────────────────────────────────────────────────┘
```

---

## 5. Tier 1 — `run_safe_sql` 守卫+执行原语

**职责**：给一条 SQL，做 ValidSQL 守卫（检查 1-5）+ 只读执行（检查 6 超时），返回结构化结果。**单次执行，不重试**（自纠错归 `query_database`）。从 [`loop.py` ⑥⑦](../../../panwen/agent/loop.py) 抽出。

**接口**
```python
# agent/safe_sql.py
@dataclass
class SqlResult:
    ok: bool                          # True = 无 blocking + 执行成功, rows 可用
    rows: list[dict] | None
    sql: str                          # 被尝试的 SQL
    blocking: list[ValidationIssue]   # 阻断性 issue (ROOT_PARSE/WRITE_OP/UNKNOWN_TABLE/
                                      #   UNKNOWN_COL/TYPE_AGG/CARTESIAN)
    advisory: list[ValidationIssue]   # 非阻断 (ROOT_UNPARAM —— Fix B 字面量 SQL 走这条)
    rootCause: str | None             # 执行失败码: ROOT_TIMEOUT / ROOT_EXEC:<type>:<msg>
    elapsed_ms: int | None

def run_safe_sql(sql: str, conn, config: AgentConfig,
                 schema_view: SchemaView | None = None) -> SqlResult: ...
```

**语义**（与现 loop.py 一致，仅抽出）：
1. `validate_sql(sql, schema_view or build_schema_view(), conn=conn)` → 拆 blocking / advisory。
2. 若 blocking 非空 → `ok=False`, `rootCause=blocking[0].rootCause`, 不执行。
3. 否则执行（`ThreadPoolExecutor` + `config.exec_timeout_s`，复用 `_execute_sql` 逻辑）。
4. 执行成功 → `ok=True, rows=...`；超时 → `rootCause="ROOT_TIMEOUT"`；异常 → `rootCause="ROOT_EXEC:<type>:<msg>"`。
5. ROOT_UNPARAM 始终 advisory，**不阻断执行**（与 Fix B 字面量策略一致）。

---

## 6. Tier 2 — tools（recipe，都走 `run_safe_sql`）

### 6.1 结果契约（可溯源，Phase 1 钉死）

```python
# agent/tools/types.py
@dataclass
class Source:
    kind: str            # "duckdb" | "web"(P2) | "rss"(P2)
    table: str | None    # duckdb 表名
    sql: str | None      # 实际执行的 SQL (溯源+复现)
    as_of: str | None    # 数据截止: report_date / 冻结日期
    url: str | None      # web/rss (Phase 2)

@dataclass
class ToolResult:
    ok: bool
    data: list[dict] | str   # rows, 或 文本/错误说明
    source: Source
    note: str | None = None  # 如 "top10_holders 端点损坏, 0 行"
```

### 6.2 窄 tool（写死 SQL，零幻觉）—— Phase 1 清单 4 个

覆盖「所有信息」的自然切面。每个拼**字面量 SQL**（Fix B 风格，`WHERE code = '<code>'`）→ `run_safe_sql` → 包 `ToolResult(source={kind:"duckdb", table, sql, as_of})`。这即「语义层 lite」：metric→column 映射写在代码里，模型不碰列名。

| tool | 表 | 说明 |
|---|---|---|
| `get_stock_profile(code)` | stock_basic | name/board/industry/is_st/listing_date |
| `get_financials(code, report_date=None)` | income+balance+cashflow+indicator | 默认最新 report_date；4 表同报告期横向拼 |
| `get_recent_quotes(code, days=30)` | daily_quote | 最近 N 日 ohlcv |
| `get_performance(code)` | performance_express | 营收/净利同比 |

> `top10_holders` 因 akshare 端点损坏（0 行）**不进 Phase 1 窄 tool**；`dragon_tiger`/`margin_daily`/宏观作为 query_database 的兜底覆盖，不单列窄 tool（YAGNI）。

### 6.3 `query_database(nl_question)` —— 通用兜底

**= Plan 2 九步管线，⑥⑦ 改调 `run_safe_sql`**。任意 NL 子问题出 rows。

```python
def make_query_database(conn, backend, rag, fewshot, config):
    def query_database(question: str) -> ToolResult:
        res = run_query(question, conn, backend, rag, fewshot, config)  # 内部 ⑥⑦→run_safe_sql
        return ToolResult(
            ok=(res.status == "answered"),
            data=res.rows if res.rows is not None else (res.reply or res.explanation.summary),
            source=Source(kind="duckdb", table=None, sql=res.sql, as_of=config.eval_as_of),
        )
    return query_database
```

- 自纠错 N=3 **保留在 `run_query` 内**（它循环调 `run_safe_sql`）。`run_safe_sql` 本身无重试。
- `run_query` 的 `normalize`/`dispatch`（out_of_scope/clarify 早退）**保留**——子问题级的拒答/澄清由它处理。

---

## 7. Backend 全栈迁移（OpenAI → Anthropic）

### 7.1 `AnthropicBackend`

```python
# agent/backend.py（替换 OpenAICompatBackend）
class AnthropicBackend:
    """裸 anthropic SDK, base_url 指 DeepSeek/GLM 的 anthropic 端点。"""
    def __init__(self, api_key: str, base_url: str, model: str, auth_mode: str):
        # auth_mode: "api_key"(x-api-key, anthropic 原生) | "auth_token"(Bearer, z.ai/DeepSeek)
        ...
    def chat(self, messages: list[Message], *, tools=None, tool_choice=None,
             temperature=0.0, system: str | None = None, model=None) -> ChatResult: ...
```

- **system 抽取**：anthropic 的 `system` 是顶层参数，不是 message。`chat` 从 `messages` 里抽 `role=="system"` → `system` 参数，余下作 `messages`。
- **block 归一化**：请求侧 `Message.content: str` → `[{"type":"text","text":...}]`；`tool_calls` → `content` 里的 `tool_use` 块 + `tool_result` 块（多轮）。响应侧 `resp.content` 块 → `ChatResult.content`（拼接 text 块）+ `tool_calls`（从 tool_use 块）。
- `make_backend(provider)`：`{"deepseek": (api.deepseek.com/anthropic, ...), "glm": (api.z.ai/api/anthropic, auth_token)}`。DeepSeek 鉴权 header 形式实现期实测确认（先试 Bearer/auth_token）。

### 7.2 `Message` / `ChatResult` 演进（向后兼容）

```python
@dataclass(frozen=True)
class Message:
    role: str                              # system|user|assistant
    content: str | list[dict] | None = None  # str=简单文本; list=blocks(text/tool_use/tool_result)
    tool_calls: list | None = None         # assistant 发起的 tool_use (兼容字段)

@dataclass
class ChatResult:
    content: str                           # 拼接后的 text
    tool_calls: list                       # 归一化的 [{id,name,input}]
    content_blocks: list                   # 原始 anthropic content 块(text/tool_use)，回填多轮历史用
    stop_reason: str | None = None         # "tool_use" | "end_turn" | ...
    raw: dict = field(default_factory=dict)
```

### 7.3 结构化输出：`response_format` → 强制 tool_use

3 处迁移（`_generate`/`normalize`/`explainer`）：各定义一个 `input_schema` = 输出形状的小工具 + `tool_choice={"type":"tool","name":"..."}` 强制，从 `tool_calls[0].input` 取已校验结果。

- `_generate`：`emit_sql{sql:str, plan?:str}`（`use_plan` 控制是否含 plan 字段）。
- `normalize`：`emit_norm{intent, entities, date_range, top_k, order, question}`。
- `explainer`：`emit_explain{assumptions[], confidence:float, summary}`。
- `clarify`：纯 chat，不迁移。

> 比 OpenAI JSON 模式更稳（validated），且与 agent loop 编排 tool 同机制——整栈统一 anthropic Messages + tool_use。

---

## 8. Tier 3 — agent loop（`agent/agent_loop.py`）

裸 `anthropic` SDK + 自写 tool-use loop。

### 8.1 主循环

```python
def run_agent(question: str, session_id: str, conn, backend, rag, fewshot, config,
              store: SessionStore) -> AgentRun:
    tools = build_tools(conn, backend, rag, fewshot, config)   # 窄 tool + query_database
    schemas = [t.schema for t in tools]                         # 给 LLM 的 JSON schema
    session = store.get_or_create(session_id)                   # 带历史的多轮(§8.4)
    session.append(Message("user", question))                   # 追加本轮用户输入
    _window(session, config.session_history_turns)              # 简单整轮窗口裁剪
    turns = 0
    while turns < config.agent_max_turns:
        resp = backend.chat(session.messages, tools=schemas, system=SYSTEM_PROMPT,
                            tool_choice=None, temperature=0.0)
        session.append(Message("assistant", resp.content_blocks, tool_calls=resp.tool_calls))
        if not resp.tool_calls:                                 # 终止 → 最终综合
            break
        for tc in resp.tool_calls:
            result = dispatch(tc.name, tc.input, tools)         # 执行 tool
            session.append(Message("user", [tool_result_block(tc.id, result)]))
        turns += 1
    return AgentRun.from_turns(question, session, turns)
```

- `config.agent_max_turns`（新增，默认 6）兜底，防死循环。
- 每轮可发起**多个** tool_call（并行 gathering），全部回填 `tool_result` 后再进下一轮。
- 终止条件：LLM 不再调 tool（出最终文本）或达 `agent_max_turns`。

### 8.2 system prompt 要点

- 角色：A 股结构化数据分析 agent（行情 / 财务 / 板块 / 资金面 / 宏观）。
- **拆解**：宽意图（如「所有信息」）拆成多个切面，各选最合适 tool。
- **选 tool**：切面命中窄 tool 优先用窄 tool（零幻觉）；任意 NL 用 `query_database`。
- **综合**：多切面 → 分节多表答复；每个事实标 source；陈述假设；不确定就说明。
- **拒答/澄清**：非金融 / 不可查（交易、预测涨跌）礼貌拒；缺关键信息（哪只股、时间窗）先问。

### 8.3 `AgentRun`（多表结果契约，UI 演进目标）

```python
@dataclass
class TableResult:
    title: str               # "最新财务" / "近 30 日行情" / ...
    rows: list[dict] | str
    source: Source

@dataclass
class AgentRun:
    status: str              # "answered"|"clarified"|"out_of_scope"|"failed"
    synthesis: str           # 最终 NL 综合答复
    tables: list[TableResult]
    sources: list[Source]    # 汇总溯源（去重）
    trace: list[TraceStep]   # 每轮: {turn, tool_calls[], ...}
    turns: int
```

### 8.4 会话历史（简单版，Phase 1）

当前系统单次问答、无记忆。Phase 1 加**最简多轮会话**：

- `SessionStore`（**内存版**，Phase 1；Phase 2 可换持久化）：按 `session_id` 存 `Session.messages`（含 system + 全部历史轮）。
- `run_agent` 取/建 session → 追加本轮 user → **基于历史 messages 跑 tool-use loop**（agent 记得之前查过什么）。
- **上下文管理（简单整轮窗口）**：`config.session_history_turns`（默认 6）裁掉最旧的**整轮**（一轮 = 一条 user + assistant 完整响应，含其 tool_use/tool_result 子序列 + 最终 synthesis），**保留 system**。整轮裁剪避免 tool_use/tool_result 孤儿。无摘要、无压缩（Phase 2 再优化）。
- system prompt 在 session 创建时种子一次。
- **UI**：Gradio chatbot 组件（§10），session_id 绑定聊天会话。

> 简单 = 内存存储 + 整轮窗口，不做摘要/向量记忆/跨会话。体验出问题（上下文丢失 / token 爆）再优化。

---

## 9. 评测（两层、不混淆、诚实）

内层（单题 SQL 质量）与外层（多面编排）是**两个并存维度**，各有入口、互不替代、不混淆。

### 9.1 内层（`query_database` / `run_query`）—— 复用冻结集

- 复用 [`eval/dataset/questions.yaml`](../../../panwen/eval/dataset/questions.yaml) 冻结集（实测 ~25 题：21 gold_sql + out_of_scope）。
- gold-SQL **执行准确率（主）** + F1 + 逐组件 **ablation**（`make eval`）—— **结构照旧**，仅在新 `AnthropicBackend` 上**重测**。
- ablation 开关（`use_fewshot`/`use_validsql`/`use_selfcorrect`/`use_plan`）是**后端无关**的管线逻辑 → ablation 有效性不变，只是数字在新后端重测。
- `run_eval.py:_predict` 继续调 `run_query`，**结构零改动**，仅 `make_backend` 返回 `AnthropicBackend`。

### 9.2 外层（agent loop）—— 新增任务级评测

- 新增**小规模**多面问题集（~5-10 题，如「告诉我信维通信的所有信息」「对比京东方A 和澄星股份最新 ROE」）。
- 评的是**编排成功**，**不是**执行准确率：
  - 是否抓全相关切面（召回切面）。
  - 是否多表渲染 + 溯源。
  - 是否避免幻觉 / 越界。
- 判定：人工或 LLM-judge rubric（实现期定）。
- **诚实标注**：自建小集、任务级、非执行准确率、**不可与内层 gold-SQL 数字或任何跨域基准（BIRD/Spider/Hermes）并列**。

---

## 10. Demo UI 演进（AgentResult → AgentRun + 多轮会话）

- 现有 `ui/render.py` 渲染单 `AgentResult`。新增渲染 `AgentRun`：`synthesis`（主答复）+ 多个 `TableResult`（分节表）+ `sources`（溯源脚注）。
- **单次问答 → 多轮聊天**：`app.py` 改用 Gradio chatbot 组件，session_id 绑定聊天会话；每轮 assistant 消息渲染对应 `AgentRun` 的多表 + 溯源。
- 入口保留 run_query（内层单查）与 run_agent（多轮编排）两个入口，agent 模式默认。
- trace 面板展示 agent loop 每轮 tool 调用。
- UI 与后端**合成同一 plan**（§15 已决）。

---

## 11. Phase 1 范围

**交付**
1. `AnthropicBackend` + `Message`/`ChatResult` 演进（§7），删除 `OpenAICompatBackend`。
2. 3 处 `response_format` → 强制 tool_use（§7.3）。
3. `run_safe_sql` 原语（§5）。
4. `query_database`（`run_query` ⑥⑦ 改调 `run_safe_sql`）+ 4 个窄 tool（§6，先 4 个，体验后再加）。
5. agent loop（§8）+ `AgentRun`（§8.3）。
6. **会话历史（简单版）**：`SessionStore` + 整轮窗口 + `run_agent` 带 session_id（§8.4）。
7. source 契约（§6.1）。
8. 内层 eval（新后端重测）+ 外层任务级评测骨架，**两个维度并存**（§9）。
9. UI：多轮聊天 + 渲染 `AgentRun`（§10）。

**推迟（Phase 1.5 / 2）**
- 候选生成 + 选择（CHESS 式多候选）。
- 会话记忆增强（摘要 / 向量记忆 / 跨会话 / 持久化）—— Phase 1 只做内存整轮窗口。
- web / RSSHub / 东方财富 tool（可溯源契约已就位，加 tool 即可）。
- 图表绘制 / 智能选股 tool。
- 全量语义层（metrics catalog YAML）—— Phase 1 用窄 tool 充当 lite 版。

---

## 12. 测试策略（TDD）

- **`AnthropicBackend`**：mock `anthropic` SDK client，验证 system 抽取 / block 归一化 / tool_use↔tool_calls / 鉴权头。
- **`run_safe_sql`**：每类 rootCause 夹具（blocking/advisory/timeout/exec-ok），验证抽出的语义与原 loop.py ⑥⑦ 一致。
- **窄 tool**：拼出的 SQL 字面量快照测试 + run_safe_sql mock，验证 source 契约。
- **`query_database`**：复用现有 `test_loop.py` 的 mock 序列（确定性响应），验证 ⑥⑦ 经 run_safe_sql 后行为不变。
- **agent loop**：FakeBackend 出固定 tool_calls 序列 → 验证 dispatch / 多轮 / 终止 / `AgentRun` 装配 / max_turns 兜底。
- **结构化输出迁移**：normalize/explainer/generate 各验证从 `tool_calls[0].input` 解析（mock）。
- **eval**：内层 `make eval` 在新后端重测，数字如实填；外层任务级集人工/ rubric 判。
- 全部 `pytest`；**现有数据层测试不得回归**；agent 单测的 mock backend 跟 `chat()` 新签名对齐。

---

## 13. 红线（承自 design.md §11 + agent-core §13，不变）

- ❌ 冒认 Hermes/GRPO/BIRD/Spider 任何数字；本项目数字全部 `make eval` 实测。外层任务级评测明确标注「自建小集、非执行准确率、非跨域基准」。
- ❌ 虚构用户数/star/流量；数据来源明确为 akshare（MIT）。
- ❌ 查询路径绝不 import akshare（Space 轻量守护，承自 Plan 3）。
- ✅ 内层 ablation 每行真实测出；外层任务级评测如实报告判定方法。
- ✅ 简历 / 面试口径一致：不预填准确率，跑出来再写。

---

## 14. 关键接口汇总（供 writing-plans 契约）

```python
# agent/safe_sql.py
def run_safe_sql(sql, conn, config, schema_view=None) -> SqlResult
@dataclass class SqlResult: ok; rows; sql; blocking; advisory; rootCause; elapsed_ms

# agent/tools/types.py
@dataclass class Source: kind; table; sql; as_of; url
@dataclass class ToolResult: ok; data; source; note
@dataclass class TableResult: title; rows; source

# agent/tools/*.py
def get_stock_profile(code) -> ToolResult
def get_financials(code, report_date=None) -> ToolResult
def get_recent_quotes(code, days=30) -> ToolResult
def get_performance(code) -> ToolResult
def make_query_database(conn, backend, rag, fewshot, config) -> Callable[[str], ToolResult]

# agent/backend.py（替换 OpenAICompatBackend）
class AnthropicBackend: def chat(messages,*,tools,tool_choice,temperature,system,model)->ChatResult
def make_backend(provider="deepseek") -> AgentBackend

# agent/types.py（演进）
@dataclass class Message: role; content: str|list|None; tool_calls
@dataclass class ChatResult: content; tool_calls; stop_reason; raw
# AgentResult / Explanation / TraceStep / NormQuery 不变

# agent/config.py（新增）
@dataclass(frozen=True) class AgentConfig:
    ... (现有字段) ...
    agent_max_turns: int = 6
    session_history_turns: int = 6   # 多轮整轮窗口(§8.4)
    eval_as_of: str = "2026-06-30"   # 冻结 as-of, 喂 source.as_of

# agent/session.py（新增, Phase 1 内存版）
@dataclass class Session: sid: str; messages: list[Message]; created_at: str
class SessionStore:
    def get_or_create(self, sid: str) -> Session: ...
    def append(self, sid: str, msg: Message) -> None: ...

# agent/agent_loop.py
def run_agent(question, session_id, conn, backend, rag, fewshot, config, store: SessionStore) -> AgentRun
@dataclass class AgentRun: status; synthesis; tables; sources; trace; turns
```

---

## 15. 未决（实现期定）

> **已决（本轮）**：① 合成 **1 个** implementation plan（不分拆）；② 窄 tool **先 4 个**（profile/financials/quotes/performance），体验后再加；③ 内层 + 外层 **两个 eval 入口并存**作两个维度；④ 多轮会话历史进 Phase 1（简单版）。

1. DeepSeek anthropic 端点鉴权 header（x-api-key vs Bearer）—— 实测确认。
2. 外层任务级评测的判定方式（人工 vs LLM-judge）—— 两层入口均保留（已决），判定法实现期定。
3. 会话窗口策略（整轮 drop vs 摘要）—— Phase 1 整轮 drop，体验问题再优化。
4. `get_financials` 多表横向拼的 report_date 对齐策略（取 MAX(report_date) 再回联 vs 各表各自最新）。
