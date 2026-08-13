# Demo UI 设计文档（Plan 3）

> 单一事实源（本文件）。实施计划由 writing-plans 据此生成。

## 1. 目标与范围

**目标：** 为「盘问 PanWen」构建一个 Gradio Web UI，让用户输入中文 A 股问句，调用 `panwen/agent/loop.py:run_query`，展示生成的 SQL、结果表、解释（置信度/假设）、9 步推理 trace，并暴露 `AgentConfig` 开关用于现场对比。可部署到 Hugging Face Spaces 作为求职作品集的公开可点链接。

**为什么：** 当前只能跑 `pytest`/`make eval` 看数字，无法向面试官/HR 实际演示 Agent 工作。trace 是"真 Agent"（非 prompt→SQL）的核心卖点。

**范围（in-scope）：**
- Gradio Blocks 单页应用（两个 Tab：问答 / 关于架构）。
- 接入现有 `run_query`，**零改动** `panwen/agent/`、`panwen/rag/`、`panwen/validsql/`、`panwen/eval/` 生产代码。
- `AgentConfig` toggle（`use_fewshot`/`use_validsql`/`use_selfcorrect`）+ 示例问句按钮。
- HF Spaces 部署所需的 `app.py`（根）+ `requirements.txt` + 文档。
- TDD 单元测试（纯逻辑层，不依赖浏览器/真实 LLM）。

**非目标（out-of-scope，本 Plan 不做）：**
- trace **实时流式**（管线逐步 yield）—— 列为加分项，单独一轮（见 §6）。
- 多用户并发/鉴权/速率限制（单用户 demo）。
- 图表/可视化（K 线、柱状图）——结果表已足够；图表为后续增强。
- 连 `live.duckdb` 的**部署**版（live 库 gitignore 不可部署）；本地可经环境变量切 live（见 §7）。
- 移动端适配。

## 2. 锁定决策

| # | 决策 | 选择 | 理由 |
|---|---|---|---|
| 1 | UI 框架 | **Gradio Blocks** | DataFrame/Accordion/Checkbox 原生契合 `AgentResult`；HF Spaces 一等公民；spec 原已列名 |
| 2 | 部署 + 数据 | **HF Spaces 公开链接 + 冻结 `eval.duckdb`** | live 库不可部署；eval 库 22MB 可复现、随仓提交 |
| 3 | Demo 深度 | **完整 trace + 配置 toggle** | 求职卖点全开（推理过程 + 现场 ablation） |
| 4 | trace 呈现 | **MVP：完成后回放**；流式为加分项 | 零改动 `loop.py`、快速可演示；流式后续加 callback hook |
| 5 | Space 依赖策略 | **方案 A：`requirements.txt` 直列运行时依赖，不含 akshare，不 `pip install -e .`** | 查询路径不 import akshare（已验证）；不动 pyproject/数据层 |

## 3. 架构与文件结构

拆成职责单一的小模块。Gradio 仅是其中一层；可测试逻辑全部下沉到无 Gradio 依赖的纯模块。

| 文件 | 职责 | 关键签名 |
|---|---|---|
| `panwen/ui/runtime.py` | 后端装配 + 懒加载单例；复用 [run_eval.py:21-40](scripts/run_eval.py) 的构造法 | `Runtime(conn,backend,rag,fewshot)`；`build_runtime(db_path,provider,embedder=None)->Runtime`；`get_runtime(...)->Runtime`（懒单例）；`ask(question,config,runtime=None)->AgentResult` |
| `panwen/ui/render.py` | **纯函数**：`AgentResult` → Gradio 可渲染结构 | 见下 |
| `panwen/ui/config_bridge.py` | UI toggle 布尔 → `AgentConfig` | `to_config(use_fewshot,use_validsql,use_selfcorrect,schema_topk=None)->AgentConfig` |
| `panwen/ui/examples.py` | 从 eval 集（`questions.yaml`）取 answerable 题，挑示例 | `example_questions(path=DATASET,limit=8)->list[str]` |
| `panwen/ui/app.py` | `build_app()->gr.Blocks`：布局 + 事件接线 | 调用上述四模块 |
| `app.py`（仓库根） | **薄入口**，HF Spaces 跑这个 | `demo=build_app(); demo.launch(server_name="0.0.0.0",server_port=7860)` |
| `requirements.txt`（根） | Space 运行时依赖（**不含 akshare**，见 §7） | gradio/duckdb/pandas/sqlglot/openai/pyyaml/sentence-transformers/torch |
| `README.md` | 加 `## Demo UI` 段 | 本地运行 + HF Spaces 部署步骤 + demo URL + 诚实口径 |
| `tests/ui/*` | TDD 测试 | 见 §9 |

### `render.py` 纯函数契约（无 Gradio 依赖，最易测）

