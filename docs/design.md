# 盘问 (PanWen) · 设计文档 v1

> **一句话定位**：用中文自然语言查询 A 股数据的开源 Text-to-SQL Agent——从历史行情/财报里做真实的财务筛选、相对估值、板块分析，并通过执行反馈自纠错、确定性校验防幻觉。
>
> - 中文名：**盘问**　·　英文名/repo：**PanWen / panwen-agent**　·　Slogan：用中文问盘：A 股自然语言查询 Agent
> - 文档日期：2026-08-12　·　状态：设计定稿，待评审
> - 这是项目的**单一事实源（设计层）**。实现计划（writing-plans）以本文件为准。

---

## 1. 背景与目标

### 1.1 为什么要做这个项目

作者背景：6 年 NLP / 向量检索 / 大规模系统工程（BERT 多任务 NL2SQL、SimCSE 微调、向量检索、Spark 图计算、C++ 图像算法），已完成一个生产级 Agent 旗舰项目 **ggb-fable**（GeoGebra AI 画布助手，已部署上线）。现转型 AI Agent 工程师。

盘问的战略价值：**用 agent 时代的实现，重做作者最熟悉的 NL2SQL 领域**——把 2020 年的 BERT 多任务 NL2SQL 升级为「LLM Agent + 确定性校验 + 严谨评估」，并直接吃透其「不公平优势」（中文归一化、schema 类型约束解码、向量检索）。

### 1.2 双目标

1. **求职作品集**：补齐 ggb-fable 之外的空白——**结构化数据 Agent** + **评估严谨性** + **深度 RAG**，并产出一个有真实用户的开源项目（远比"精致作业"有说服力）。
2. **开源影响力**：做成真实开发者/投资者能用起来的活工具（攒 star、可写博客、面试有料可聊）。

### 1.3 诚实底线（铁律，贯穿全项目）

- **只写自建冻结集上真实跑出的指标**，全部 `make eval` 可复现；对标基准数字明确标注为"基准对比"，**绝不冒认 SOTA**。
- 参考了 Hermes V3（Swiggy）的 few-shot 检索思路、GRPO 微调复盘（AWS）的奖励/超时教训——但 54%→93%、87.3% 等**都是人家的数字，只字不挪用**。
- 简历/面试口径与项目口径一致；项目所有数字建成后单独登记进简历素材库 `04_指标台账.md`。

---

## 2. 用户与场景

### 2.1 典型用户

| 用户 | 核心诉求 |
|---|---|
| 散户 / 个人投资者 | 盘后复盘、自然语言做财务筛选与对比，省去写 SQL/代码 |
| 研究 / 量化入门者 | 快速做财务筛选；把生成的 SQL 拿回自己系统跑 |
| 金融学生 / 学习者 | 学财务分析 + 学 SQL（看 Agent 生成的 SQL）|
| 开源开发者 | fork 框架到自己的领域，或贡献新数据维度 / 工具 |

### 2.2 使用流

1. **一次性查询**（核心，Phase 1）：中文问题 →（缺信息则主动澄清）→ 生成 SQL → ValidSQL 校验 → 只读执行 → 输出【结果表 + SQL + 解释（假设 + 置信度）】，可选简单图表。
2. **多轮分析**（Phase 2）：「白酒近三年 ROE」→「那把 PE 也加上」→「按 ROE 排序」。
3. **实时补充**（Phase 2）：查完结构化数据后，Agent 调 `search_news` 补最新公告/研报/快讯。
4. **导出**：复制 SQL 到自己量化系统 / 导出结果 CSV。

### 2.3 产品能力（数据 → 用户能问什么）

有了 MVP 数据域，这些**真实、多表、有洞察**的自然语言查询成立（分析师/投资者真会问，非玩具 count）：

| 能力类 | 示例问题（→ 所需 JOIN） |
|---|---|
| 财务筛选 | 「白酒行业**连续三年 ROE>15%**的公司」（行业 × 财务时序）|
| 相对估值 | 「今天**涨停**的股票里**市盈率最低**的五只」（行情 × 估值）|
| 板块横向 | 「**申万一级各行业**今年涨跌幅排名」（行情 × 行业，聚合）|
| 时序增长 | 「近五年**每年净利润都增长**的公司」（财务时序）|
| 多维交叉 | 「**连续三年分红且股息率>5%**的消费股」（财务 × 分红）|
| 资金/情绪 | 「今天**龙虎榜**上机构净买入最多的票」「**融资余额**连续一周增长的股票」|

