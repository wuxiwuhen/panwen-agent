# 盘问 / PanWen

> 用中文问盘：A 股自然语言查询 Agent

**状态 / Status:** Phase 1 数据层 + Phase 2 Agent 核心（Agent Core）。数据层（akshare → DuckDB）已在真实数据上端到端验证；Agent 核心层（9 步确定性管线 + ValidSQL + 双路 RAG + 有界自纠错 + 冻结评测集）已实现并通过 98 项单元/集成测试（pytest 全绿）。**端到端问答需自备 LLM API key 跑 `make eval` 实测指标**（指标为自建冻结集实测，非跨域基准，详见下文「诚实口径」）。

---

## Agent 核心层（Plan 2）

在数据层之上构建了端到端中文 Text-to-SQL Agent：

- **9 步确定性管线**：① normalize（规则+LLM 混合，含意图/范围门）→ ② dispatch（确定性三分支：out_of_scope 拒答 / needs_clarify 澄清 / sql_answerable 继续）→ ③④ 双路 RAG 上下文 → ⑤ plan+generate（单次 LLM 调用）→ ⑥ ValidSQL 校验 → ⑦ 只读执行（超时保护）→ ⑧ 有界自纠错（N=3）→ ⑨ 解释。
- **ValidSQL（sqlglot AST 6 项）**：只写白名单 / 表列存在 / 类型约束（文本列禁聚合）/ 防笛卡尔 / 参数化 / 执行超时。**诚实口径：6 项检查全部运行；其中「参数化」检查（check 5）在 MVP 为顾问式（记入 trace 但不触发自纠错），因为自建评测集的 gold SQL 用裸字面量（如 `code='600519'`）；生产硬化将通过参数化执行（DuckDB 命名参数 + `?` 绑定）将其提升为阻断式。**
- **双路 RAG**：schema_retriever（常开，控 token、降列幻觉）+ fewshot_store（可 toggle），均用 `BAAI/bge-large-zh-v1.5`（本地、离线、免费），预计算缓存到 `data/rag_cache/`（gitignore）。
- **LLM 后端**：OpenAI 兼容（DeepSeek-V3 主 / GLM-4.6 备），`AgentBackend` 抽象注入。
- **冻结评测集**：starter 25 题（21 含 gold_sql + 4 out_of_scope 陷阱），跨 4 难度层；gold SQL 全部在冻结 `eval.duckdb`（as-of 2026-06-30）上可执且返回非空值。执行准确率（主）+ F1 软评分 + 逐组件 ablation（baseline → +Few-shot → +ValidSQL → +自纠错）。

### 跑评测 / Run eval

```bash
pip install -e ".[dev,rag]"   # 拉取 torch + sentence-transformers
export DEEPSEEK_API_KEY=...   # 或 GLM_API_KEY
make eval                     # 首次会下载 bge-large-zh-v1.5（~1.3GB）
```

### 诚实口径 / Honest claims

- **指标全部实测，绝不编造。** 上述能力已通过 98 项单元/集成测试验证（管线分支、ValidSQL 各检查、RAG 召回、自纠错预算、评分边界）。**端到端执行准确率 / ablation 百分比须由你在本地 `make eval` 实测**——本仓库不预填任何准确率数字。
- 跨域基准（如 Hermes 54%→93%、GRPO 87.3%）是**他人成果**，仅作对比参照，绝不冒认为本项目指标。
- ValidSQL check 5（参数化）当前为顾问式（见上），不声称其在 MVP 阻断。
- 交互式 Demo UI（Gradio/Streamlit）为独立后续计划，不在 Plan 2 内。

---

## 数据层（akshare → DuckDB）