```python
def result_table(result: AgentResult) -> tuple[list[str], list[list]]:
    """(headers, rows) 供 gr.DataFrame。rows 为空时 headers 也为空。"""

def sql_block(result: AgentResult) -> str:
    """SQL 的 markdown 代码块；result.sql 为 None 时返回 ''。"""

def trace_rows(result: AgentResult) -> list[list]:
    """[[stage, '✓'|'✗', detail, rootCause_or_''], ...]，顺序同 result.trace。"""

def explanation_md(result: AgentResult) -> str:
    """置信度 badge + 假设列表 + summary 的 markdown；explanation 为 None 时返回 ''。"""

def status_reply(result: AgentResult) -> str:
    """status != 'answered' 时返回 result.reply（澄清反问 / 拒答 / 错误概述）；
    status == 'answered' 时返回 ''。失败步的 rootCause 由 trace_rows 单独展示。"""
```

## 4. 数据流（一次查询的生命周期）

1. 用户输入问句（或点示例按钮填入）→ Gradio 触发 handler。
2. handler 读 toggle 值 → `config_bridge.to_config(...)` 生成 `AgentConfig`（`use_plan` 恒 True）。
3. handler 调 `runtime.ask(question, config)`：
   - `ask` 取懒单例 `get_runtime()`（**首次调用**触发 bge 加载 ~1.3GB，期间 UI 显示"模型加载中…"）。
   - 调 `run_query(question, conn, backend, rag, fewshot, config)` → `AgentResult`。
4. handler 调 `render.*` 把 `AgentResult` 转成各组件的值。
5. UI 更新：SQL 代码块、结果表（DataFrame）、解释、trace（Accordion/表）、status 回复。

handler 返回一个 tuple，对应 `outputs=[sql, table, explanation, trace, reply]` 的更新值。

## 5. UI 布局（Gradio Blocks，两 Tab）

```
┌─ 盘问 PanWen · A股自然语言查询 Agent ───────────────────────────┐
│ [示例] 茅台近三年ROE │ 沪深300成分股 │ 行业板块涨幅 │ ...        │
│ ┌──────────────────────────────────────┐ ┌─ 配置 toggle ──────┐ │
│ │  问句输入框                          │ │ ☑ Few-shot         │ │
│ │                                      │ │ ☑ ValidSQL         │ │
│ │                        [ 查询 Ask ]  │ │ ☑ 自纠错           │ │
│ └──────────────────────────────────────┘ │ schema top_k 滑块  │ │
│ ┌─ 生成的 SQL ──────────────────────────┐ └────────────────────┘ │
│ │ SELECT code, report_date, roe ...     │                        │
│ ├─ 结果表 (DataFrame) ──────────────────┤                        │
│ │ code   | report_date | roe            │                        │
│ ├─ 解释 ────────────────────────────────┤                        │
│ │ 置信度 0.82 · 假设：①"近三年"=2023-26  │                        │
│ ├─ 推理 trace ──────────────────────────┤                        │
│ │ ✓ normalize ② ✓ dispatch ③ ✓ rag ...  │                        │
│ └───────────────────────────────────────┘                        │
│ [Tab: 问答]   [Tab: 关于/架构 ← 9步管线·ValidSQL·诚实口径]       │
└──────────────────────────────────────────────────────────────────┘
```

**四种 `status` 分支 UX（render.status_reply + 条件渲染）：**
- `answered` → SQL + 表 + 解释 + trace 全开。
- `clarified` → 醒目展示 Agent 的反问（`reply`），无 SQL/表。
- `out_of_scope` → 礼貌拒答 + 说明范围（仅 A 股数据）。
- `failed` → 展示 `reply`（错误概述）；trace 中失败步的 `rootCause`（如 `ROOT_UNKNOWN_COL`）已在 trace_rows 暴露——展示优雅失败 + 自纠错耗尽，而非崩溃。

## 6. trace：MVP vs 流式（加分项）

- **MVP（本 Plan）：完成后回放。** `run_query` 返回完整 `AgentResult`（trace 是完整 list），UI 一次性渲染全部 9 步。**零改动 `loop.py`**，快、稳。
- **加分项（后续单独一轮）：实时流式。** 给 `loop.py` 加 `run_query_streaming(..., on_step: Callable[[TraceStep], None])` 变体，管线每完成一步回调一次，UI 逐步浮现。**视觉冲击大**（真·思考过程），但要改已 review 的 `loop.py`、有回归风险，故不进 MVP。

本 Plan 的 `runtime.ask` 签名保持稳定，流式轮只需新增 `ask_streaming` + 一个可订阅 handler，不破坏 MVP。

## 7. 部署（HF Spaces）+ 依赖策略

### 方案 A：`requirements.txt` 直列依赖，不含 akshare，不 `pip install -e .`