> 作者的**中文归一化**（"连续三年/涨停/最低五只/白酒行业"）与**schema 类型约束**（ROE/PE 数值列、行业 文本列）几乎逐条对应这些查询——这是不公平优势的直接兑现。

---

## 3. 数据层

### 3.1 数据域与稳定性

🟢稳定（主力源多年稳定）·🟡中（偶有变动/口径需注意）·🔴受限（监管/断供）

| 域 | 维度 | akshare 代表接口 | 稳定性 | MVP？ |
|---|---|---|---|---|
| **① 基础/行情** | 股票基础信息、交易日历、日/周/月 K 线（后复权）、实时快照、指数行情、ST 标记 | `stock_zh_a_hist` · `stock_zh_a_spot_em` · `stock_zh_index_daily` | 🟢 | ✅ |
| **② 财务** | 三大报表×多报告期、财务指标（ROE/毛利率/PE/PB…）、业绩预告/快报 | `stock_financial_report_sina` · `stock_financial_analysis_indicator` · `stock_em_yjbb` | 🟢 | ✅ |
| **③ 行业/板块** | 东财行业板块行情+成分股、东财概念板块 | `stock_board_industry_*_em` · `stock_board_concept_*_em` | 🟢 | ✅ |
| **④ 资金面** | 融资融券余额/明细、龙虎榜、个股资金流 | `stock_margin_*` · `stock_lhb_*` | 🟢/🟡 | ✅（融资融券+龙虎榜）|
| **⑤ 公司事件** | 十大股东/流通股东、限售解禁、分红送转、股东人数 | `stock_gdfx_*_em` · `stock_dividend_cninfo` | 🟡 | ✅（批次，顺手加）|
| **⑥ 宏观** | CPI/PPI/GDP/PMI/货币供应量 | `macro_china_*` | 🟢 | ✅ |
| ~~北向资金~~ | ~~沪深港通资金流向~~ | ~~`stock_hsgt_*`~~ | 🔴 | ❌ 移出（见下）|

**北向资金处理**：`stock_hsgt_*` 自 **2024-08-19 起实时盘中数据停止披露**（港交所监管调整），历史有缺口。决定：**不进结构化库**，改由 `search_news` 资讯工具**定性补充（辅助）**。

### 3.2 数据获取架构（全量回填 + 每日增量）

**核心结论：全历史可抓，但"一次性"是批量任务不是一次调用；每日增量反而极便宜。**

两类数据，两种抓法：

| 类型 | 抓法 | 调用量 |
|---|---|---|
| **个股级历史**（日 K 线、个股财报）| 按股票循环，每只 1 次调用拿全历史；财报可按报告期批量（每期分页一次拿全市场）| 日 K 线 ~5000 调用；财报按期更省 |
| **全市场级**（指数/板块/融资融券/龙虎榜/宏观/业绩快报）| 按日或按报告期，单次/分页调用 | 调用量小 |

**现实约束与对策：**
- akshare 打东财/新浪/同花顺上游 → 会被限流/偶发封 → 必须**节流（sleep）+ 重试（指数退避）+ 断点续传（持久化已抓 code/报告期，挂了能续）**。
- 全量回填是**数小时级夜间任务**（建议 cron 夜间跑），非分钟级。
- 数据量：~2500 万行日行情 → DuckDB 列存轻松，**瓶颈在抓取吞吐不在存储**。
- **复权**：存**后复权**（后复权历史值在新除权后不变，稳定；前复权历史会变需重抓）。进阶可存"不复权 + 除权因子按需算"，MVP 先后复权。

**每日增量（便宜）：**
- 日行情：`stock_zh_a_spot_em` **一次调用返回全市场 ~5000 只最新快照** → 1 调用/天。
- 财报：披露季按报告期补抓；板块/融资融券/龙虎榜/宏观/指数：按日单次。
- **幂等 upsert**（`ON CONFLICT` by (code,date) / (code,report_period)）+ cron 定时 + 失败告警。