盘问的数据来自 [akshare](https://akshare.akfamily.xyz)（MIT，免费无 token）。仓库**只发入库脚本不发数据**。

```bash
make install
make seed-backfill    # 开发: ~10 只种子快速验证
make data-backfill    # 生产: 全市场全量回填(数小时,建议夜间;支持断点续传)
make data-incremental # 每日增量(spot 全市场快照,1 调用)
make eval-freeze      # 冻结 live→eval,随仓提交以保证指标可复现
```

- 日行情存**后复权(hfq)**。
- ROE / ROA / 毛利率 / 净利率 / 资产负债率 取自财务指标接口 (`financial_indicator`)；PE / PB 取自实时行情快照 (`spot_snapshot`)。
- `data/live.duckdb`（gitignore，每日刷新）与 `data/eval.duckdb`（冻结，随仓提交）双库分离。
- 数据稳定性说明：北向资金因 2024-08-19 监管调整停止实时披露，本数据层不含此维度（改由资讯工具定性补充，见 Plan 2）。

### 真实数据验证 (2026-08-12)

数据层已在真实 akshare 数据上端到端跑通（2 只样本股 `600519/000001` + 全市场 oneshot）。下列为**实测行数**（非估算），回填前先 `export NO_PROXY='*' no_proxy='*'` 直连：

| 表 / Table | 域 | 实测行数 | 说明 |
|---|---|---|---|
| `stock_basic` | 基础 | 5,543 | 全市场 code/name（元数据列见下「已知限制」） |
| `trade_calendar` | 基础 | 8,797 | 历史交易日历 |
| `daily_quote` | 行情 | 680 | 2 股 · 后复权 · 分段 `20230101–20240601`（全历史分块见下） |
| `income_statement` | 财务 | 224 | 2 股（≈112/股） |
| `balance_sheet` | 财务 | 221 | 2 股；`total_equity` 非空，恒等式 `资产=负债+权益` 成立 |
| `cashflow_statement` | 财务 | 201 | 2 股（≈100/股） |
| `financial_indicator` | 财务 | 90 | 2 股（≈45/股，ROE/ROA/毛利率/净利率/资产负债率） |
| `performance_express` | 财务 | 11,668 | 全市场 · 报告期 20231231 |
| `margin_daily` | 资金面 | 2,000 | SSE 融资融券（约最近 8 年，单次上限见下） |
| `dragon_tiger` | 事件 | 167,832 | 约 11 年龙虎榜明细 |
| `industry_board` | 板块 | 90 | 行业板块列表（同花顺 ths，90 个二级行业） |
| `concept_board` | 板块 | 375 | 概念板块列表（同花顺 ths） |
| `industry_board_daily` | 板块 | 1,700 | 行业板块日线（ths，5 板块有界验证；全 90 板块见下） |
| `macro_series` | 宏观 | 223 | CPI 同比（`2026年07月份`→`2026-07-01`） |

**数值健全性自检（真实数据）：** 贵州茅台 2026Q1 营收 547.0 亿 / 净利润 281.5 亿；资产负债表 `资产总计 3199.2 亿 = 负债合计 387.8 亿 + 所有者权益合计 2811.4 亿`（会计恒等式成立）；所有 `report_date` 规范化为 `YYYY-MM-DD`。这些是**自建数据层的实测产出**，非任何论文/SOTA 的对标数字。

### 已知限制 / Known limitations

- **网络代理坑 (macOS 系统代理):** akshare/requests 会自动继承 macOS 系统代理设置。若本机开了代理（如 `127.0.0.1:7897`），eastmoney push2/datacenter 等域名常被代理拦截导致 `ProxyError` / `RemoteDisconnected`。回填前先直连：`export NO_PROXY='*' no_proxy='*'`（`scutil --proxy` 可查当前系统代理）。这是**环境问题不是代码缺陷**，开放网络下多数端点正常。
- **列名校准状态 (2026-08-12 实测):** 以下 rename_map 已对真实数据逐列校准（VERIFIED，回填正常落库）：行情（`stock_info_a_code_name` / `tool_trade_date_hist_sina` / `stock_zh_a_hist` 后复权）、三大报表与财务指标（`stock_financial_report_sina` / `stock_financial_analysis_indicator`）、业绩快报（`stock_yjbb_em`）、融资融券（`stock_margin_sse`）、龙虎榜（`stock_lhb_detail_em`）、宏观 CPI（`macro_china_cpi`）、行业/概念板块列表与板块日线（改接同花顺 ths：`stock_board_industry/concept_name_ths` / `stock_board_industry_index_ths`）。**仍 UNVERIFIED**（eastmoney 端点限流/不可达）：行情快照估值（`stock_zh_a_spot_em`，PE/PB/市值/换手率）、板块成分股（`stock_board_*_cons_em`，ths 无对应端点）、十大股东（`stock_gdfx_holding_detail_em`）。这些表的 rename_map 沿用文档 schema 猜测，待 eastmoney 限流解除或开放网络用 `scripts/probe_akshare.py` 重探测 —— `map_columns` 会静默丢弃未匹配列，列漂移会导致整张表写空。
- **eastmoney 限流（反爬）与 provider 切换:** 真实回填时 eastmoney push2/datacenter 端点会对本 IP 临时限流（高频请求后连日行情 `push2his` 也会 `RemoteDisconnected`），数小时后解除或换 IP 即恢复。故板块 LIST/DAILY 已**改接同花顺(ths, 10jqka)**——ths 是独立数据商、不受 eastmoney 限流影响，作全量回填的稳健兜底（但 ths 不提供成分股与 PE/PB 估值，这两类仍需 eastmoney）。
- **stock_basic 元数据不完整:** canonical schema 声明了 `listing_date/board/industry/is_st/delist_date`，但 `stock_info_a_code_name` 实测**仅返回 `code/name`**，这些元数据列当前恒为 NULL。完整元数据需换端点（如 `stock_info_sh_name`/交易所列表）或单独补全，列为 MVP 后增强项。
- **龙虎榜主键收敛:** `dragon_tiger` 主键为 `(code, date)`，`reason`（解读）降为可空属性。原因：真实 lhb 数据的「解读」字段存在空值，作为主键分量会触发 NOT NULL 约束整批失败；`(code, date)` 是稳定自然键。同一股同日因多原因上榜按 last-write-wins 合并（`reason` 取末行值）。
- **资产负债表总权益列:** `total_equity` 取 `所有者权益(或股东权益)合计`（= 归属于母公司股东权益合计 + 少数股东权益）。同端点另有裸列「所有者权益」实测**恒为空**，不可误用。该列名含**半角**括号 `( )`（非全角），rename_map 须逐字精确。
- **日行情全历史分块:** `stock_zh_a_hist` 单次请求 2010→2099 全历史偶被服务端掐断（`RemoteDisconnected`）。当前默认 `arg_builder` 仍是全范围；若回填遇断流，可改用分段日期（实测 `20230101–20240601` 稳定）。按年/段自动分块为生产增强项。
- **融资融券行数上限:** `stock_margin_sse` 单次调用上限约 2000 行（约最近 8 年）；完整历史需要按年分窗口抓取（计划在 MVP 后增强）。
- **每日增量范围:** `run_daily` 当前仅刷新 `spot_snapshot`（全市场快照，1 次调用）；融资融券/龙虎榜/宏观等在下次全量 `data-backfill` 时刷新。
- 北向资金因 2024-08-19 监管调整停止实时披露，本数据层不含此维度。