**已验证查询路径不 import akshare：**
- `panwen/data/__init__.py` 为空。
- `panwen/data/db.py` 只 import `duckdb` + `panwen.data.schema`。
- `import akshare` 仅在 `panwen/data/ingest/specs.py:38`，且只有入库脚本（`scripts/`）引用 `data.ingest`；查询路径（`run_query`→`panwen.data.db`）不触及。

**Space 部署机制：**
1. 建 Space（SDK: Gradio，CPU basic 16GB）。
2. Secrets 设 `DEEPSEEK_API_KEY`（或 `GLM_API_KEY`）。
3. push 本仓库到 Space repo（`data/eval.duckdb` 22MB 随仓提交 → Space 有；`live.duckdb` gitignore → 不推送）。
4. Space 跑根 `app.py`，装 `requirements.txt`，从仓库根 cwd `import panwen`（**不 `pip install -e .`**，故 pyproject 的 akshare 核心依赖不被拉入）。
5. 首次提问时下载 bge（~1.3GB），UI 显示"模型加载中…"。

`requirements.txt`（根）内容：
```
gradio>=4.0
duckdb>=1.1.0
pandas>=2.2.0
sqlglot>=23.0.0
openai>=1.0.0
pyyaml>=6.0
sentence-transformers>=2.7.0
torch  # CPU；Space 默认 CPU 版
```
（**不含 akshare**；`panwen` 从 cwd 导入，不需安装。）

**本地切 live 库（仅本地，不部署）：** `get_runtime` 默认 `db_path = os.environ.get("PANWEN_DB", "data/eval.duckdb")`。本地 `export PANWEN_DB=data/live.duckdb` 即连实时库。

## 8. 重资源启动策略（懒加载单例）

`runtime.get_runtime()` 懒构造：Space 一启动 UI 立刻可见，首次提问才加载 bge（~1.3GB，约 1-2 分钟），期间 UI 显示 loading。**不**在 import 时阻塞加载（否则 Space 卡 "Building" 数分钟才出 UI，体验差）。

`build_runtime(embedder=None)` 的 `embedder` 参数可注入 `FakeEmbedder`（已存在），使测试无需真实模型。

## 9. 测试（TDD，复用现有 FakeBackend/FakeEmbedder）

- `tests/ui/test_render.py` — 纯函数：构造 4 种 `status` 的 `AgentResult`，断言 `result_table`/`sql_block`/`trace_rows`/`explanation_md`/`status_reply` 的输出结构与边界（空 rows、None sql、None explanation、trace 为空）。
- `tests/ui/test_runtime.py` — `build_runtime`（注入 FakeBackend + FakeEmbedder + 内存 duckdb conn）→ `ask(question, config)` 断言：传入正确 `AgentConfig`、返回 `AgentResult`、**单例只构造一次**（第二次 `get_runtime` 不重建）。
- `tests/ui/test_config_bridge.py` — toggle 布尔 → `AgentConfig` 字段映射；`use_plan` 恒 True。
- `tests/ui/test_examples.py` — `example_questions()` 从真实 `questions.yaml` 取出、全部为 answerable、数量合理、可重复。
- `tests/ui/test_app_smoke.py` — `build_app()` 不抛异常、返回 `gr.Blocks`（布局烟雾测试；Gradio 胶水不深测）。
- `tests/ui/test_no_akshare_dep.py` — import `panwen.ui.runtime`/`app` 后断言 `"akshare" not in sys.modules`（守护 Space 轻量，防回归）。

**测试纪律：** 不真实调用 LLM/不下载 bge；全部用 FakeBackend + FakeEmbedder + 内存或 eval.duckdb（只读）。

## 10. 诚实口径（贯穿 UI，与 README/简历一致）

- "关于"Tab + 结果区底部明确：**演示跑在冻结 `eval.duckdb`（as-of 2026-06-30 快照）**；本地连 `live.duckdb` 看实时数据。
- ValidSQL check 5（参数化）在 MVP 为**顾问式**（不阻断）——如实写明，不声称阻断。
- **不预填任何准确率数字**；如展示指标，须来自用户本地 `make eval` 实测。
- 跨域基准（Hermes/GRPO）不冒认为本项目指标。

## 11. 已知限制

- **Space 冷启动下载 bge（~1.3GB）：** 免费 CPU Space 磁盘 ephemeral，每次冷启动重下，首次提问慢（~1-2 分钟）。缓解：Space 开启 persistent storage 缓存 `data/rag_cache/`（部署配置项，非代码）。
- **16GB RAM：** torch + bge-large + app 应能放下；若 OOM，降级 `bge-base`（会改检索结果，需重测，非默认）。
- **单用户：** 无并发/鉴权；demo 用途。
- **API 成本：** 每次查询多步 LLM 调用，消耗 DEEPSEEK 额度；Space Secret 须设额度上限意识。