**双库分离：**
- `eval.duckdb`——冻结到某日期的子集快照，**随仓库提交**，`make eval` 复现所有指标。
- `live.duckdb`——每日刷新，喂 demo（gitignore，可重建）。

**入库只发脚本不发数据**：行情/财报是事实数据无版权；仓库发 akshare→DuckDB 入库脚本（`make data-backfill` / `make data-incremental`），任何人可复现。

---

## 4. 系统架构

### 4.1 Agent 闭环（单 Agent，ReAct 式 + 预算控制）

```
中文自然语言问题
 → ① 中文归一化（日期"过去三年/连续季度"·百分比·金额·单位·top-k·实体"白酒/创业板"）
 → ② 完整性校验：缺信息 → 主动澄清（不瞎猜，如"白酒行业"指申万一级还是二级？）
 → ③ Plan-then-SQL：先出中间逻辑 / 意图（提复杂查询准确率）
 → ④ 双路 RAG：a) Few-shot 检索自建(问题→SQL)语料  b) Schema 检索相关表/字段
 → ⑤ SQL 生成（plan + few-shot + schema 子集 → LLM）
 → ⑥ ValidSQL 确定性校验（见 §5）
 → ⑦ 只读 DuckDB 执行（ThreadPoolExecutor 超时，防笛卡尔积卡死）
 → ⑧ 失败信号 → rootCause 归因 → 自纠错（预算 N 轮，"修上游不盲试"）
 → ⑨ 解释层：SQL + 依据假设 + 置信度 + 纠错轨迹
```

设计要点（复刻/借鉴 ggb-fable 与两篇参考文章）：
- **预算控制**：自纠错最大 N 轮（参考 ggb-fable 的轮次预算），防止无限循环。
- **错误归因**：执行失败带 `rootCause`（"上游根因"），引导 Agent 修 schema 误解而非逐条盲试——直接搬 ggb-fable 的 `execute_command` 机制。
- **解释层**：展示生成 SQL 所依据的假设 + 结果置信度（借鉴 Hermes V3），提升非技术用户信任；与 ggb-fable 的 TracePanel 一脉相承。

### 4.2 LLM 后端

复用 ggb-fable 的 `AgentBackend` 抽象：chat / vision 可注入，适配 **DeepSeek / GLM** 等多模型，同一套 Agent 循环支持平台 Key 与 BYOK 双模式。

### 4.3 工具清单（Agent 可调用）

| 工具 | 用途 | 阶段 |
|---|---|---|
| `retrieve_schema` | RAG：检索相关表/字段（控制 token）| P1 |
| `retrieve_fewshot` | RAG：检索自建(问题→SQL)相似示例 | P1 |
| `generate_sql` | LLM 生成 SQL（含 plan 步骤）| P1 |
| `validate_sql` | ValidSQL 确定性校验 | P1 |
| `execute_sql` | 只读 DuckDB 执行（超时）| P1 |
| `clarify` | 信息不全时向用户追问 | P1 |
| `search_news` | RSSHub/东财 在线检索公告/研报/快讯（替代北向等实时定性信息）| P2 |

---

## 5. 确定性校验层 ValidSQL

> 这是防幻觉与"工程严谨度"的核心，也是面试重点。用 **sqlglot** 做 AST 分析（SQLite/DuckDB 方言）。

1. **AST 白名单**：只允许只读 `SELECT`；禁止 DDL/DML（`INSERT/UPDATE/DELETE/DROP/ALTER…`）。
2. **表/列存在性**：引用的表/列必须在当前 schema 中（反幻觉，拦 LLM 编造的列名）。
3. **类型约束**（直接迁移作者老 NL2SQL 的 schema 类型约束解码器）：
   - 文本列（名称/行业/板块）**禁止聚合**（AVG/SUM 无意义）。
   - 数值列（ROE/PE/价格/金额）**允许范围比较与聚合**。
4. **防笛卡尔积**：多表查询必须有 JOIN/ON 条件；带行数估算拦截（避免 `FROM A,B,C` 交叉积）。**借鉴 GRPO 文章的工程坑**。
5. **参数化绑定**：用户提到的值走参数化，防注入与解析错误。
6. **执行超时**：`ThreadPoolExecutor` + `.result(timeout=30)`，超时返回失败信号进入自纠错。**借鉴 GRPO 文章（一条笛卡尔积 SQL 卡死 8 卡训练 30 分钟）**。

