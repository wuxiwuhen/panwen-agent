# 盘问 PanWen · Plan 2「Agent 核心」设计 spec

> **范围**：本 spec 只覆盖 **Plan 2 = Agent 核心闭环**（§4.1 九步 + ValidSQL + 双路 RAG + 自建评测/ablation + 解释层）。
> **与 design.md 的关系**：`docs/design.md` 是项目总体单一事实源（数据层/Phase 划分/红线）。本文件是 Agent 核心子系统的细化设计，冲突时**数据层与红线以 design.md 为准，Agent 闭环实现以本文件为准**。
> **日期**：2026-08-12　**状态**：设计定稿，待复审 → writing-plans

---

## 1. 目标与非目标

**目标（Plan 2 交付物）**
1. 确定性 9 步 Agent 闭环，端到端跑通：中文问题 →（缺信息澄清）→ SQL → ValidSQL → 只读执行 → 自纠错 → 解释。
2. ValidSQL 确定性校验层（sqlglot AST，6 检查）。
3. 双路 RAG（schema 检索 + few-shot 检索，bge embedding，预计算+缓存）。
4. 自建冻结评测集 150 题（分层）+ 执行准确率/F1/维度面板/**逐组件 ablation**。
5. AgentBackend 抽象（DeepSeek 主力，GLM 可加），复用 ggb-fable 的 Backend 注入 + rootCause + trace 模式。

**非目标（明确 defer）**
- 多库业务路由、多轮会话记忆、`search_news` 实时资讯工具（均 Phase 2）。
- BIRD 跨域对标（Phase 3）。
- demo UI（Gradio/Streamlit）—— 本 spec 不含，单独规划。
- 行业分组查询、PE/PB 估值、成分股、日内 K 线 —— 受阻于数据层（design.md 已记录），不进 MVP 评测。

---

## 2. 已锁定决策（不再征询）

| 维度 | 决策 |
|---|---|
| 数据/评测基板 | **先扩财务**（sina 直连，~30–50 股）→ 冻结 `eval.duckdb` → 再建 Agent |
| 主力 LLM | **DeepSeek-V3**（`deepseek-chat`，OpenAI 兼容）；AgentBackend 抽象保证 GLM 可加 |
| Embedding | **`BAAI/bge-large-zh-v1.5`** 本地 sentence-transformers + 预计算落盘缓存 |
| 评测集规模 | **150 题**，分层（见 §8.1） |
| ValidSQL | **全开**（6 检查，§6） |
| 主架构 | **确定性管线 + 有界自纠错子循环**（§3） |
| ① 归一化 | **混合**：规则（日期/单位/top-k）+ LLM（实体/意图） |
| ③⑤ plan+generate | **一次 LLM 调用**，结构化输出（plan 字段 + sql 字段；plan 开关 = 丢 plan 字段） |
| ⑧ 自纠错预算 | **N=3**；每轮复用已检索上下文 + 追加错误反馈（不重新检索） |
| 范围门（out-of-scope） | ① 的 LLM 调用顺带输出 `intent ∈ {sql_answerable, needs_clarify, out_of_scope}`，管线三分支：拒答 / 澄清 / 正常。零额外调用，防「不相干输入被硬塞成幻觉 SQL」 |

---

## 3. 主架构：确定性管线 + 有界自纠错

**为何不用 ggb-fable 的自主工具循环**：design.md §4.1 写「ReAct 式」，但 §7.3 的核心卖点「逐组件 ablation」要求每个组件能**独立开关、干净测边际贡献」——这在 LLM 自主 function-calling 循环里做不到（LLM 会隐式跳过/合并步骤，ablation 数字不可信）。两者内在冲突。

**调和方案**：9 步做成**固定 Python 管线**（确定性，每阶段一个开关 → ablation 干净）；其中第 ⑧ 步自纠错是**有界 ReAct 式微循环**（看 rootCause → 改上游 → 重生），保留了「ReAct 式 + 预算控制」的精神。这样同时满足 §4.1 与 §7.3。

复用 ggb-fable：**AgentBackend 抽象**（chat 注入，trial/byok 工厂）、**rootCause 错误归因**（修上游不盲试）、**hooks/trace**（喂解释层）。**不复用**其自主工具循环与 6 个 function-calling 工具。

---

## 4. 模块结构

```
panwen/
  agent/
    __init__.py
    backend.py        # AgentBackend Protocol + OpenAICompatBackend + make_backend() 工厂
    config.py         # AgentConfig（ablation 开关 + 预算 + 检索 k）
    loop.py           # run_query(): 9 步确定性管线 + 自纠错子循环
    normalize.py      # ① 中文归一化（规则 + LLM）
    clarify.py        # ② 完整性校验 → 主动澄清
    explainer.py      # ⑨ 解释层（假设 + 置信度 + 摘要）
    types.py          # Message / ChatResult / AgentResult / Explanation / TraceStep
  validsql/
    validator.py      # ⑥ validate_sql(): sqlglot AST 6 检查 → list[ValidationIssue]
  rag/
    embed.py          # bge 加载 + 预计算/缓存（schema 文档 + fewshot 问题）
    schema_retriever.py   # ④a 问题 → top-k 表/列子集
    fewshot_store.py  # ④b (question→SQL) 语料检索
  eval/
    dataset/          # 150 题（question, gold_sql, difficulty, tags）—— yaml
    runner.py         # 单配置: 跑全集 → 执行准确率 + F1
    ablation.py       # 遍历开关组合 → 边际贡献表
    panel.py          # 维度面板（难度 / SQL 结构切片）
  prompts/
    v1/               # 版本化 prompt（plan_generate / clarify / explain / normalize_entity）
  tests/
    agent/ validsql/ rag/ eval/   # 对应单测 + 集成测
```

deterministic 架构下，design.md §9 的 `tools/` 目录取消——「工具」即管线各阶段的 Python 函数，不走 LLM function-calling。`search_news`（P2）届时再加。

---

## 5. 数据流：`run_query(question, conn, backend, rag, config) → AgentResult`

固定顺序，每阶段受 `config` 开关控制（ablation 机理）。失败不中断，记入 trace。

```
① normalize(question, backend)   ← 含意图/范围门（折叠进同一次 LLM 调用，零额外成本）
   - 规则: 解析「过去N年/连续M季度/最近一周」→ 日期区间；「百分之X/亿/万」→ 数值；「最低/最高/前K」→ top-k + 排序方向。
   - LLM: 实体/意图解析 + **意图分类 intent ∈ {sql_answerable, needs_clarify, out_of_scope}**。
     · out_of_scope: 闲聊 / 非金融 / 非查询 / 做不了的动作（交易、预测涨跌、写代码、算命）。
     · 行业映射因数据缺无条件成立 → 意图保留，后续 clarify 或退化为全市场筛选。
   - 产出: NormQuery{原问题, 日期区间, top_k, 排序, 实体, 意图, intent}

② dispatch（按 intent，确定性三分支）
   - intent=out_of_scope → 优雅拒答早退: AgentResult(status=out_of_scope, reply="这不在我的能力范围（我只能查 A 股结构化数据：行情/财务/板块/资金面/宏观），试试问『茅台近三年 ROE』？")，sql=None。
   - intent=needs_clarify → 澄清早退: 缺必要槽（哪只股 / 时间窗歧义 / 筛选条件空）→ AgentResult(status=clarified, reply=<澄清问题>)。规则(必填槽) + LLM(歧义)。
   - intent=sql_answerable → 正常走 ③–⑨。
   【关键】任意输入都有归宿——不相干的礼貌拒、缺信息的问、能查的查，无一条被硬塞成幻觉 SQL。

③④ plan+rag(norm, backend, rag, config)
   - schema_retriever(常开): norm → embedding → cosine top-k(config.schema_topk) 表/列 → schema 子集(控 token)。
   - fewshot_store[config.use_fewshot]: 检索 top-k(config.fewshot_k) 相似 (Q→SQL) 作 few-shot。
   - plan: 并入 ⑤ 的结构化输出, 此处只准备上下文。

⑤ generate(norm, schema_subset, fewshot, backend, config)   ← 单次 LLM 调用
   - 结构化输出: {plan: str(若 use_plan), sql: str}。use_plan=False 时 prompt 丢 plan 字段、只要 sql。
   - prompt 装配: 系统(schema方言DuckDB+只读约束) + fewshot + schema子集 + 规则化参数 + 问题。

⑥ validate_sql(sql, schema_view) [config.use_validsql]
   - sqlglot 6 检查(§6) → list[ValidationIssue]。非空 → rootCause 进 ⑧。

⑦ execute_sql(sql, conn) [ThreadPoolExecutor, timeout=config.exec_timeout_s]
   - 只读执行。失败(超时/SQL错误) → rootCause 进 ⑧。

⑧ self_correct(prev_sql, issues/rootCause, context, backend, config) [config.use_selfcorrect]
   - 有界循环 i in 1..config.selfcorrect_budget(=3):
     回灌 {失败SQL + rootCause + 错误} 到 generate(复用③④上下文, 不重新检索) → 新SQL → 重验⑥ → 重执⑦。
     成功即出; 用尽预算仍失败 → 保留最后一次结果, trace 标记, ⑨ 降低置信度。

⑨ explain(question, sql, rows, trace, backend)
   - LLM 出 Explanation{assumptions[], confidence 0..1, summary}。trace 由 hooks 贯穿采集。
```

**控制流出口（三分支）**：out_of_scope → 拒答早退；needs_clarify → 澄清早退；sql_answerable → 走完 ⑤–⑧ 出 SQL+rows，⑨ 出解释。

---

## 6. ValidSQL（`validsql/validator.py`，sqlglot）

`validate_sql(sql: str, schema: SchemaView) -> list[ValidationIssue]`，空列表 = 通过。每 issue 带 `code / message / rootCause`（喂自纠错）。

1. **AST 白名单**：parse 后只允许 `SELECT`（含 CTE/子查询/UNION）；出现 `INSERT/UPDATE/DELETE/DROP/ALTER/CREATE/...` → `ROOT_WRITE_OP`。
2. **表/列存在性**：遍历 AST 的 table/column 引用，对 `schema.py` 的 `COLUMN_CLASS` 核对；不存在 → `ROOT_UNKNOWN_COL`「列 X 不存在于表 Y」（反幻觉核心）。
3. **类型约束**（迁移作者老 NL2SQL 解码器）：`schema.py` 标 `text` 的列禁 `AVG/SUM/MIN/MAX/COUNT(DISTINCT)`；`numeric` 列允范围比较与聚合 → 违者 `ROOT_TYPE_AGG`「对文本列 name 做 AVG 无意义」。
4. **防笛卡尔**：`FROM` 多表须有对应 `JOIN ... ON`/`WHERE` 连接条件；并用 `EXPLAIN` 行数估算 > `config.cartesian_row_warn`(默认 10000) 告警 → `ROOT_CARTESIAN`。
5. **参数化绑定**：用户值走 DuckDB 参数（`?` / `$1`），非字符串拼接 → 检测裸字面量注入模式 → `ROOT_UNPARAM`。（生成阶段 prompt 即要求参数化；此为兜底校验。）
6. **执行超时**：在 ⑦ 用 `ThreadPoolExecutor.submit().result(timeout=config.exec_timeout_s)` 实现，超时 → `ROOT_TIMEOUT`。非 validate 阶段，但归入 ValidSQL 责任域。

`SchemaView` 由 `schema.py` 的 `COLUMN_CLASS` + `PRIMARY_KEYS` 派生（表→列→类型），不新增数据。

---

## 7. RAG（双路检索）

- **`rag/embed.py`**：加载 `BAAI/bge-large-zh-v1.5`（sentence-transformers，本地、离线、免费）。预计算两类 embedding 并缓存落盘（`data/rag_cache/`，gitignore）：(a) schema 文档（每表/列的中文描述），(b) fewshot 问题文本。复用 ggb-fable「预计算 + 缓存」模式，eval 可复现。
- **`schema_retriever.py`**（常开）：问题 embedding × schema 文档 embedding → cosine → top-k 表/列子集。目的：控进 prompt 的 token，并降列幻觉（只给相关列）。
- **`fewshot_store.py`**（`config.use_fewshot`）：存 eval 集的 `(question → gold_sql)`；按问题 embedding 检索 top-k 相似题作 few-shot。**自建集天然带问题文本，比 Hermes 反推 NL 更干净**（design.md §6）。

两路复用同一套 embedding 基建。

---

## 8. 评测与 ablation

### 8.1 冻结集（`eval/dataset/`，150 题）
分层（对标 BIRD 难度）：
- 简单单表 ~40（单股财务深查、宏观、单板块行情）
- 多表 JOIN ~50（财务×行情、龙虎榜×股票）
- 时序聚合·嵌套 ~40（连续N年ROE、每年净利润增长、top-k 筛选）
- 板块·宏观·全市场事件 ~20（融资融券、业绩快报、CPI）

每题 `{question, gold_sql, difficulty, tags[], answerable_on: <freeze_as_of>}`。gold_sql 在冻结的 `eval.duckdb` 上可执、有确定结果。**只能写自建集真实跑出的指标**（design.md §11 红线）。

### 8.2 指标（`eval/runner.py`）
- **执行准确率（主）**：pred SQL 与 gold SQL 在 `eval.duckdb` 上执行结果集一致（排序敏感按题标注）。
- **F1 软评分**：部分行匹配给 0~1（precision/recall on rows）。
- 报告时标注「执行正确性是唯一可信信号，结构相似/LLM-judge 只是代理」（design.md §7.2）。

### 8.3 逐组件 ablation（`eval/ablation.py`）—— 卖点
遍历 `AgentConfig` 开关组合，每配置跑全集：

| 配置 | use_plan | use_fewshot | use_validsql | use_selfcorrect |
|---|---|---|---|---|
| 1-shot baseline | ✗ | ✗ | ✗ | ✗ |
| + Few-shot RAG | ✗ | ✓ | ✗ | ✗ |
| + Plan-then-SQL | ✓ | ✓ | ✗ | ✗ |
| + ValidSQL | ✓ | ✓ | ✓ | ✗ |
| + 自纠错 | ✓ | ✓ | ✓ | ✓ |

→ 每行执行准确率/F1 **实测填** → 边际贡献。`make eval` 一键复现。
**可选维度（范围门增益）**：另跑一组评测含一批 out-of-scope「陷阱题」（闲聊/非金融/诱导幻觉 SQL），对比 有/无 范围门时的「幻觉 SQL 率」（硬塞成 SQL 的比例）——量化范围门防幻觉的价值。

### 8.4 维度面板（`eval/panel.py`）
按 difficulty / SQL 结构（JOIN 数、子查询、聚合）切片准确率。

---

## 9. 关键接口（供 writing-plans 的契约）

```python
# agent/types.py
@dataclass(frozen=True) class Message: role: str; content: str | None; tool_calls: list | None = None
@dataclass class ChatResult: content: str; tool_calls: list; raw: dict
@dataclass class Explanation: assumptions: list[str]; confidence: float; summary: str
@dataclass class TraceStep: stage: str; ok: bool; detail: str; rootCause: str | None = None
@dataclass class AgentResult:
    status: str                  # "answered" | "clarified" | "out_of_scope" | "failed"
    sql: str | None
    rows: list[dict] | None
    reply: str | None            # status != answered 时的非 SQL 回复（澄清问题 / 超范围拒答）
    explanation: Explanation | None   # status=answered 时非空
    trace: list[TraceStep]
# NormQuery（① 产出）: {question, date_range, top_k, order, entities, intent}
#   intent ∈ {"sql_answerable", "needs_clarify", "out_of_scope"}

# agent/backend.py
class AgentBackend(Protocol):
    def chat(self, messages: list[Message], *, tools: list | None = None,
             temperature: float = 0.0, response_format: dict | None = None,
             model: str | None = None) -> ChatResult: ...

class OpenAICompatBackend:        # DeepSeek + GLM 同接口(均 OpenAI 兼容)
    def __init__(self, api_key: str, base_url: str, model: str): ...
def make_backend(provider: str = "deepseek") -> AgentBackend: ...   # 从 env 读 key(trial)

# agent/config.py
@dataclass(frozen=True) class AgentConfig:
    use_plan: bool = True; use_fewshot: bool = True
    use_validsql: bool = True; use_selfcorrect: bool = True
    selfcorrect_budget: int = 3; fewshot_k: int = 3; schema_topk: int = 5
    exec_timeout_s: int = 30; cartesian_row_warn: int = 10_000

# agent/loop.py
def run_query(question: str, conn, backend: AgentBackend, rag: "RagIndex",
              config: AgentConfig = AgentConfig()) -> AgentResult: ...

# validsql/validator.py
@dataclass class ValidationIssue: code: str; message: str; rootCause: str
def validate_sql(sql: str, schema: "SchemaView") -> list[ValidationIssue]: ...

# eval/runner.py
def run_eval(dataset, conn, backend, rag, config: AgentConfig) -> EvalReport: ...  # acc + f1
```

---

## 10. 错误处理

- **管线级**：每阶段 try/except，失败记 trace 不中断；⑧ 自纠错兜底；用尽预算 → 出最后结果 + 降置信度（不抛）。
- **rootCause 归因**：⑥⑦ 失败产出结构化 rootCause（`ROOT_UNKNOWN_COL` 等），回灌 generate 指引「修 schema 误解而非逐条盲试」（搬 ggb-fable execute_command 的 failures[].rootCause）。
- **超时**：⑦ ThreadPoolExecutor 30s；超时 → rootCause 进自纠错。
- **LLM 不可用/限流**：backend.chat 抛错 → 管线捕获，trace 标记，返回 AgentResult(explanation.confidence=0, summary="LLM 不可用")。

---

## 11. 测试策略（TDD）

- **validsql**：每检查单测，pass/fail SQL 夹具（含陷阱：文本列聚合、编造列、无 JOIN 多表、写操作）。
- **normalize**：单测日期模式（过去三年/连续季度/最近一周）、单位、top-k；意图分类单测（三类 intent 的判定，含 out-of-scope 陷阱输入）；LLM 部分用固定响应 mock。
- **backend**：mock OpenAI 客户端，验证消息装配 + 结构化解析。
- **rag**：schema_retriever/fewshot 在固定小语料上测召回排序。
- **loop**：mock backend（确定性响应序列）做集成测——覆盖：out_of_scope 拒答早退、澄清早退、一次成功、自纠错 1 轮成功、用尽预算、validsql 拦截。
- **eval/runner**：toy gold/pred 测执行准确率与 F1 计算。
- 全部 `pytest`；现有 45 个数据层测试不得回归。

---

## 12. 前置任务（Task 0，评测基板）

Agent 代码数据无关，但评测集需冻结基板。**先做**：
1. 扩财务：sina 直连（`stock_financial_report_sina` / `stock_financial_analysis_indicator`，未被限流），把 income/balance/cashflow/financial_indicator 从 2 股扩到 ~30–50 股（蓝筹+多板块可识别名），写入 `data/live.duckdb`。
2. 冻结：`make eval-freeze` 把 live 子集冻结到 `data/eval.duckdb`（随仓提交）。**冻结 as-of** = 扩展后库中存在的最近完整季报截止日（目标 2025-12-31 或 2026-03-31，扩展后按实际存在确定）。
3. 评测集 150 题 gold_sql 必须在冻结的 eval.duckdb 上可执、有确定结果。

（daily_quote 仍限流、行业元数据仍缺 —— 不影响财务筛选/单股深查/板块行情/宏观/事件类评测题。）

---

## 13. 红线（承自 design.md §11，不变）

- ❌ 冒认 Hermes/GRPO 任何数字（54%→93%、87.3% 等）；本项目数字全部 `make eval` 实测。
- ❌ 虚构用户数/star/流量；数据来源明确为 akshare（MIT）。
- ✅ ablation 表每行真实测出，标注「自建冻结集、非跨域基准」。

---

## 14. 未决（实现期定）

1. 冻结 as-of 具体日期（Task 0 扩展后定）。
2. demo 形态 Gradio vs Streamlit（本 spec 外，单独规划）。
3. `clarify` 的必填槽规则清单（实现期随评测题打磨）。