---

## 6. RAG（双路检索）

- **Schema 检索**：对库的表/列描述做 embedding，按问题召回相关 schema 子集（控制进 prompt 的 token）。
- **Few-shot 语料检索**：自建 (问题 → SQL) 语料库（即 eval 冻结集中的 question→gold SQL 对），按问题的自然语言 embedding 检索相似示例作 few-shot。**借鉴 Hermes V3 的最大杠杆**——我们自建集天然带问题文本，比 Hermes 反推 NL 更干净。
- 两路复用同一套 embedding 基建（参考 ggb-fable 的 embedding 预计算 + 缓存）。

---

## 7. 评估体系（项目差异化核心）

> ggb-fable 缺评估，盘问把"严谨评估"做成主打卖点。

### 7.1 冻结评测集

- 自建 **150–300 题**，按难度分层（对标 BIRD 难度划分）：简单单表 / 多表 JOIN / 时序聚合 / 复杂嵌套。
- 基于 `eval.duckdb` 冻结快照，每题有 gold SQL 与期望结果。`make eval` 一键复现。

### 7.2 指标

- **执行准确率（主指标，ground truth）**：预测 SQL 与 gold SQL 在库上执行结果一致。**借鉴 GRPO 文章核心教训——执行正确性是唯一可信信号，结构相似/LLM-judge 只是代理，报告时标注局限。**
- **F1 软评分**：部分行匹配给 0~1 分（借鉴 GRPO 文章奖励设计），比硬 0/1 更细。
- **维度准确率面板**：按难度 / 按 SQL 结构（JOIN 数、子查询、聚合）切片。
- **自纠错增益**：单次生成 vs. N 轮自纠错的准确率提升。

### 7.3 逐组件增益 ablation（最强故事）

| 配置 | 执行准确率 / F1 |
|---|---|
| 1-shot baseline | _（实测填）_ |
| + Few-shot RAG | _（实测填）_ |
| + Plan-then-SQL | _（实测填）_ |
| + ValidSQL 校验 | _（实测填）_ |
| + 自纠错循环 | _（实测填）_ |

每行真实测出 → 简历可写"逐组件贡献度"，面试讲清每个机制值多少。

### 7.4 跨域对标（Phase 3，可信核对）

拿 **BIRD 金融子集**跑一遍，证明方法不是过拟合到自建集。数字明确标注为"基准对比"。

---

## 8. Phase 2 扩展

### 8.1 多库业务路由

数据天然分库（行情库 / 财务库 / 资金面库 / 指数库 / 宏观库）。**第一层域识别**（keyword + embedding 识别业务域，缩小到目标库）→ **第二层 Schema 检索**（在目标库内检索相关表/字段）。**借鉴 GRPO 文章的两层 RAG Agent。** 重跑 ablation 证明路由贡献。

### 8.2 多轮会话记忆

跟踪会话状态，支持 follow-up（"那按行业拆呢"「把时间拉到五年」）。**借鉴 Hermes V3 的会话记忆。**

### 8.3 实时资讯工具 `search_news`

RSSHub/东财源（财经快讯、个股公告/资讯/研报、行业/策略研报）。**定位：在线检索工具，不是 SQL 数据源**——补结构化库答不了的"最新公告/研报/快讯/北向定性信息"。带**优雅降级**（源不可用则跳过，不阻塞主查询）。

> 定位情报：已有 [akshare-stockdata-plugin (for Dify)](https://github.com/shaoxing-xie/akshare-stockdata-plugin) 验证了"akshare 当数据源喂 AI"可行，但那只是 Dify 数据拉取插件，**不是带校验/自纠错/评估的 Text-to-SQL Agent**——盘问的差异化正在于此。

---

## 9. 技术栈与仓库结构

**技术栈**：Python · sqlglot（AST + SQLite/DuckDB 方言）· akshare（数据）· DuckDB（只读分析执行）· sentence-transformers/embedding（RAG）· DeepSeek/GLM（复用 ggb-fable `AgentBackend`）· pytest（eval）· Gradio/Streamlit（demo）· FastAPI（可选 API）。

```
panwen/
  data/
    ingest/        # akshare 抓取: backfill.py, incremental.py, schemas.py
    snapshots/     # eval.duckdb（随仓提交）, live.duckdb（gitignore，可重建）
  agent/
    loop.py        # 主循环 + 预算控制
    tools/         # retrieve_schema, retrieve_fewshot, generate_sql, validate_sql, execute_sql, clarify, search_news
    prompts/       # 版本化 prompt（v1, v2…）
  validsql/        # AST 白名单 / 类型约束 / 防笛卡尔 / 参数化 / 超时
  rag/
    schema_retriever.py
    fewshot_store.py
  eval/
    dataset/       # 冻结问题集（question, gold_sql, difficulty, tags）
    runners/       # exec_acc, f1, ablation
    panels/        # 维度准确率面板
  demo/            # Gradio/Streamlit
  api/             # FastAPI（可选）
  tests/
  docs/            # design.md, README, 博客
  Makefile         # make data-backfill / data-incremental / eval / demo
```

---

## 10. 分阶段路线（诚实控范围）

- **Phase 1（MVP，~3 周，spec 重点）**：全部🟢数据域 + 顺手的🟡批次（§3.1）；核心闭环（§4.1 ①–⑨，含解释层）；双路 RAG（§6）；ValidSQL（§5）；自建冻结 eval + 逐组件 ablation（§7）；最小 demo + README（含真实示例查询）。单库先跑通——这本身就是个能发的真实数据 OSS 项目。
- **Phase 2**：多库业务路由（§8.1）+ 多轮会话（§8.2）+ `search_news` 实时资讯工具（§8.3）；重跑 ablation。
- **Phase 3（影响力）**：BIRD 金融子集跨域对标（§7.4）+ 写博客推广 + 推广拉 star。

---

## 11. 诚实指标与红线

### 11.1 可写（项目建成后，全部 `make eval` 可复现）

- 自建冻结集上的执行准确率 / F1 / 维度面板 / 逐组件 ablation 数字。
- BIRD 对标数字（明确标注"基准对比"）。

### 11.2 禁止

- ❌ 冒认 Hermes / GRPO 文章的任何数字（54%→93%、87.3% 等）。
- ❌ 虚构用户数 / star 数 / 生产流量。
- ❌ 把 akshare/RSSHub 当作自研数据源；明确陈述数据来自 akshare（MIT）/RSSHub。

---

## 12. 未决 / 待确认

1. MVP 是否纳入🟡批次维度（龙虎榜/业绩快报/十大股东）——当前默认**纳入**（单次/按期调用，近零成本），可在评审时调整。
2. eval 冻结快照的"冻结日期"——待数据回填后确定（建议取一个财务披露完整的季报截止日）。
3. demo 形态：Gradio vs Streamlit——Phase 1 实现时定。
4. 复权存储：**已定**——复权数据极好拿（`stock_zh_a_hist` 的 `adjust` 参数直接返回复权价，与抓 raw 同一次调用、零额外难度），故 MVP **直接抓并存储后复权(hfq)**；应用层默认用后复权。原始不复权 / 复权因子 MVP 不抓（进阶再考虑）。注：PE/ROE 等指标直接取自财务指标接口，不靠存储的复权价计算，故只存 hfq 不丢信息。

---

## 13. 参考来源

- **Hermes V3（Swiggy）**：基于历史查询的 few-shot 向量检索（54%→93%）、会话记忆、orchestrator 拆步骤、解释层、主动澄清。InfoQ：https://www.infoq.com/news/2026/01/swiggy-hermes-conversational-ai/
- **32B Text2SQL GRPO 微调复盘（AWS）**：ground-truth 奖励不可替代、F1 软评分、SQL 执行超时防笛卡尔积、两层 RAG Agent。知乎：https://zhuanlan.zhihu.com/p/2015523496889964219
- **akshare 文档**：https://akshare.akfamily.xyz/data/index.html · https://akshare.akfamily.xyz/data/stock/stock.html
- **RSSHub 金融路由**：https://rsshub-doc.pages.dev/finance
- **akshare-stockdata-plugin (Dify)**（定位参照）：https://github.com/shaoxing-xie/akshare-stockdata-plugin
- **作者既有项目**：ggb-fable（Agent 闭环/`AgentBackend`/TracePanel/RAG 抽象复用源）、BERT 多任务 NL2SQL（schema 类型约束解码器迁移源）。
