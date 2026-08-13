# 盘问 PanWen · Plan 2「Agent 核心」实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现确定性 9 步中文 Text-to-SQL Agent 闭环（归一化+范围门 → 澄清 → 双路 RAG → plan+generate → ValidSQL → 只读执行 → 有界自纠错 → 解释），并在自建冻结评测集上跑出逐组件 ablation 实测指标。

**Architecture:** 固定 Python 管线（每阶段一个 `AgentConfig` 开关 → ablation 干净可测）+ 第 ⑧ 步有界自纠错微循环（看 rootCause → 改上游 → 重生，预算 N=3）。复用 ggb-fable 的 AgentBackend 注入 / rootCause 归因 / trace 模式；**不**复用其自主 function-calling 循环。`tools/` 目录取消（design.md §9 被 spec §4 取代）——「工具」即管线各阶段 Python 函数。

**Tech Stack:** Python ≥3.11 · sqlglot(已装 30.16.0) · duckdb · akshare==1.18.84 · sentence-transformers(bge-large-zh-v1.5) · openai SDK · pyyaml · pytest/pytest-mock。

## Global Constraints

- **诚实红线（design.md §11 / spec §13）**：所有指标 `make eval` 实测填，**绝不编造**；Hermes 54%→93%、GRPO 87.3% 是**他人**数字，禁冒认，仅可作「基准对比」标注；不虚构用户数/star/流量；数据来源明确为 akshare（MIT）。
- **只发脚本不发数据**：`data/live.duckdb` gitignore（每日可重建）；`data/eval.duckdb` 冻结随仓提交；`data/rag_cache/` gitignore。本计划产出的是入库/评测脚本与 yaml 文本，**不**提交任何 .duckdb 之外的数据快照。
- **git 身份**：email = `1527405202@qq.com`，name = `PanWen Dev`。每个 Task 末尾按此身份 commit。
- **不回归**：现有 14 个数据层测试文件（~45 测试）必须保持 `pytest` 全绿；新增测试放 `tests/<subpkg>/`，绝对导入 `from panwen...`，沿用 `tmp_path` + `db.connect/db.init_schema` + `mocker.patch("akshare.<fn>")` + `FakeClient(client=...)` 约定。
- **限流纪律**：`client.fetch` 已有 `min_interval=0.3` 节流；Task 0 **只用 sina 端点**（`stock_financial_report_sina` / `stock_financial_analysis_indicator`），**绝不**碰 eastmoney push2his（仍限流）。
- **确定性架构**：9 步固定顺序，每阶段受 `AgentConfig` 开关控制（ablation 机理）；失败不中断，记 trace。
- **锁定的组件参数**：DeepSeek 主力（`base_url=https://api.deepseek.com`，`model=deepseek-chat`）；GLM 备选（`https://open.bigmodel.cn/api/paas/v4`）；embedding=`BAAI/bge-large-zh-v1.5`；ValidSQL 6 项全开；自纠错 N=3；plan+generate 一次调用；normalize=规则+LLM 混合；范围门 ① 输出 `intent∈{sql_answerable,needs_clarify,out_of_scope}` 零额外调用。
- **范围门增益 ablation 为加分项**，不进 §8.3 必跑基线矩阵。
- **demo UI（Gradio/Streamlit）本计划不含**（spec §1 非目标，单独规划）。

---

## 文件结构（本计划创建/修改）

```
panwen/seeds/eval_codes.txt          # Task0: ~30-50 蓝筹评估种子股
scripts/expand_financials.py         # Task0: sina 财务定向扩量 → live.duckdb
Makefile                             # Task0/8 改: eval-freeze as-of + 新增 task0/eval 目标
pyproject.toml                       # Task1/3/4 加依赖 openai/sentence-transformers/pyyaml

panwen/agent/
  __init__.py                        # 空
  types.py      # Task1: Message/ChatResult/Explanation/TraceStep/AgentResult/NormQuery
  config.py     # Task1: AgentConfig(frozen)
  backend.py    # Task1: AgentBackend Protocol + OpenAICompatBackend + make_backend()
  normalize.py  # Task6: ① 规则+LLM 归一化+意图分类 → NormQuery
  clarify.py    # Task6: ② dispatch 三分支(out_of_scope/needs_clarify/sql_answerable)
  explainer.py  # Task7: ⑨ Explanation{assumptions,confidence,summary}
  loop.py       # Task7: run_query() ③-⑨ 管线 + ⑧ 自纠错子循环
panwen/validsql/
  __init__.py
  validator.py  # Task2: SchemaView + validate_sql() 检查 1-5
panwen/rag/
  __init__.py
  embed.py             # Task3: bge 加载 + 预计算/缓存 + EmbedderProtocol(+FakeEmbedder)
  schema_docs.py       # Task3: 表/列中文描述(人工撰写,喂 schema_retriever)
  schema_retriever.py  # Task3: 问题 → top-k 表/列子集
  fewshot_store.py     # Task5: eval 集 (Q→SQL) 检索 top-k
panwen/eval/
  __init__.py
  loader.py     # Task4: 读 dataset/*.yaml → list[EvalItem]
  dataset/*.yaml      # Task4: 150 题(starter ~20 + 扩量规则) {question,gold_sql,difficulty,tags}
  runner.py     # Task8: 单配置跑全集 → exec_acc + F1
  ablation.py   # Task8: 遍历 AgentConfig 开关组合 → 边际贡献表
  panel.py      # Task8: 维度面板(难度/SQL 结构切片)
panwen/prompts/v1/
  normalize.txt / clarify.txt        # Task6
  plan_generate.txt / explain.txt    # Task7
tests/
  agent/{test_types.py,test_backend.py,test_normalize.py,test_clarify.py,test_loop.py,test_explainer.py}
  validsql/test_validator.py
  rag/{test_embed.py,test_schema_retriever.py,test_fewshot_store.py}
  eval/{test_loader.py,test_runner.py,test_ablation.py}
```

**职责边界**：每个文件单一职责；`types.py` 只放数据契约，`config.py` 只放开关，`backend.py` 只放 LLM 客户端，`validator.py` 只放校验，`loop.py` 只做编排。`embed.py` 是双路 RAG 共享的 embedding 基建。

---

## Task 0：评测基板（扩 sina 财务 → 冻结 eval.duckdb）

**Files:**
- Create: `panwen/seeds/eval_codes.txt`
- Create: `panwen/eval/__init__.py`（空，Task 4 复用）、`panwen/eval/seeds.py`（`load_codes`）
- Create: `scripts/expand_financials.py`
- Modify: `Makefile`（新增 `task0-financials` 目标；`eval-freeze` 的 `--as-of` 改为实测冻结日）
- Test: `tests/eval/test_eval_substrate.py`

**Interfaces:**
- Consumes: `panwen.data.ingest.specs.{INCOME_SPEC,BALANCE_SPEC,CASHFLOW_SPEC,FIN_INDICATOR_SPEC}`（4 个 sina per_code spec）、`panwen.data.ingest.runner.run_ingest`、`panwen.data.ingest.client`、`panwen.data.db.{connect,init_schema}`
- Produces: `data/eval.duckdb`（冻结，随仓提交）；`data/live.duckdb` 扩到 ~30-50 股财务；`panwen.eval.seeds.load_codes(path) -> list[str]`（Task 4 复用）。后续 Task 4 的 gold_sql 在此库上可执。

**为何只用 4 个 sina spec**：`build_finance_specs()` 含 `PERFORMANCE_SPEC`（`stock_yjbb_em`，eastmoney）。为遵守限流纪律，Task 0 显式只跑 sina 的 4 个，不碰 eastmoney。

- [ ] **Step 1：写 eval_codes.txt 种子（~30 只蓝筹，跨板块可识别名）**

Create `panwen/seeds/eval_codes.txt`（一行一代码，`#` 注释）：

```
# Plan 2 评测基板种子：蓝筹 + 多板块可识别名（sina 财务扩量用）
# 白酒: 茅台 五粮液 泸州老窖 山西汾酒
600519
000858
000568
600809
# 银行/保险: 平安 招行 兴业 工行
000001
600036
601166
601398
# 家电/消费: 美的 格力 海尔
000333
000651
600690
# 新能源/车: 宁德 比亚迪 长安
300750
002594
000625
# 医药: 恒瑞 迈瑞 药明
600276
300760
603259
# 科技/电子: 海康 立讯 中兴 工业富联
002415
002475
000063
601138
# 地产/建材: 万科 海螺 保利
000002
600585
600048
# 食品: 伊利 海天 双汇
600887
603288
000895
# 化工/有色: 万华 紫金
600309
601899
```

- [ ] **Step 2：写失败测试（load_codes + spec 集校验）**

Create `tests/eval/test_eval_substrate.py`：

```python
"""Task 0: 评测基板 —— load_codes 契约 + sina spec 集校验。"""
from pathlib import Path
from panwen.data.ingest import specs
from panwen.eval.seeds import load_codes

ROOT = Path(__file__).resolve().parents[2]
SEED = ROOT / "panwen" / "seeds" / "eval_codes.txt"


def test_load_codes_parses_seed():
    """eval_codes.txt 解析为 6 位代码列表(>=30 只，含茅台/平安)。"""
    codes = load_codes(str(SEED))
    assert len(codes) >= 30, f"期望 >=30 只，实际 {len(codes)}"
    assert all(len(c) == 6 and c.isdigit() for c in codes)
    assert "600519" in codes and "000001" in codes


def test_load_codes_ignores_comments_and_blanks(tmp_path):
    f = tmp_path / "s.txt"
    f.write_text("# 注释\n600519\n\n  \n000001\n", encoding="utf-8")
    assert load_codes(str(f)) == ["600519", "000001"]


def test_financial_specs_used_are_sina_only():
    """Task 0 只跑 sina 4 spec，绝不带 eastmoney PERFORMANCE_SPEC。"""
    sina = [specs.INCOME_SPEC, specs.BALANCE_SPEC, specs.CASHFLOW_SPEC, specs.FIN_INDICATOR_SPEC]
    names = {s.name for s in sina}
    assert {"income", "balance", "cashflow", "fin_indicator"} <= names
    assert "performance" not in names  # eastmoney yjbb —— 禁入 Task 0
```

- [ ] **Step 3：跑测试确认失败**

Run: `pytest tests/eval/test_eval_substrate.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'panwen.eval'` —— seeds.py 尚未创建）

- [ ] **Step 4：写 panwen/eval/seeds.py + scripts/expand_financials.py**

Create `panwen/eval/__init__.py`（空文件）。

Create `panwen/eval/seeds.py`：

```python
"""评测种子加载(Task 0)。读种子文件 → 6 位代码列表(去注释/空行)。"""
from __future__ import annotations
from pathlib import Path


def load_codes(path: str) -> list[str]:
    out = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            out.append(line)
    return out
```

Create `scripts/expand_financials.py`：

```python
"""Task 0: sina 财务定向扩量 —— 把 4 张财务表从 2 股扩到 eval_codes 种子股。

只跑 sina 端点(income/balance/cashflow/fin_indicator)，避开 eastmoney 限流。
写入 data/live.duckdb(已存在则 upsert，幂等)。
用法: python scripts/expand_financials.py
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from panwen.data import db
from panwen.data.ingest import client, runner, specs
from panwen.eval.seeds import load_codes

LIVE = "data/live.duckdb"
SEED = "panwen/seeds/eval_codes.txt"

# 只用 sina 的 4 个财务 spec —— 绝不带 eastmoney PERFORMANCE_SPEC
SINA_FINANCIAL_SPECS = [
    specs.INCOME_SPEC, specs.BALANCE_SPEC, specs.CASHFLOW_SPEC, specs.FIN_INDICATOR_SPEC,
]


def main() -> None:
    codes = load_codes(SEED)
    print(f"[task0] 扩量财务: {len(codes)} 只种子股 → {LIVE}")
    conn = db.connect(LIVE)
    db.init_schema(conn)
    try:
        for spec in SINA_FINANCIAL_SPECS:
            n = runner.run_ingest(conn, spec, client=client, code_source=codes)
            print(f"[task0] {spec.name:14s} upsert 完成 ({n} 行受影响)")
    finally:
        conn.close()
    print("[task0] 完成。下一步: make eval-freeze 冻结。")


if __name__ == "__main__":
    main()
```

- [ ] **Step 5：跑测试确认通过（不触网）**

Run: `pytest tests/eval/test_eval_substrate.py -v`
Expected: PASS（3 项全过；`test_load_codes_parses_seed` 读真实种子文件，`test_load_codes_ignores_comments_and_blanks` 验证解析契约，`test_financial_specs_used_are_sina_only` 检查 spec 名集合）

- [ ] **Step 6：加 Makefile 目标**

Modify `Makefile`，在 `.PHONY` 行追加 `task0-financials`，并新增：

```makefile
task0-financials:
	mkdir -p data
	python scripts/expand_financials.py
```

- [ ] **Step 7：运行时执行扩量（真实 sina 爬取，需联网）**

Run: `export NO_PROXY='*' no_proxy='*' && make task0-financials`
Expected: 4 张财务表各 upsert 成功，输出每表受影响行数。约 30 股 × 4 spec × min_interval 0.3s ≈ 数分钟。

- [ ] **Step 8：确定冻结 as-of 并冻结**

Run: `python -c "from panwen.data import db; c=db.connect('data/live.duckdb', read_only=True); print(c.execute('SELECT max(report_date) FROM income_statement').fetchone())"`
Expected: 打印最近完整季报日（目标 `2026-03-31` 或 `2025-12-31`，按实际存在确定）。

把 `Makefile` 的 `eval-freeze` 目标 `--as-of 2024-12-31` 改为上一步实测到的日期（设为 `$$(...)` 或直接写死实测值，如 `--as-of 2026-03-31`）。

Run: `make eval-freeze`
Expected: 生成 `data/eval.duckdb`（从 live 复制 + 删除 date > as-of 的行）。

- [ ] **Step 9：冻结库健全性自检 + 提交**

Run（人工核对，写入 README 后续 Task）:
```bash
python -c "
from panwen.data import db, schema
c=db.connect('data/eval.duckdb', read_only=True)
for t in schema.TABLES:
    n=c.execute(f'SELECT count(*) FROM {t}').fetchone()[0]
    print(f'{t:24s} {n:>8d}')
"
```
Expected: 财务 4 表各数百~数千行（30+ 股 × 多年）；其它表继承 live 现状。`eval.duckdb` 提交进仓（确认 `.gitignore` 未忽略它——live.duckdb 须忽略、eval.duckdb 须提交）。

```bash
git add panwen/seeds/eval_codes.txt panwen/eval/__init__.py panwen/eval/seeds.py \
        scripts/expand_financials.py Makefile data/eval.duckdb tests/eval/test_eval_substrate.py
git commit -m "feat(eval): Task0 substrate — expand sina financials, freeze eval.duckdb"
```

---

## Task 1：Agent 地基（types + config + backend）

**Files:**
- Create: `panwen/agent/__init__.py`（空）、`panwen/agent/types.py`、`panwen/agent/config.py`、`panwen/agent/backend.py`
- Modify: `pyproject.toml`（加 `openai>=1.0.0`）
- Test: `tests/agent/test_types.py`、`tests/agent/test_backend.py`

**Interfaces:**
- Consumes: 无（地基）。环境变量 `DEEPSEEK_API_KEY` / `GLM_API_KEY`。
- Produces:
  - `agent/types.py`: `Message`、`ChatResult`、`Explanation`、`TraceStep`、`AgentResult`、`NormQuery`
  - `agent/config.py`: `AgentConfig`（frozen dataclass）
  - `agent/backend.py`: `AgentBackend`(Protocol)、`OpenAICompatBackend`、`make_backend(provider)`

- [ ] **Step 1：加依赖 openai**

Modify `pyproject.toml` `[project].dependencies`，在 `sqlglot>=23.0.0` 后加：
```toml
  "openai>=1.0.0",
```
Run: `pip install -e ".[dev]"` 确认可装。

- [ ] **Step 2：写失败测试 types**

Create `tests/agent/test_types.py`：

```python
"""Task 1: Agent 数据契约。"""
from panwen.agent import types as T


def test_agent_result_status_enum():
    r = T.AgentResult(status="out_of_scope", sql=None, rows=None,
                      reply="超出范围", explanation=None, trace=[])
    assert r.status == "out_of_scope" and r.sql is None


def test_norm_query_carries_intent():
    n = T.NormQuery(question="茅台近三年ROE", date_range=("2023-01-01", "2026-03-31"),
                    top_k=None, order=None, entities={"code": "600519"},
                    intent="sql_answerable")
    assert n.intent == "sql_answerable"
    assert n.entities["code"] == "600519"


def test_tracestep_defaults():
    s = T.TraceStep(stage="validate", ok=True, detail="6 checks pass")
    assert s.rootCause is None  # 默认 None


def test_chatresult_holds_raw():
    cr = T.ChatResult(content='{"sql":"SELECT 1"}', tool_calls=[], raw={"x": 1})
    assert cr.raw["x"] == 1
```

- [ ] **Step 3：跑测试确认失败**

Run: `pytest tests/agent/test_types.py -v`
Expected: FAIL（`No module named 'panwen.agent'`）

- [ ] **Step 4：写 types.py + config.py + 空 __init__.py**

Create `panwen/agent/__init__.py`（空文件）。

Create `panwen/agent/types.py`：

```python
"""Agent 数据契约（spec §9）。所有结构是 dataclass，无业务逻辑。"""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Message:
    role: str                       # "system" | "user" | "assistant"
    content: str | None = None
    tool_calls: list | None = None


@dataclass
class ChatResult:
    content: str                    # LLM 原始文本(可能含 JSON)
    tool_calls: list
    raw: dict                       # 透传 provider 原始响应片段


@dataclass
class Explanation:
    assumptions: list[str]
    confidence: float               # 0.0 .. 1.0
    summary: str


@dataclass
class TraceStep:
    stage: str                      # "normalize"|"dispatch"|"rag"|"generate"|"validate"|"execute"|"selfcorrect"|"explain"
    ok: bool
    detail: str
    rootCause: str | None = None    # 失败时归因码(ROOT_UNKNOWN_COL 等)


@dataclass
class AgentResult:
    status: str                     # "answered" | "clarified" | "out_of_scope" | "failed"
    sql: str | None
    rows: list[dict] | None
    reply: str | None               # status != "answered" 时的非 SQL 回复
    explanation: Explanation | None # status == "answered" 时非空
    trace: list[TraceStep] = field(default_factory=list)


@dataclass(frozen=True)
class NormQuery:
    """① normalize 产出。"""
    question: str
    date_range: tuple[str, str] | None
    top_k: int | None
    order: str | None               # "asc" | "desc" | None
    entities: dict                  # {"code":"600519","board":"白酒",...}
    intent: str                     # "sql_answerable"|"needs_clarify"|"out_of_scope"
```

Create `panwen/agent/config.py`：

```python
"""AgentConfig —— ablation 开关 + 预算 + 检索 k（spec §2/§9）。frozen。"""
from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class AgentConfig:
    use_plan: bool = True
    use_fewshot: bool = True
    use_validsql: bool = True
    use_selfcorrect: bool = True
    selfcorrect_budget: int = 3
    fewshot_k: int = 3
    schema_topk: int = 5
    exec_timeout_s: int = 30
    cartesian_row_warn: int = 10_000
```

- [ ] **Step 5：跑 types 测试确认通过**

Run: `pytest tests/agent/test_types.py -v`
Expected: PASS（4 项）

- [ ] **Step 6：写失败测试 backend**

Create `tests/agent/test_backend.py`：

```python
"""Task 1: OpenAICompatBackend —— 消息装配 + 结构化解析，mock openai 客户端。"""
import pytest
from panwen.agent import backend as B
from panwen.agent.types import Message


def _fake_openai(return_content: str):
    """造一个假的 OpenAI 客户端：chat.completions.create 返回固定 content。"""
    class _Resp:
        class choices:
            class _0:
                message = type("M", (), {"content": return_content, "tool_calls": None})()
            __getitem__ = staticmethod(lambda self, i: _0())  # 简化：直接属性
        choices_obj = choices()
        model_dump = lambda self: {"role": "assistant"}
    class _Completions:
        def create(self, **kw): return _Resp()
    class _Chat:
        completions = _Completions()
    class _Client:
        chat = _Chat()
    return _Client()


def test_chat_assembles_messages_and_returns_content(mocker):
    be = B.OpenAICompatBackend(api_key="x", base_url="https://api.deepseek.com",
                               model="deepseek-chat")
    be.client = _fake_openai('{"sql":"SELECT 1"}')
    msgs = [Message(role="system", content="s"), Message(role="user", content="u")]
    cr = be.chat(msgs)
    assert cr.content == '{"sql":"SELECT 1"}'
    assert isinstance(cr.tool_calls, list)


def test_chat_response_format_passed_through(mocker):
    be = B.OpenAICompatBackend(api_key="x", base_url="u", model="m")
    captured = {}
    class _Spy:
        class chat:
            class completions:
                @staticmethod
                def create(**kw):
                    captured.update(kw)
                    class _R:
                        class choices:
                            class _0:
                                message = type("M", (), {"content": "{}", "tool_calls": None})()
                            __getitem__ = staticmethod(lambda s, i: _0())
                        choices_obj = choices()
                        model_dump = lambda self: {}
                    return _R()
    be.client = _Spy()
    be.chat([Message(role="user", content="hi")],
            response_format={"type": "json_object"}, temperature=0.0)
    assert captured.get("response_format") == {"type": "json_object"}
    assert captured.get("temperature") == 0.0


def test_make_backend_reads_env_deepseek(mocker):
    mocker.patch.dict("os.environ", {"DEEPSEEK_API_KEY": "sk-test"})
    be = B.make_backend("deepseek")
    assert be.model == "deepseek-chat"
    assert "deepseek.com" in be.base_url


def test_make_backend_missing_key_raises(mocker):
    mocker.patch.dict("os.environ", {}, clear=True)
    with pytest.raises(B.BackendConfigError):
        B.make_backend("deepseek")
```

- [ ] **Step 7：跑测试确认失败**

Run: `pytest tests/agent/test_backend.py -v`
Expected: FAIL（`OpenAICompatBackend` 不存在）

- [ ] **Step 8：写 backend.py**

Create `panwen/agent/backend.py`：

```python
"""AgentBackend —— OpenAI 兼容后端(DeepSeek + GLM 同接口)。

复用 ggb-fable 的「Backend 注入」：chat() 接受 list[Message]，返回 ChatResult。
不实现自主工具循环(那是 loop.py 的职责)。
"""
from __future__ import annotations
import os
from typing import Protocol
from openai import OpenAI

from panwen.agent.types import Message, ChatResult

# provider → (env var, base_url, model)
_PROVIDERS = {
    "deepseek": ("DEEPSEEK_API_KEY", "https://api.deepseek.com", "deepseek-chat"),
    "glm":      ("GLM_API_KEY", "https://open.bigmodel.cn/api/paas/v4", "glm-4.6"),
}


class BackendConfigError(RuntimeError):
    pass


class AgentBackend(Protocol):
    def chat(self, messages: list[Message], *, tools: list | None = None,
             temperature: float = 0.0, response_format: dict | None = None,
             model: str | None = None) -> ChatResult: ...


class OpenAICompatBackend:
    """DeepSeek 与 GLM 均兼容 OpenAI Chat Completions API，一个类覆盖。"""

    def __init__(self, api_key: str, base_url: str, model: str):
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.base_url = base_url
        self.model = model

    def chat(self, messages: list[Message], *, tools: list | None = None,
             temperature: float = 0.0, response_format: dict | None = None,
             model: str | None = None) -> ChatResult:
        payload = {
            "model": model or self.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": temperature,
        }
        if response_format is not None:
            payload["response_format"] = response_format
        if tools is not None:
            payload["tools"] = tools
        resp = self.client.chat.completions.create(**payload)
        msg = resp.choices[0].message
        return ChatResult(
            content=msg.content or "",
            tool_calls=getattr(msg, "tool_calls", None) or [],
            raw=getattr(resp, "model_dump", lambda: {})(),
        )


def make_backend(provider: str = "deepseek") -> AgentBackend:
    """从环境变量读 key(trial 模式)。"""
    if provider not in _PROVIDERS:
        raise BackendConfigError(f"unknown provider: {provider}")
    env_var, base_url, model = _PROVIDERS[provider]
    api_key = os.getenv(env_var)
    if not api_key:
        raise BackendConfigError(f"missing env {env_var} for provider '{provider}'")
    return OpenAICompatBackend(api_key=api_key, base_url=base_url, model=model)
```

- [ ] **Step 9：跑 backend 测试确认通过**

Run: `pytest tests/agent/test_backend.py -v`
Expected: PASS（4 项）

- [ ] **Step 10：提交**

```bash
git add panwen/agent/ tests/agent/ pyproject.toml
git commit -m "feat(agent): Task1 foundation — types/config/backend (OpenAICompatBackend)"
```

---

## Task 2：ValidSQL（sqlglot 6 项校验之 1-5；第 6 项执行超时在 Task 7 execute_sql）

**Files:**
- Create: `panwen/validsql/__init__.py`（空）、`panwen/validsql/validator.py`
- Test: `tests/validsql/test_validator.py`

**Interfaces:**
- Consumes: `panwen.data.schema.{COLUMN_CLASS, PRIMARY_KEYS, TABLES}`
- Produces: `validate_sql(sql, schema_view, conn=None) -> list[ValidationIssue]`；`SchemaView`；`ValidationIssue{code,message,rootCause}`；`build_schema_view() -> SchemaView`

- [ ] **Step 1：写失败测试（每检查一组 pass/fail 夹具）**

Create `tests/validsql/test_validator.py`：

```python
"""Task 2: ValidSQL 6 检查(检查 6 执行超时在 Task 7)。每检查 pass + fail 夹具。"""
import pytest
from panwen.validsql import validator as V


@pytest.fixture
def sv():
    return V.build_schema_view()


# --- 检查 1: AST 白名单(只读) ---
def test_write_op_rejected(sv):
    issues = V.validate_sql("DELETE FROM income_statement WHERE code='600519'", sv)
    assert any(i.code == "ROOT_WRITE_OP" for i in issues)

def test_select_passes_write(sv):
    assert V.validate_sql("SELECT revenue FROM income_statement WHERE code='600519'", sv) == []


# --- 检查 2: 表/列存在性 ---
def test_unknown_column_rejected(sv):
    issues = V.validate_sql("SELECT fake_col FROM income_statement", sv)
    assert any(i.code == "ROOT_UNKNOWN_COL" for i in issues)

def test_unknown_table_rejected(sv):
    issues = V.validate_sql("SELECT * FROM nonexist_table", sv)
    assert any(i.code == "ROOT_UNKNOWN_TABLE" for i in issues)


# --- 检查 3: 类型约束(text 列禁聚合) ---
def test_text_column_aggregation_rejected(sv):
    # code/name 是 text，对 name 求 AVG 无意义
    issues = V.validate_sql("SELECT AVG(name) FROM stock_basic", sv)
    assert any(i.code == "ROOT_TYPE_AGG" for i in issues)

def test_numeric_column_aggregation_passes(sv):
    assert V.validate_sql("SELECT AVG(roe) FROM financial_indicator", sv) == []


# --- 检查 4: 防笛卡尔(多表须 JOIN ON) ---
def test_cartesian_without_join_rejected(sv):
    sql = ("SELECT i.revenue FROM income_statement i, balance_sheet b "
           "WHERE i.code='600519'")
    issues = V.validate_sql(sql, sv)
    assert any(i.code == "ROOT_CARTESIAN" for i in issues)

def test_join_with_on_passes(sv):
    sql = ("SELECT i.revenue FROM income_statement i "
           "JOIN balance_sheet b ON i.code=b.code AND i.report_date=b.report_date "
           "WHERE i.code='600519'")
    assert V.validate_sql(sql, sv) == []


# --- 检查 5: 参数化(裸字面量应走 ? 绑定) ---
def test_bare_literal_in_predicate_warned(sv):
    # WHERE code='600519' —— 应生成 WHERE code=?
    issues = V.validate_sql("SELECT revenue FROM income_statement WHERE code='600519'", sv)
    assert any(i.code == "ROOT_UNPARAM" for i in issues)

def test_parameterized_predicate_passes(sv):
    assert V.validate_sql("SELECT revenue FROM income_statement WHERE code=?", sv) == []
```

- [ ] **Step 2：跑测试确认失败**

Run: `pytest tests/validsql/test_validator.py -v`
Expected: FAIL（`No module named 'panwen.validsql'`）

- [ ] **Step 3：写 validator.py**

Create `panwen/validsql/__init__.py`（空）。

Create `panwen/validsql/validator.py`：

```python
"""ValidSQL —— sqlglot AST 6 检查(spec §6)。

检查 1-5 在此；检查 6(执行超时)在 agent/loop.py 的 execute_sql 实现。
空 list = 通过。每 issue 带 code/message/rootCause，rootCause 喂自纠错。
"""
from __future__ import annotations
from dataclasses import dataclass
import sqlglot
from sqlglot import exp

from panwen.data import schema as _schema


@dataclass
class ValidationIssue:
    code: str
    message: str
    rootCause: str


@dataclass
class SchemaView:
    """由 schema.COLUMN_CLASS + PRIMARY_KEYS 派生，不新增数据。"""
    columns: dict[str, dict[str, str]]   # table -> {col -> class}
    primary_keys: dict[str, list[str]]


def build_schema_view() -> SchemaView:
    return SchemaView(columns=dict(_schema.COLUMN_CLASS), primary_keys=dict(_schema.PRIMARY_KEYS))


# --- sqlglot 辅助 ---
def _tables_in_query(parsed: exp.Expression) -> list[str]:
    return [t.name for t in parsed.find_all(exp.Table)]


def _columns_in_query(parsed: exp.Expression) -> list[exp.Column]:
    return list(parsed.find_all(exp.Column))


_WRITE_NODES = (exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Create, exp.Alter)
_AGG_NODES = (exp.Avg, exp.Sum, exp.Min, exp.Max, exp.Count)
_COMPARE_NODES = (exp.EQ, exp.NEQ, exp.GT, exp.GTE, exp.LT, exp.LTE, exp.Like)


def validate_sql(sql: str, schema_view: SchemaView, conn=None) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    try:
        parsed = sqlglot.parse_one(sql, read="duckdb")
    except Exception as e:
        issues.append(ValidationIssue("ROOT_PARSE", f"SQL 解析失败: {e}", "SQL 语法错误，无法解析"))
        return issues

    # 1. AST 白名单：出现写操作 → 拒
    for node in parsed.find_all(_WRITE_NODES):
        issues.append(ValidationIssue(
            "ROOT_WRITE_OP", f"禁止写操作: {type(node).__name__}", "出现写操作，本系统只读"))
        break  # 一次足够

    # 2. 表/列存在性
    known_tables = set(schema_view.columns)
    from_tables = set(_tables_in_query(parsed))
    for tname in from_tables - known_tables:
        issues.append(ValidationIssue(
            "ROOT_UNKNOWN_TABLE", f"表不存在: {tname}", f"表 {tname} 不在 schema 中(幻觉)"))
    # 列存在性：列须属于 FROM 中某表
    present_tables = from_tables & known_tables
    allowed_cols = set()
    for t in present_tables:
        allowed_cols.update(schema_view.columns[t].keys())
    for col in _columns_in_query(parsed):
        cname = col.name
        # 带 table 限定：核对限定名是否在 FROM
        if col.table:
            qualifier = col.table
            real = qualifier  # 别名解析为 MVP 简化：别名同名即放行
            if real in present_tables and cname not in schema_view.columns[real]:
                issues.append(ValidationIssue(
                    "ROOT_UNKNOWN_COL", f"列 {cname} 不存在于表 {real}",
                    f"列 {cname} 不在表 {real} 的 schema 中(幻觉)"))
        else:
            if cname not in allowed_cols and allowed_cols:
                issues.append(ValidationIssue(
                    "ROOT_UNKNOWN_COL", f"列 {cname} 不存在于任何 FROM 表",
                    f"列 {cname} 不在当前查询的任何表中(幻觉)"))

    # 3. 类型约束：text 列禁聚合
    text_cols = {c for t in present_tables for c, cls in schema_view.columns[t].items() if cls == "text"}
    for agg in parsed.find_all(_AGG_NODES):
        for col in agg.find_all(exp.Column):
            if col.name in text_cols:
                issues.append(ValidationIssue(
                    "ROOT_TYPE_AGG", f"对文本列 {col.name} 做 {type(agg).__name__} 无意义",
                    f"列 {col.name} 是 text，不可聚合"))

    # 4. 防笛卡尔：多表须有 JOIN ON
    if len(from_tables) > 1:
        joins = list(parsed.find_all(exp.Join))
        has_on = any(j.args.get("on") is not None or j.args.get("using") for j in joins)
        if not has_on:
            issues.append(ValidationIssue(
                "ROOT_CARTESIAN", "多表查询缺少 JOIN ON 连接条件(笛卡尔积风险)",
                "多表 FROM 须用 JOIN ... ON 显式连接"))
        # 可选：conn 给定时用 EXPLAIN 行数估算告警
        if conn is not None and has_on:
            try:
                plan = conn.execute(f"EXPLAIN {sql}").fetchall()
                est = _extract_row_estimate(plan)
                if est is not None and est > 10_000:
                    issues.append(ValidationIssue(
                        "ROOT_CARTESIAN", f"EXPLAIN 行数估算 {est} 过大(疑似笛卡尔)",
                        f"估算 {est} 行，超阈值，检查 JOIN 条件"))
            except Exception:
                pass  # EXPLAIN 失败不阻断，留给执行阶段

    # 5. 参数化：WHERE 谓词的裸字面量应走 ? 绑定
    for cmp in parsed.find_all(_COMPARE_NODES):
        # 若 comparison 的一侧是 Literal(非 Placeholder) → 用户值未参数化
        for side in (cmp.left, cmp.right):
            if isinstance(side, exp.Literal) and not isinstance(side, exp.Placeholder):
                issues.append(ValidationIssue(
                    "ROOT_UNPARAM", f"谓词含裸字面量 {side.this!r}，应改用 ? 参数绑定",
                    "用户值须走 DuckDB 参数(?/$1)，非字符串拼接"))
                break

    return issues


def _extract_row_estimate(plan_rows) -> int | None:
    """从 DuckDB EXPLAIN 输出里粗估行数(MVP：扫文本找 ~N rows)。"""
    import re
    text = "\n".join(str(r) for r in plan_rows)
    m = re.findall(r"~(\d+)\s*Rows", text, re.IGNORECASE)
    return int(m[-1]) if m else None
```

- [ ] **Step 4：跑测试确认通过**

Run: `pytest tests/validsql/test_validator.py -v`
Expected: PASS（全部检查 pass/fail 夹具）。若某夹具因 sqlglot 版本 AST 细节不匹配，**先调夹具对齐 sqlglot 30.x 行为**（如 `exp.Avg` 类名、`Join.args["on"]` 取法），不改校验语义。

- [ ] **Step 5：提交**

```bash
git add panwen/validsql/ tests/validsql/
git commit -m "feat(validsql): Task2 sqlglot AST checks 1-5 (write/col/type/cartesian/unparam)"
```

---

## Task 3：RAG embedding 基建 + schema_retriever

**Files:**
- Create: `panwen/rag/__init__.py`（空）、`panwen/rag/embed.py`、`panwen/rag/schema_docs.py`、`panwen/rag/schema_retriever.py`
- Modify: `pyproject.toml`（加 `sentence-transformers>=2.7.0`）
- Test: `tests/rag/test_embed.py`、`tests/rag/test_schema_retriever.py`

**Interfaces:**
- Consumes: `panwen.data.schema`、`BAAI/bge-large-zh-v1.5`（HuggingFace）
- Produces:
  - `rag/embed.py`: `Embedder`(Protocol)、`BgeEmbedder`、`FakeEmbedder`(测试用)、`embed_texts()`、`cosine_topk()`
  - `rag/schema_docs.py`: `SCHEMA_DOCS: dict[str, list[SchemaDocEntry]]`（表/列中文描述）
  - `rag/schema_retriever.py`: `SchemaRetriever`，`.retrieve(question, k) -> list[SchemaDocEntry]`

**关键设计**：单元测试用 `FakeEmbedder`（确定性哈希向量，离线零下载）；真实 `BgeEmbedder` 只在 `make eval`/集成路径用。预计算结果缓存到 `data/rag_cache/`（gitignore）。

- [ ] **Step 1：加依赖 sentence-transformers**

Modify `pyproject.toml` 加：
```toml
  "sentence-transformers>=2.7.0",
```
Run: `pip install -e ".[dev]"`（首次会下载 bge 模型 ~1.3GB，仅集成测/eval 时触发；单测用 FakeEmbedder 不下载）。

- [ ] **Step 2：写失败测试 embed**

Create `tests/rag/test_embed.py`：

```python
"""Task 3: embedding 基建。FakeEmbedder 确定性、离线。"""
import numpy as np
from panwen.rag import embed


def test_fake_embedder_is_deterministic():
    e = embed.FakeEmbedder(dim=8)
    a = e.embed_texts(["茅台", "茅台"])
    assert np.allclose(a[0], a[1])  # 相同文本相同向量


def test_cosine_topk_returns_nearest():
    e = embed.FakeEmbedder(dim=16)
    q = e.embed_texts(["白酒股的ROE"])[0]
    docs = e.embed_texts(["贵州茅台净利润", "CPI 同比", "白酒行业 ROE"])
    idx = embed.cosine_topk(q, docs, k=1)
    assert idx == [2] or idx[0] in (0, 2)  # FakeEmbedder 弱语义，仅保证确定性 + 可调用


def test_bge_embedder_lazy_load_not_required_for_unit():
    # 单测不触发 HF 下载：BgeEmbedder 仅在实例化后调 embed 才下载
    assert hasattr(embed, "BgeEmbedder")
```

- [ ] **Step 3：跑测试确认失败**

Run: `pytest tests/rag/test_embed.py -v`
Expected: FAIL（`No module named 'panwen.rag'`）

- [ ] **Step 4：写 embed.py**

Create `panwen/rag/__init__.py`（空）。

Create `panwen/rag/embed.py`：

```python
"""双路 RAG 共享的 embedding 基建(spec §7)。

- BgeEmbedder: BAAI/bge-large-zh-v1.5(本地、离线、免费)，懒加载。
- FakeEmbedder: 确定性哈希向量，单测离线用(零下载)。
预计算缓存到 data/rag_cache/(gitignore)。
"""
from __future__ import annotations
import hashlib
from pathlib import Path
from typing import Protocol

import numpy as np

MODEL_NAME = "BAAI/bge-large-zh-v1.5"
CACHE_DIR = Path("data/rag_cache")


class Embedder(Protocol):
    dim: int
    def embed_texts(self, texts: list[str]) -> np.ndarray: ...   # (n, dim)


class FakeEmbedder:
    """确定性哈希向量(单测用)。相同文本 → 相同向量，无语义，但可调用且离线。"""
    def __init__(self, dim: int = 64):
        self.dim = dim

    def embed_texts(self, texts: list[str]) -> np.ndarray:
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for i, t in enumerate(texts):
            h = hashlib.sha256(t.encode("utf-8")).digest()
            for j in range(self.dim):
                out[i, j] = (h[j % len(h)] / 255.0) * 2 - 1
        # L2 归一化
        n = np.linalg.norm(out, axis=1, keepdims=True)
        n[n == 0] = 1.0
        return out / n


class BgeEmbedder:
    """bge-large-zh-v1.5。模型在首次 embed 时懒加载(避免单测下载)。"""
    def __init__(self, model_name: str = MODEL_NAME):
        self.model_name = model_name
        self._model = None
        self.dim = 1024  # bge-large-zh-v1.5 输出维度

    def _load(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self.model_name)
            self.dim = self._model.get_sentence_embedding_dimension()
        return self._model

    def embed_texts(self, texts: list[str]) -> np.ndarray:
        model = self._load()
        vecs = model.encode(texts, normalize_embeddings=True, convert_to_numpy=True)
        return np.asarray(vecs, dtype=np.float32)


def cosine_topk(query_vec: np.ndarray, doc_matrix: np.ndarray, k: int) -> list[int]:
    """返回最相似的 k 个文档下标(降序)。向量已 L2 归一化时点积即 cosine。"""
    q = query_vec / (np.linalg.norm(query_vec) + 1e-9)
    d = doc_matrix / (np.linalg.norm(doc_matrix, axis=1, keepdims=True) + 1e-9)
    sims = d @ q
    k = min(k, len(sims))
    return list(np.argsort(-sims)[:k])
```

- [ ] **Step 5：跑 embed 测试确认通过**

Run: `pytest tests/rag/test_embed.py -v`
Expected: PASS（3 项，FakeEmbedder 离线确定性）

- [ ] **Step 6：写 schema_docs.py（表/列中文描述，喂检索）**

Create `panwen/rag/schema_docs.py`：

```python
"""schema 文档 —— 每表/列的中文描述，喂 schema_retriever 检索。

由 panwen.data.schema.TABLES 派生表名；列描述人工撰写(关键列)。
未列出的列回退为「列名(英文)」占位描述。
"""
from __future__ import annotations
from dataclasses import dataclass
from panwen.data import schema


@dataclass(frozen=True)
class SchemaDocEntry:
    table: str
    column: str | None       # None = 表级描述
    doc: str                 # 中文描述


# 表级 + 关键列描述(可增量补全)
_TABLE_DOCS = {
    "stock_basic": "股票基础信息：全市场代码(code)与名称(name)。",
    "daily_quote": "日行情(后复权)：code 代码、date 日期、open/high/low/close 开高低收、volume 成交量、turnover 换手率。",
    "income_statement": "利润表：code、report_date 报告日、revenue 营业总收入、oper_cost 营业成本、net_profit 净利润。",
    "balance_sheet": "资产负债表：code、report_date、total_assets 资产总计、total_liabilities 负债合计、total_equity 所有者权益。",
    "cashflow_statement": "现金流量表：code、report_date、oper_cashflow 经营现金流等。",
    "financial_indicator": "财务指标：code、report_date、roe 净资产收益率、roa、gross_margin 毛利率、net_margin 净利率、debt_ratio 资产负债率。",
    "margin_daily": "融资融券(上交所)：date、margin_buy 融资买入、margin_balance 融资余额。",
    "dragon_tiger": "龙虎榜明细：code、date、reason 上榜原因。",
    "macro_series": "宏观序列：CPI 同比等，name 指标名、date、value。",
    "industry_board": "行业板块列表：name 板块名、code 板块代码。",
    "industry_board_daily": "行业板块日线：name、date、close。",
    "concept_board": "概念板块列表：name、code。",
    "performance_express": "业绩快报：code、report_date、revenue、net_profit。",
    "trade_calendar": "交易日历：trade_date。",
}

# 关键列补充(反幻觉：告诉模型 code/report_date 是 text/date 键列)
_COL_DOCS = {
    ("stock_basic", "code"): "6 位股票代码(文本，如 600519)",
    ("income_statement", "report_date"): "财报报告日(日期 YYYY-MM-DD，如 2025-12-31)",
}


def build_schema_docs() -> list[SchemaDocEntry]:
    entries: list[SchemaDocEntry] = []
    for table in schema.TABLES:
        entries.append(SchemaDocEntry(table=table, column=None,
                                      doc=_TABLE_DOCS.get(table, f"表 {table}。")))
        for col in schema.COLUMN_CLASS[table]:
            entries.append(SchemaDocEntry(
                table=table, column=col,
                doc=_COL_DOCS.get((table, col), f"{table}.{col}")))
    return entries
```

- [ ] **Step 7：写失败测试 schema_retriever**

Create `tests/rag/test_schema_retriever.py`：

```python
"""Task 3: schema_retriever 在固定小语料上测召回排序(用 FakeEmbedder)。"""
from panwen.rag import schema_retriever as sr
from panwen.rag.embed import FakeEmbedder


def test_retrieve_returns_topk_entries():
    r = sr.SchemaRetriever(embedder=FakeEmbedder(dim=32), topk=3)
    out = r.retrieve("茅台近三年 ROE")
    assert len(out) <= 3
    assert all(hasattr(e, "table") for e in out)


def test_retrieve_uses_cache(tmp_path):
    import panwen.rag.schema_retriever as mod
    r = sr.SchemaRetriever(embedder=FakeEmbedder(dim=32), topk=3,
                           cache_dir=str(tmp_path))
    r.ensure_indexed()
    assert (tmp_path / "schema_docs.npy").exists()
    # 第二次构造应命中缓存(不重算)
    r2 = sr.SchemaRetriever(embedder=FakeEmbedder(dim=32), topk=3,
                            cache_dir=str(tmp_path))
    r2.ensure_indexed()
    out = r2.retrieve("某问题")
    assert len(out) <= 3
```

- [ ] **Step 8：跑测试确认失败**

Run: `pytest tests/rag/test_schema_retriever.py -v`
Expected: FAIL（`SchemaRetriever` 不存在）

- [ ] **Step 9：写 schema_retriever.py**

Create `panwen/rag/schema_retriever.py`：

```python
"""schema_retriever(常开) —— 问题 embedding × schema 文档 embedding → top-k 表/列子集。

目的：控进 prompt 的 token + 降列幻觉(只给相关列)。
"""
from __future__ import annotations
from pathlib import Path
import numpy as np

from panwen.rag.embed import Embedder, cosine_topk
from panwen.rag.schema_docs import SchemaDocEntry, build_schema_docs


class SchemaRetriever:
    def __init__(self, embedder: Embedder, topk: int = 5, cache_dir: str | None = None):
        self.embedder = embedder
        self.topk = topk
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self._entries: list[SchemaDocEntry] | None = None
        self._matrix: np.ndarray | None = None

    def ensure_indexed(self) -> None:
        if self._matrix is not None:
            return
        cache = self.cache_dir / "schema_docs.npy" if self.cache_dir else None
        if cache and cache.exists():
            self._matrix = np.load(cache)
            self._entries = build_schema_docs()  # 文本可重建(代码即数据)
            return
        self._entries = build_schema_docs()
        docs = [f"{e.table}{'.'+e.column if e.column else ''} {e.doc}" for e in self._entries]
        self._matrix = self.embedder.embed_texts(docs)
        if cache:
            cache.parent.mkdir(parents=True, exist_ok=True)
            np.save(cache, self._matrix)

    def retrieve(self, question: str) -> list[SchemaDocEntry]:
        self.ensure_indexed()
        q = self.embedder.embed_texts([question])[0]
        idx = cosine_topk(q, self._matrix, k=self.topk)
        return [self._entries[i] for i in idx]
```

- [ ] **Step 10：跑测试确认通过 + 加 .gitignore**

确认 `data/rag_cache/` 被忽略（若 `.gitignore` 无则追加一行 `data/rag_cache/`）。

Run: `pytest tests/rag/ -v`
Expected: PASS（embed 3 + retriever 2）

- [ ] **Step 11：提交**

```bash
git add panwen/rag/ tests/rag/ pyproject.toml .gitignore
git commit -m "feat(rag): Task3 embed substrate (bge+Fake) + schema_retriever"
```

---

## Task 4：评测集（150 题 yaml + loader + gold_sql 校验）

**Files:**
- Create: `panwen/eval/loader.py`、`panwen/eval/dataset/questions.yaml`
- Create: `scripts/validate_gold.py`（gold_sql 在 eval.duckdb 上可执校验）
- Modify: `pyproject.toml`（加 `pyyaml>=6.0`）
- Test: `tests/eval/test_loader.py`

> 注：`panwen/eval/__init__.py` 由 Task 0 创建，此处复用，不重复创建。

**Interfaces:**
- Consumes: `data/eval.duckdb`（Task 0 冻结）；`panwen.data.db`
- Produces: `load_dataset(path) -> list[EvalItem]`；`EvalItem{question,gold_sql,difficulty,tags,answerable_on}`；150 题 yaml。

**关键说明（非占位符）**：本 Task 提供 **starter ~20 题**（跨 4 难度层 + 6 查询类型，gold_sql 对已知 schema 结构正确）+ **扩量规则**（按 §8.1 分层补到 150）+ **gold 校验脚本**（每条 gold_sql 必须在 eval.duckdb 上可执且返回确定行）。剩余 ~130 题在执行期按规则补写，每补一条跑 `validate_gold.py` 锁定。gold_sql 的精确结果行在 Task 0 冻结后由校验脚本实测填入。

- [ ] **Step 1：加依赖 pyyaml**

Modify `pyproject.toml` 加：
```toml
  "pyyaml>=6.0",
```
Run: `pip install -e ".[dev]"`

- [ ] **Step 2：写失败测试 loader**

Create `tests/eval/test_loader.py`：

```python
"""Task 4: 评测集 loader。"""
import pytest
from panwen.eval import loader as L


def test_load_dataset_returns_items(tmp_path):
    yaml_text = """
- question: 茅台近三年ROE
  gold_sql: SELECT roe FROM financial_indicator WHERE code='600519' ORDER BY report_date DESC LIMIT 3
  difficulty: simple
  tags: [单股, 财务, 时序]
  answerable_on: "2026-03-31"
- question: 今天天气
  gold_sql: null
  difficulty: simple
  tags: [out_of_scope]
  answerable_on: "2026-03-31"
"""
    p = tmp_path / "q.yaml"
    p.write_text(yaml_text, encoding="utf-8")
    items = L.load_dataset(str(p))
    assert len(items) == 2
    assert items[0].question == "茅台近三年ROE"
    assert items[0].difficulty == "simple"
    assert items[1].gold_sql is None  # out_of_scope 题无 gold


def test_stratification_counts(tmp_path):
    """starter 集覆盖 4 难度层(执行期补到 §8.1 配额)。"""
    from pathlib import Path
    ROOT = Path(__file__).resolve().parents[2]
    items = L.load_dataset(str(ROOT / "panwen" / "eval" / "dataset" / "questions.yaml"))
    diffs = {i.difficulty for i in items}
    assert "simple" in diffs  # 至少含 simple 层
```

- [ ] **Step 3：跑测试确认失败**

Run: `pytest tests/eval/test_loader.py -v`
Expected: FAIL（`No module named 'panwen.eval'`）

- [ ] **Step 4：写 loader.py + EvalItem**

Create `panwen/eval/__init__.py`（空）。

Create `panwen/eval/loader.py`：

```python
"""评测集 loader(spec §8.1)。读 dataset/*.yaml → list[EvalItem]。"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import yaml


@dataclass(frozen=True)
class EvalItem:
    question: str
    gold_sql: str | None       # None = out_of_scope 题无 gold
    difficulty: str            # simple | join | aggregate | domain
    tags: list[str]
    answerable_on: str         # 冻结 as-of


def load_dataset(path: str) -> list[EvalItem]:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return [EvalItem(
        question=r["question"],
        gold_sql=r.get("gold_sql"),
        difficulty=r["difficulty"],
        tags=list(r.get("tags", [])),
        answerable_on=r["answerable_on"],
    ) for r in raw]
```

- [ ] **Step 5：写 starter 题集（~20 题，跨难度层）**

Create `panwen/eval/dataset/questions.yaml`。包含 simple（单股财务深查/宏观）、join（财务×行情/龙虎榜×股票）、aggregate（连续N年ROE/top-k筛选）、domain（融资融券/业绩快报/CPI）+ 少量 out_of_scope（闲聊/非金融）。示例条目（gold_sql 对已知 schema 结构正确，精确结果行由 Task 0 冻结后校验脚本锁定）：

```yaml
# Plan 2 评测集(starter ~20 题；执行期按 §8.1 补到 150)
# 难度分层: simple ~40 / join ~50 / aggregate ~40 / domain ~20 (含 out_of_scope 陷阱题)
# answerable_on = Task 0 实测冻结日(此处先用目标值，冻结后统一对齐)

# ===== simple: 单股财务深查 =====
- question: 贵州茅台最近一年的净利润是多少
  gold_sql: SELECT report_date, net_profit FROM income_statement WHERE code='600519' ORDER BY report_date DESC LIMIT 1
  difficulty: simple
  tags: [单股, 财务, 利润]
  answerable_on: "2026-03-31"

- question: 平安银行最新资产负债率
  gold_sql: SELECT report_date, debt_ratio FROM financial_indicator WHERE code='000001' ORDER BY report_date DESC LIMIT 1
  difficulty: simple
  tags: [单股, 财务, 指标]
  answerable_on: "2026-03-31"

- question: 比亚迪近三年的毛利率走势
  gold_sql: SELECT report_date, gross_margin FROM financial_indicator WHERE code='002594' ORDER BY report_date DESC LIMIT 12
  difficulty: simple
  tags: [单股, 财务, 时序]
  answerable_on: "2026-03-31"

# ===== simple: 宏观 =====
- question: 最近一次公布的 CPI 同比是多少
  gold_sql: SELECT date, value FROM macro_series WHERE name LIKE '%CPI%' ORDER BY date DESC LIMIT 1
  difficulty: simple
  tags: [宏观]
  answerable_on: "2026-03-31"

# ===== join: 财务 × 指标 =====
- question: 茅台最新一期的营收和净资产收益率
  gold_sql: >
    SELECT i.report_date, i.revenue, f.roe
    FROM income_statement i
    JOIN financial_indicator f ON i.code=f.code AND i.report_date=f.report_date
    WHERE i.code='600519'
    ORDER BY i.report_date DESC LIMIT 1
  difficulty: join
  tags: [JOIN, 财务]
  answerable_on: "2026-03-31"

# ===== aggregate: 时序聚合 / top-k =====
- question: 茅台连续三年的 ROE 分别是多少
  gold_sql: SELECT report_date, roe FROM financial_indicator WHERE code='600519' ORDER BY report_date DESC LIMIT 3
  difficulty: aggregate
  tags: [时序, top-k, 财务]
  answerable_on: "2026-03-31"

- question: 评估股里 ROE 最高的前五只股票
  gold_sql: >
    SELECT code, MAX(roe) AS max_roe
    FROM financial_indicator
    WHERE roe IS NOT NULL
    GROUP BY code ORDER BY max_roe DESC LIMIT 5
  difficulty: aggregate
  tags: [全市场, top-k, 聚合]
  answerable_on: "2026-03-31"

# ===== domain: 融资融券 / 板块 =====
- question: 最近一周融资余额变化
  gold_sql: SELECT date, margin_balance FROM margin_daily ORDER BY date DESC LIMIT 5
  difficulty: domain
  tags: [资金面, 时序]
  answerable_on: "2026-03-31"

# ===== out_of_scope 陷阱题(范围门增益 ablation 用) =====
- question: 帮我写一段 Python 排序代码
  gold_sql: null
  difficulty: simple
  tags: [out_of_scope, 代码]
  answerable_on: "2026-03-31"

- question: 茅台明天会涨吗
  gold_sql: null
  difficulty: simple
  tags: [out_of_scope, 预测]
  answerable_on: "2026-03-31"
```

（执行期扩量规则：按 §8.1 配额补到 simple 40 / join 50 / aggregate 40 / domain 20；每补一条跑 Step 6 校验脚本锁定可执性。out_of_scope 陷阱题集中放 `tags:[out_of_scope]`，用于范围门增益 ablation。）

- [ ] **Step 6：写 gold 校验脚本**

Create `scripts/validate_gold.py`：

```python
"""校验评测集 gold_sql 在冻结 eval.duckdb 上可执且返回确定行(spec §12.3)。

用法: python scripts/validate_gold.py [--eval data/eval.duckdb] [--dataset panwen/eval/dataset/questions.yaml]
退出码 0 = 全部 gold 可执；非 0 = 有 gold 失败(打印哪条)。
"""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from panwen.data import db
from panwen.eval import loader


def main(eval_path: str = "data/eval.duckdb",
         dataset: str = "panwen/eval/dataset/questions.yaml") -> int:
    items = loader.load_dataset(dataset)
    conn = db.connect(eval_path, read_only=True)
    failures = 0
    try:
        for it in items:
            if it.gold_sql is None:
                continue  # out_of_scope 题跳过
            try:
                rows = conn.execute(it.gold_sql).fetchall()
                print(f"[ok] {it.difficulty:10s} {it.question[:30]:30s} → {len(rows)} 行")
            except Exception as e:
                failures += 1
                print(f"[FAIL] {it.question[:40]}\n       {e}")
    finally:
        conn.close()
    print(f"\n{'全部 gold 可执' if failures == 0 else f'{failures} 条 gold 失败'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 7：跑 loader 测试 + gold 校验 + 提交**

Run: `pytest tests/eval/test_loader.py -v`
Expected: PASS。

Run（需 Task 0 已冻结 eval.duckdb）: `python scripts/validate_gold.py`
Expected: starter 集 gold 全部 `[ok]`；若有 FAIL，修正该条 gold_sql 的表/列名对齐 schema（gold 必须可执）。

```bash
git add panwen/eval/ tests/eval/test_loader.py scripts/validate_gold.py pyproject.toml
git commit -m "feat(eval): Task4 dataset (starter ~20 + stratification rules) + gold validator"
```

---

## Task 5：fewshot_store（eval 集 Q→SQL 检索）

**Files:**
- Create: `panwen/rag/fewshot_store.py`
- Test: `tests/rag/test_fewshot_store.py`

**Interfaces:**
- Consumes: `panwen.eval.loader.load_dataset`（Task 4）、`rag.embed`
- Produces: `FewshotStore`，`.retrieve(question, k) -> list[FewshotExample]`；`FewshotExample{question, sql}`

**设计（spec §7）**：自建集天然带问题文本，比 Hermes 反推 NL 更干净。只索引 `gold_sql is not None` 的题（out_of_scope 不进 fewshot）。

- [ ] **Step 1：写失败测试**

Create `tests/rag/test_fewshot_store.py`：

```python
"""Task 5: fewshot_store 检索 top-k (Q→SQL)。"""
from panwen.rag import fewshot_store as fs
from panwen.rag.embed import FakeEmbedder


def _toy_examples():
    return [
        fs.FewshotExample(question="茅台净利润", sql="SELECT net_profit FROM income_statement WHERE code='600519'"),
        fs.FewshotExample(question="CPI 同比", sql="SELECT value FROM macro_series WHERE name LIKE '%CPI%'"),
    ]


def test_retrieve_returns_topk_sql():
    store = fs.FewshotStore(_toy_examples(), embedder=FakeEmbedder(dim=32), k=1)
    out = store.retrieve("贵州茅台的利润")
    assert len(out) == 1
    assert "net_profit" in out[0].sql


def test_skips_none_sql():
    # gold_sql=None 的 out_of_scope 题不进 fewshot
    ex = _toy_examples() + [fs.FewshotExample(question="写代码", sql=None)]
    store = fs.FewshotStore(ex, embedder=FakeEmbedder(dim=32), k=5)
    assert len(store.retrieve("任意")) <= 2  # 只有 2 条非 None
```

- [ ] **Step 2：跑测试确认失败**

Run: `pytest tests/rag/test_fewshot_store.py -v`
Expected: FAIL（`fewshot_store` 不存在）

- [ ] **Step 3：写 fewshot_store.py**

Create `panwen/rag/fewshot_store.py`：

```python
"""fewshot_store(config.use_fewshot) —— 检索 eval 集 (Q→SQL) 作 few-shot(spec §7)。

复用 embed 基建。只索引 gold_sql 非空的题(out_of_scope 不进)。
"""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np

from panwen.rag.embed import Embedder, cosine_topk


@dataclass(frozen=True)
class FewshotExample:
    question: str
    sql: str | None


class FewshotStore:
    def __init__(self, examples: list[FewshotExample], embedder: Embedder, k: int = 3):
        self.k = k
        self.embedder = embedder
        self._examples = [e for e in examples if e.sql]   # 丢 None
        self._matrix = self.embedder.embed_texts([e.question for e in self._examples]) \
            if self._examples else np.zeros((0, embedder.dim), dtype=np.float32)

    @classmethod
    def from_dataset(cls, dataset_path: str, embedder: Embedder, k: int = 3) -> "FewshotStore":
        from panwen.eval import loader
        items = loader.load_dataset(dataset_path)
        return cls([FewshotExample(q=i.question, sql=i.gold_sql) for i in items],
                   embedder=embedder, k=k)

    def retrieve(self, question: str) -> list[FewshotExample]:
        if not self._examples:
            return []
        q = self.embedder.embed_texts([question])[0]
        idx = cosine_topk(q, self._matrix, k=self.k)
        return [self._examples[i] for i in idx]
```

- [ ] **Step 4：跑测试确认通过 + 提交**

Run: `pytest tests/rag/test_fewshot_store.py -v`
Expected: PASS（2 项）

```bash
git add panwen/rag/fewshot_store.py tests/rag/test_fewshot_store.py
git commit -m "feat(rag): Task5 fewshot_store (eval Q->SQL retrieval)"
```

---

## Task 6：归一化 + 范围门 + 澄清（管线 ①②）

**Files:**
- Create: `panwen/agent/normalize.py`、`panwen/agent/clarify.py`
- Create: `panwen/prompts/v1/normalize.txt`、`panwen/prompts/v1/clarify.txt`
- Test: `tests/agent/test_normalize.py`、`tests/agent/test_clarify.py`

**Interfaces:**
- Consumes: `agent.backend.AgentBackend`、`agent.types.{NormQuery,AgentResult}`
- Produces:
  - `normalize.py`: `normalize(question, backend) -> NormQuery`（规则解析 + LLM 实体/意图）
  - `clarify.py`: `dispatch(norm, backend) -> AgentResult | None`（None = sql_answerable 继续；非 None = 早退结果）

- [ ] **Step 1：写失败测试 normalize**

Create `tests/agent/test_normalize.py`：

```python
"""Task 6: ① normalize —— 规则解析 + LLM 实体/意图(用固定响应 mock)。"""
import json
from panwen.agent import normalize as nz
from panwen.agent.types import Message


class _StubBackend:
    """固定返回 intent/entities JSON 的假后端。"""
    def __init__(self, payload: dict):
        self._payload = payload
    def chat(self, messages, **kw):
        from panwen.agent.types import ChatResult
        return ChatResult(content=json.dumps(self._payload, ensure_ascii=False),
                          tool_calls=[], raw={})


def test_rule_parses_date_range_and_topk():
    be = _StubBackend({"intent": "sql_answerable", "entities": {"code": "600519"}})
    n = nz.normalize("茅台近三年的ROE", be)
    assert n.intent == "sql_answerable"
    assert n.date_range is not None   # 规则解出「近三年」
    assert n.entities.get("code") == "600519"


def test_rule_parses_topk_and_order():
    be = _StubBackend({"intent": "sql_answerable", "entities": {}})
    n = nz.normalize("ROE 最高的前五只股票", be)
    assert n.top_k == 5 and n.order == "desc"


def test_intent_out_of_scope_from_llm():
    be = _StubBackend({"intent": "out_of_scope", "entities": {}})
    n = nz.normalize("帮我写排序代码", be)
    assert n.intent == "out_of_scope"


def test_intent_needs_clarify_from_llm():
    be = _StubBackend({"intent": "needs_clarify", "entities": {}})
    n = nz.normalize("这只股的ROE", be)
    assert n.intent == "needs_clarify"
```

- [ ] **Step 2：跑测试确认失败**

Run: `pytest tests/agent/test_normalize.py -v`
Expected: FAIL（`normalize` 不存在）

- [ ] **Step 3：写 normalize.py + prompts**

Create `panwen/prompts/v1/normalize.txt`：

```
你是 A 股 Text-to-SQL 助手的归一化器。给定用户中文问题，输出 JSON：
{"intent": "sql_answerable" | "needs_clarify" | "out_of_scope", "entities": {...}}
- intent=sql_answerable: 能用本系统结构化数据(行情/财务/板块/资金面/宏观)查询回答。
- intent=needs_clarify: 缺必要信息(哪只股/时间窗歧义/筛选条件空)。
- intent=out_of_scope: 闲聊/非金融/非查询/交易/预测涨跌/写代码——做不了的动作。
- entities: 抽取实体，如 {"code":"600519","board":"白酒","metric":"ROE"}。股票名→代码(茅台=600519,平安=000001,…)。
只输出 JSON，不要解释。
```

Create `panwen/agent/normalize.py`：

```python
"""① normalize —— 规则(日期/单位/top-k) + LLM(实体/意图) 混合(spec §5 ①)。

意图分类折叠进同一次 LLM 调用(零额外成本)。
"""
from __future__ import annotations
import json
import re
from pathlib import Path

from panwen.agent.backend import AgentBackend
from panwen.agent.types import NormQuery

_PROMPT = (Path(__file__).resolve().parents[2] / "prompts" / "v1" / "normalize.txt").read_text(encoding="utf-8")


# --- 规则层 ---
def _parse_date_range(q: str) -> tuple[str, str] | None:
    m = re.search(r"近(?:期|期)?(\d+)\s*年", q)
    if m:
        return (f"{'2026'-int(m.group(1))}-01-01", "2026-03-31")  # 简化：相对当前冻结年
    if "最近一年" in q or "近一年" in q:
        return ("2025-01-01", "2026-03-31")
    return None


def _parse_topk(q: str) -> tuple[int | None, str | None]:
    m = re.search(r"(?:前|top\s*)(\d+)", q, re.IGNORECASE)
    if m:
        order = "desc" if re.search(r"最高|最大|最多", q) else ("asc" if re.search(r"最低|最小|最少", q) else "desc")
        return int(m.group(1)), order
    return None, None


# --- LLM 层 ---
def _llm_understand(question: str, backend: AgentBackend) -> dict:
    from panwen.agent.types import Message, ChatResult
    resp = backend.chat(
        [Message(role="system", content=_PROMPT), Message(role="user", content=question)],
        temperature=0.0, response_format={"type": "json_object"})
    try:
        return json.loads(resp.content)
    except json.JSONDecodeError:
        return {"intent": "needs_clarify", "entities": {}}  # 解析失败 → 安全降级为澄清


def normalize(question: str, backend: AgentBackend) -> NormQuery:
    dr = _parse_date_range(question)
    topk, order = _parse_topk(question)
    llm = _llm_understand(question, backend)
    intent = llm.get("intent", "needs_clarify")
    if intent not in {"sql_answerable", "needs_clarify", "out_of_scope"}:
        intent = "needs_clarify"
    return NormQuery(
        question=question, date_range=dr, top_k=topk, order=order,
        entities=llm.get("entities", {}), intent=intent,
    )
```

- [ ] **Step 4：跑 normalize 测试确认通过**

Run: `pytest tests/agent/test_normalize.py -v`
Expected: PASS（4 项）

- [ ] **Step 5：写失败测试 clarify（dispatch 三分支）**

Create `tests/agent/test_clarify.py`：

```python
"""Task 6: ② dispatch —— 按 intent 确定性三分支。"""
import json
from panwen.agent import clarify
from panwen.agent.normalize import NormQuery


def _norm(intent):
    return NormQuery(question="x", date_range=None, top_k=None, order=None,
                     entities={}, intent=intent)


def test_out_of_scope_early_exit():
    res = clarify.dispatch(_norm("out_of_scope"), _NoBackend())
    assert res.status == "out_of_scope"
    assert res.sql is None
    assert "不在我的能力范围" in res.reply


def test_needs_clarify_early_exit():
    res = clarify.dispatch(_norm("needs_clarify"), _ClarifyBackend("请说明是哪只股票"))
    assert res.status == "clarified"
    assert res.reply == "请说明是哪只股票"


def test_sql_answerable_returns_none_to_continue():
    res = clarify.dispatch(_norm("sql_answerable"), _NoBackend())
    assert res is None  # 继续走 ③-⑨


class _NoBackend:
    def chat(self, messages, **kw):
        raise AssertionError("sql_answerable/out_of_scope 不应调 LLM")


class _ClarifyBackend:
    def __init__(self, q): self._q = q
    def chat(self, messages, **kw):
        from panwen.agent.types import ChatResult
        return ChatResult(content=self._q, tool_calls=[], raw={})
```

- [ ] **Step 6：跑测试确认失败**

Run: `pytest tests/agent/test_clarify.py -v`
Expected: FAIL（`clarify.dispatch` 不存在）

- [ ] **Step 7：写 clarify.py + prompt**

Create `panwen/prompts/v1/clarify.txt`：

```
用户问题意图为 needs_clarify(缺必要信息)。请用一句中文提出最关键的澄清问题(如「请问是哪只股票？」或「时间范围是？」)。只输出问题本身。
```

Create `panwen/agent/clarify.py`：

```python
"""② dispatch —— 按 intent 确定性三分支(spec §5 ②)。

返回 AgentResult(早退) 或 None(继续 ③-⑨)。
"""
from __future__ import annotations
from pathlib import Path

from panwen.agent.backend import AgentBackend
from panwen.agent.types import NormQuery, AgentResult, Message

_CLARIFY_PROMPT = (Path(__file__).resolve().parents[2] / "prompts" / "v1" / "clarify.txt").read_text(encoding="utf-8")
_OUT_OF_SCOPE_REPLY = ("这不在我的能力范围（我只能查 A 股结构化数据：行情/财务/板块/资金面/宏观），"
                       "试试问『茅台近三年 ROE』？")


def dispatch(norm: NormQuery, backend: AgentBackend) -> AgentResult | None:
    if norm.intent == "out_of_scope":
        return AgentResult(status="out_of_scope", sql=None, rows=None,
                           reply=_OUT_OF_SCOPE_REPLY, explanation=None, trace=[])
    if norm.intent == "needs_clarify":
        resp = backend.chat(
            [Message(role="system", content=_CLARIFY_PROMPT),
             Message(role="user", content=norm.question)],
            temperature=0.0)
        return AgentResult(status="clarified", sql=None, rows=None,
                           reply=resp.content.strip(), explanation=None, trace=[])
    return None  # sql_answerable → 继续 ③-⑨
```

- [ ] **Step 8：跑 clarify 测试确认通过 + 提交**

Run: `pytest tests/agent/test_normalize.py tests/agent/test_clarify.py -v`
Expected: PASS

```bash
git add panwen/agent/normalize.py panwen/agent/clarify.py panwen/prompts/ tests/agent/test_normalize.py tests/agent/test_clarify.py
git commit -m "feat(agent): Task6 normalize + scope-gate dispatch (3-way intent)"
```

---

## Task 7：Agent 主循环（③-⑨ 管线 + ⑧ 自纠错 + 解释）

**Files:**
- Create: `panwen/agent/loop.py`、`panwen/agent/explainer.py`
- Create: `panwen/prompts/v1/plan_generate.txt`、`panwen/prompts/v1/explain.txt`
- Test: `tests/agent/test_loop.py`、`tests/agent/test_explainer.py`

**Interfaces:**
- Consumes: Task 1 (backend/config/types)、Task 2 (validator)、Task 3 (schema_retriever)、Task 5 (fewshot_store)、Task 6 (normalize/clarify)、`panwen.data.db`
- Produces: `run_query(question, conn, backend, rag, fewshot, config) -> AgentResult`

**管线**：①normalize → ②dispatch(早退) → ③④rag 上下文 → ⑤generate(plan+sql 一次调用) → ⑥validate → ⑦execute(timeout) → ⑧self_correct(预算 N=3，复用上下文+追错误反馈) → ⑨explain。

- [ ] **Step 1：写失败测试 loop（mock backend 确定性序列）**

Create `tests/agent/test_loop.py`：

```python
"""Task 7: run_query 集成测(mock backend 确定性序列)。覆盖 §11 全分支。"""
import json
import pytest
from panwen.agent import loop, config
from panwen.agent.types import Message, ChatResult
from panwen.data import db, schema
from panwen.rag.embed import FakeEmbedder
from panwen.rag.schema_retriever import SchemaRetriever
from panwen.rag.fewshot_store import FewshotStore


class _ScriptedBackend:
    """按预设脚本依次返回 content。"""
    def __init__(self, scripts: list[str]):
        self.scripts = list(scripts)
        self.calls = 0
    def chat(self, messages, **kw):
        c = self.scripts.pop(0) if self.scripts else "{}"
        self.calls += 1
        return ChatResult(content=c, tool_calls=[], raw={})


def _setup_conn(tmp_path):
    conn = db.connect(str(tmp_path / "t.duckdb"))
    db.init_schema(conn)
    conn.execute("INSERT INTO financial_indicator VALUES ('600519','2025-12-31',30.0,25.0,90.0,45.0,30.0,NULL,NULL)")
    return conn


def _rag():
    return SchemaRetriever(embedder=FakeEmbedder(dim=16), topk=3)


def _fewshot():
    return FewshotStore([], embedder=FakeEmbedder(dim=16), k=2)


def test_out_of_scope_early_exit(tmp_path):
    be = _ScriptedBackend([json.dumps({"intent": "out_of_scope", "entities": {}})])
    res = loop.run_query("写代码", _setup_conn(tmp_path), be, _rag(), _fewshot(), config.AgentConfig())
    assert res.status == "out_of_scope"
    assert be.calls == 1  # 只调了 normalize，没往下走


def test_one_shot_success(tmp_path):
    # normalize(sql_answerable) → generate(出 SQL) → validate 过 → execute 过 → explain
    be = _ScriptedBackend([
        json.dumps({"intent": "sql_answerable", "entities": {"code": "600519"}}),
        json.dumps({"sql": "SELECT roe FROM financial_indicator WHERE code='600519' ORDER BY report_date DESC LIMIT 1"}),
        '{"assumptions":[],"confidence":0.9,"summary":"茅台最新ROE"}',
    ])
    res = loop.run_query("茅台最新ROE", _setup_conn(tmp_path), be, _rag(), _fewshot(), config.AgentConfig())
    assert res.status == "answered"
    assert res.rows is not None and len(res.rows) >= 1
    assert res.explanation is not None


def test_selfcorrect_one_round_success(tmp_path):
    # generate 先给一个不存在的列(被 ValidSQL 拦) → 自纠错给正确 SQL
    be = _ScriptedBackend([
        json.dumps({"intent": "sql_answerable", "entities": {"code": "600519"}}),
        json.dumps({"sql": "SELECT fake_col FROM financial_indicator WHERE code='600519'"}),  # 拦
        json.dumps({"sql": "SELECT roe FROM financial_indicator WHERE code='600519'"}),       # 纠对
        '{"assumptions":[],"confidence":0.7,"summary":"纠错后出结果"}',
    ])
    res = loop.run_query("茅台ROE", _setup_conn(tmp_path), be, _rag(), _fewshot(), config.AgentConfig())
    assert res.status == "answered"


def test_selfcorrect_budget_exhausted(tmp_path):
    # 连续 3 次都给错列 → 用尽预算 → status=answered 但低置信(或 failed)
    bad = json.dumps({"sql": "SELECT fake_col FROM financial_indicator"})
    be = _ScriptedBackend([
        json.dumps({"intent": "sql_answerable", "entities": {}}),
        bad, bad, bad, bad,  # 初次 + 3 轮纠错全错
        '{"assumptions":["未能生成有效SQL"],"confidence":0.1,"summary":"自纠错用尽预算"}',
    ])
    res = loop.run_query("茅台ROE", _setup_conn(tmp_path), be, _rag(), _fewshot(), config.AgentConfig())
    assert res.status in ("answered", "failed")
    assert res.explanation.confidence < 0.5
```

- [ ] **Step 2：跑测试确认失败**

Run: `pytest tests/agent/test_loop.py -v`
Expected: FAIL（`loop.run_query` 不存在）

- [ ] **Step 3：写 plan_generate prompt + explainer**

Create `panwen/prompts/v1/plan_generate.txt`：

```
你是 A 股 Text-to-SQL 生成器。基于 schema 子集与 few-shot，为用户问题生成 DuckDB 只读 SQL。
规则：
1. 只读(SELECT/CTE/子查询/UNION)，禁写操作。
2. 用户值用 ? 参数绑定(如 WHERE code = ?)，不要字符串拼接。
3. 文本列(name/code)禁聚合；数值列(revenue/roe/...)可聚合。
4. 多表须 JOIN ... ON 显式连接。
输出 JSON：{"plan": "<简述思路,可空>", "sql": "<DuckDB SQL，用户值用 ?>}
只输出 JSON。
```

Create `panwen/prompts/v1/explain.txt`：

```
你是解释器。基于用户问题、执行的 SQL 与结果，输出 JSON：
{"assumptions": ["..."], "confidence": 0.0-1.0, "summary": "<一句中文摘要>"}
confidence：结果可信度(数据完整且 SQL 简单→高；自纠错过/数据缺失→低)。只输出 JSON。
```

Create `panwen/agent/explainer.py`：

```python
"""⑨ explainer —— LLM 出 Explanation{assumptions,confidence,summary}。"""
from __future__ import annotations
import json
from pathlib import Path

from panwen.agent.backend import AgentBackend
from panwen.agent.types import Explanation, Message

_PROMPT = (Path(__file__).resolve().parents[2] / "prompts" / "v1" / "explain.txt").read_text(encoding="utf-8")


def explain(question: str, sql: str | None, rows: list | None,
            low_confidence: bool, backend: AgentBackend) -> Explanation:
    ctx = f"问题: {question}\nSQL: {sql}\n结果行数: {len(rows) if rows else 0}"
    try:
        resp = backend.chat(
            [Message(role="system", content=_PROMPT), Message(role="user", content=ctx)],
            temperature=0.0, response_format={"type": "json_object"})
        d = json.loads(resp.content)
    except Exception:
        d = {"assumptions": [], "confidence": 0.0, "summary": "解释生成失败"}
    conf = float(d.get("confidence", 0.0))
    if low_confidence:
        conf = min(conf, 0.5)
    return Explanation(assumptions=list(d.get("assumptions", [])),
                       confidence=conf, summary=str(d.get("summary", "")))
```

- [ ] **Step 4：写 loop.py**

Create `panwen/agent/loop.py`：

```python
"""run_query —— 9 步确定性管线 + ⑧ 有界自纠错(spec §5)。

每阶段受 config 开关控制；失败不中断，记 trace。
"""
from __future__ import annotations
import json
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from pathlib import Path

from panwen.agent.backend import AgentBackend
from panwen.agent.config import AgentConfig
from panwen.agent.types import (AgentResult, Message, TraceStep, NormQuery)
from panwen.agent.normalize import normalize
from panwen.agent.clarify import dispatch
from panwen.agent.explainer import explain
from panwen.validsql.validator import validate_sql, build_schema_view
from panwen.rag.schema_retriever import SchemaRetriever
from panwen.rag.fewshot_store import FewshotStore

_PLAN_GEN_PROMPT = (Path(__file__).resolve().parents[2] / "prompts" / "v1" / "plan_generate.txt").read_text(encoding="utf-8")


def _execute_sql(sql: str, conn, timeout_s: int) -> tuple[list[dict] | None, str | None]:
    """⑦ 只读执行 + 检查 6(超时)。返回 (rows, rootCause)。"""
    def _run():
        cur = conn.execute(sql)
        cols = [d[0] for d in cur.description] if cur.description else []
        return [dict(zip(cols, r)) for r in cur.fetchall()]
    try:
        with ThreadPoolExecutor(max_workers=1) as ex:
            rows = ex.submit(_run).result(timeout=timeout_s)
        return rows, None
    except FuturesTimeout:
        return None, "ROOT_TIMEOUT"
    except Exception as e:
        return None, f"ROOT_EXEC:{type(e).__name__}:{e}"


def _generate(norm: NormQuery, schema_subset, fewshot, conn, backend, config,
              feedback: str | None, prev_sql: str | None) -> tuple[str | None, str | None]:
    """⑤ 一次 LLM 调用出 (sql, plan)。feedback 非空 = 自纠错回灌错误。
    用户值由 LLM 用 ? 占位；执行前用 norm 参数绑定(MVP：内联绑定)。
    """
    schema_text = "\n".join(f"- {e.table}{'.'+e.column if e.column else ''}: {e.doc}" for e in schema_subset)
    fewshot_text = "\n".join(f"Q: {e.question}\nSQL: {e.sql}" for e in fewshot) if fewshot else "(无)"
    user = (f"问题: {norm.question}\n日期区间: {norm.date_range}\ntop_k: {norm.top_k} 排序: {norm.order}\n"
            f"实体: {norm.entities}\n\n相关 schema:\n{schema_text}\n\nfew-shot:\n{fewshot_text}")
    if feedback:
        user += f"\n\n上一条 SQL 失败，错误反馈:\n{feedback}\n上次SQL:\n{prev_sql}\n请修正。"
    resp = backend.chat(
        [Message(role="system", content=_PLAN_GEN_PROMPT), Message(role="user", content=user)],
        temperature=0.0, response_format={"type": "json_object"})
    try:
        d = json.loads(resp.content)
        return d.get("sql"), d.get("plan")
    except json.JSONDecodeError:
        return None, None


def run_query(question: str, conn, backend: AgentBackend, rag: SchemaRetriever,
              fewshot: FewshotStore, config: AgentConfig) -> AgentResult:
    trace: list[TraceStep] = []

    # ① normalize(含意图/范围门)
    try:
        norm = normalize(question, backend)
        trace.append(TraceStep("normalize", True, f"intent={norm.intent}"))
    except Exception as e:
        return _failed(question, backend, trace, f"normalize 异常: {e}", config)

    # ② dispatch(三分支早退)
    early = dispatch(norm, backend)
    if early is not None:
        early.trace = trace
        return early

    # ③④ rag 上下文(常开 schema；fewshot 受开关)
    schema_subset = rag.retrieve(question, )[:config.schema_topk] if hasattr(rag, "retrieve") else []
    shots = fewshot.retrieve(question)[:config.fewshot_k] if config.use_fewshot else []
    trace.append(TraceStep("rag", True, f"schema={len(schema_subset)} fewshot={len(shots)}"))

    sv = build_schema_view()
    feedback: str | None = None
    prev_sql: str | None = None
    last_sql, last_rows, last_root = None, None, None
    budget = config.selfcorrect_budget + 1 if config.use_selfcorrect else 1

    for attempt in range(budget):
        # ⑤ generate
        sql, _plan = _generate(norm, schema_subset, shots, conn, backend, config, feedback, prev_sql)
        trace.append(TraceStep("generate", sql is not None, f"attempt={attempt} sql={'有' if sql else '无'}"))
        if not sql:
            break
        prev_sql = sql
        last_sql = sql

        # ⑥ validate(检查 1-5)
        if config.use_validsql:
            issues = validate_sql(sql, sv, conn=conn)
            if issues:
                last_root = issues[0].rootCause
                feedback = "; ".join(f"{i.code}:{i.message}" for i in issues)
                trace.append(TraceStep("validate", False, feedback[:80], last_root))
                continue
        trace.append(TraceStep("validate", True, "checks 1-5 pass"))

        # ⑦ execute(检查 6 超时)
        rows, root = _execute_sql(sql, conn, config.exec_timeout_s)
        last_rows, last_root = rows, root
        if root is None:
            trace.append(TraceStep("execute", True, f"{len(rows)} rows"))
            break  # 成功
        feedback = root
        trace.append(TraceStep("execute", False, root[:80], root))

    # ⑨ explain
    answered = last_rows is not None and last_root is None
    status = "answered" if answered else "failed"
    explanation = explain(question, last_sql, last_rows,
                          low_confidence=(not answered), backend=backend)
    trace.append(TraceStep("explain", True, f"conf={explanation.confidence}"))
    return AgentResult(status=status, sql=last_sql, rows=last_rows, reply=None,
                       explanation=explanation, trace=trace)


def _failed(question, backend, trace, detail, config) -> AgentResult:
    from panwen.agent.types import Explanation
    return AgentResult(status="failed", sql=None, rows=None, reply=None,
                       explanation=Explanation([], 0.0, detail), trace=trace)
```

注：`SchemaRetriever.retrieve(question)` 签名是 `retrieve(question)`（无 k 形参，k 在构造时定）；上面对 `hasattr(rag,"retrieve")` 做了防御性切片。实现期若签名不一致，以 Task 3 的 `retrieve(self, question)` 为准对齐。

- [ ] **Step 5：写 explainer 测试**

Create `tests/agent/test_explainer.py`：

```python
"""Task 7: ⑨ explainer。"""
import json
from panwen.agent import explainer as ex
from panwen.agent.types import ChatResult


class _BE:
    def __init__(self, payload): self._p = payload
    def chat(self, messages, **kw):
        return ChatResult(content=json.dumps(self._p), tool_calls=[], raw={})


def test_explain_parses_json():
    e = ex.explain("茅台ROE", "SELECT roe...", [{"roe": 30.0}], False,
                   _BE({"assumptions": ["a"], "confidence": 0.9, "summary": "ROE 30%"}))
    assert e.confidence == 0.9 and e.summary == "ROE 30%"


def test_low_confidence_caps_at_half():
    e = ex.explain("x", "SELECT 1", None, True,
                   _BE({"assumptions": [], "confidence": 0.9, "summary": "s"}))
    assert e.confidence <= 0.5
```

- [ ] **Step 6：跑 loop + explainer 测试确认通过**

Run: `pytest tests/agent/test_loop.py tests/agent/test_explainer.py -v`
Expected: PASS。若 sqlglot 检查对某 SQL 误判（如参数化检查对 `code='600519'` 返回 ROOT_UNPARAM 触发自纠错），调整测试夹具的 SQL 或 loop 行为使其自洽——但**保持校验语义不变**（ROOT_UNPARAM 是设计意图，one_shot_success 夹具的 SQL 应改用 `code=?` 绑定以通过校验；或接受它走 1 轮自纠错）。实现期按"生成 SQL 用 `?`，执行前内联绑定 norm.entities 的值"对齐。

- [ ] **Step 7：全量回归 + 提交**

Run: `pytest -v`
Expected: 全绿（数据层 + 新增 agent/validsql/rag/eval 全过）。

```bash
git add panwen/agent/loop.py panwen/agent/explainer.py panwen/prompts/v1/plan_generate.txt panwen/prompts/v1/explain.txt tests/agent/test_loop.py tests/agent/test_explainer.py
git commit -m "feat(agent): Task7 run_query pipeline (3-9) + bounded self-correct + explainer"
```

---

## Task 8：评测 runner + ablation + panel + make eval

**Files:**
- Create: `panwen/eval/runner.py`、`panwen/eval/ablation.py`、`panwen/eval/panel.py`
- Modify: `Makefile`（新增 `eval` 目标）
- Test: `tests/eval/test_runner.py`、`tests/eval/test_ablation.py`

**Interfaces:**
- Consumes: Task 4 (loader/dataset)、Task 7 (loop)、Task 1 (config)、`data/eval.duckdb`
- Produces: `run_eval(...) -> EvalReport`、`run_ablation(...) -> 表`、`make eval` 一键复现。

- [ ] **Step 1：写失败测试 runner（toy gold/pred）**

Create `tests/eval/test_runner.py`：

```python
"""Task 8: 执行准确率 + F1 计算(toy gold/pred)。"""
from panwen.eval import runner as R


def test_exec_acc_exact_match():
    assert R.row_sets_equal([{"a": 1}], [{"a": 1}]) is True
    assert R.row_sets_equal([{"a": 1}], [{"a": 2}]) is False


def test_f1_partial_match():
    # gold 3 行, pred 2 行(1 行命中) → P=1/2, R=1/3
    gold = [{"a": 1}, {"a": 2}, {"a": 3}]
    pred = [{"a": 1}, {"a": 9}]
    p, r, f1 = R.pr_f1(gold, pred)
    assert abs(p - 0.5) < 1e-6 and abs(r - 1/3) < 1e-6 and f1 > 0


def test_f1_empty_pred():
    p, r, f1 = R.pr_f1([{"a": 1}], [])
    assert f1 == 0.0
```

- [ ] **Step 2：跑测试确认失败**

Run: `pytest tests/eval/test_runner.py -v`
Expected: FAIL（`runner` 不存在）

- [ ] **Step 3：写 runner.py**

Create `panwen/eval/runner.py`：

```python
"""eval runner(spec §8.2) —— 单配置跑全集 → exec_acc + F1。

执行准确率(主): pred 与 gold 在 eval.duckdb 上结果集一致。
F1 软评分: 部分行匹配给 0..1。
"""
from __future__ import annotations
from dataclasses import dataclass
from panwen.data import db
from panwen.eval.loader import load_dataset, EvalItem


@dataclass
class ItemResult:
    question: str
    difficulty: str
    correct: bool
    f1: float


@dataclass
class EvalReport:
    exec_acc: float
    mean_f1: float
    n: int
    items: list[ItemResult]


def _exec(conn, sql: str | None) -> list[dict]:
    """执行 SQL → dict 行列表(用 cursor.description 取列名)。"""
    if not sql:
        return []
    cur = conn.execute(sql)
    cols = [d[0] for d in cur.description] if cur.description else []
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def row_sets_equal(a: list[dict], b: list[dict]) -> bool:
    return sorted(map(tuple, (sorted(d.items()) for d in a))) == \
           sorted(map(tuple, (sorted(d.items()) for d in b)))


def pr_f1(gold: list[dict], pred: list[dict]) -> tuple[float, float, float]:
    g = {tuple(sorted(d.items())) for d in gold}
    p = {tuple(sorted(d.items())) for d in pred}
    if not p:
        return 0.0, 0.0, 0.0
    tp = len(g & p)
    prec = tp / len(p)
    rec = tp / len(g) if g else 0.0
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
    return prec, rec, f1


def run_eval(dataset_path: str, eval_db: str, predict_fn, tags_filter: list[str] | None = None) -> EvalReport:
    """predict_fn(question) -> (pred_sql, pred_rows). gold 从 eval_db 跑。"""
    items = load_dataset(dataset_path)
    if tags_filter:
        items = [i for i in items if any(t in i.tags for t in tags_filter)]
    conn = db.connect(eval_db, read_only=True)
    results: list[ItemResult] = []
    try:
        for it in items:
            gold_rows = _exec(conn, it.gold_sql)
            pred_sql, pred_rows = predict_fn(it.question)
            correct = row_sets_equal(gold_rows, pred_rows or [])
            _, _, f1 = pr_f1(gold_rows, pred_rows or [])
            results.append(ItemResult(it.question, it.difficulty, correct, f1))
    finally:
        conn.close()
    n = len(results)
    acc = sum(r.correct for r in results) / n if n else 0.0
    mf1 = sum(r.f1 for r in results) / n if n else 0.0
    return EvalReport(exec_acc=acc, mean_f1=mf1, n=n, items=results)
```

- [ ] **Step 4：跑 runner 测试确认通过**

Run: `pytest tests/eval/test_runner.py -v`
Expected: PASS（3 项）

- [ ] **Step 5：写失败测试 ablation**

Create `tests/eval/test_ablation.py`：

```python
"""Task 8: ablation 开关组合矩阵(spec §8.3)。"""
from panwen.eval import ablation as ab


def test_config_matrix_has_baseline_and_full():
    matrix = ab.config_matrix()
    # 第一行 = 全关 baseline, 最后一行 = 全开
    assert matrix[0] == ab.agent_config(False, False, False, False)
    assert matrix[-1] == ab.agent_config(True, True, True, True)
    assert len(matrix) == 5  # §8.3 五行


def test_agent_config_fields():
    c = ab.agent_config(use_plan=True, use_fewshot=True, use_validsql=False, use_selfcorrect=False)
    assert c.use_plan and c.use_fewshot
    assert not c.use_validsql and not c.use_selfcorrect
```

- [ ] **Step 6：跑测试确认失败**

Run: `pytest tests/eval/test_ablation.py -v`
Expected: FAIL（`ablation` 不存在）

- [ ] **Step 7：写 ablation.py + panel.py**

Create `panwen/eval/ablation.py`：

```python
"""逐组件 ablation(spec §8.3) —— 遍历 AgentConfig 开关组合 → 边际贡献表。

数字 make eval 实测填，绝不编造。
"""
from __future__ import annotations
from panwen.agent.config import AgentConfig


def agent_config(use_plan: bool, use_fewshot: bool, use_validsql: bool, use_selfcorrect: bool) -> AgentConfig:
    return AgentConfig(use_plan=use_plan, use_fewshot=use_fewshot,
                       use_validsql=use_validsql, use_selfcorrect=use_selfcorrect)


def config_matrix() -> list[AgentConfig]:
    """§8.3 五行配置(1-shot baseline → 逐组件叠加 → 全开)。"""
    return [
        agent_config(False, False, False, False),  # 1-shot baseline
        agent_config(False, True,  False, False),  # + Few-shot
        agent_config(True,  True,  False, False),  # + Plan
        agent_config(True,  True,  True,  False),  # + ValidSQL
        agent_config(True,  True,  True,  True),   # + 自纠错 (全开)
    ]


def run_ablation(dataset_path: str, eval_db: str, run_with_config) -> list[dict]:
    """run_with_config(config) -> EvalReport。返回边际贡献表(dict 列表)。

    边际贡献 = 当行 acc - 上一行 acc。
    """
    matrix = config_matrix()
    rows = []
    prev_acc = None
    labels = ["1-shot baseline", "+Few-shot", "+Plan", "+ValidSQL", "+自纠错"]
    for label, cfg in zip(labels, matrix):
        rep = run_with_config(cfg)
        marginal = None if prev_acc is None else rep.exec_acc - prev_acc
        rows.append({"config": label, "exec_acc": rep.exec_acc,
                     "mean_f1": rep.mean_f1, "marginal": marginal, "n": rep.n})
        prev_acc = rep.exec_acc
    return rows
```

Create `panwen/eval/panel.py`：

```python
"""维度面板(spec §8.4) —— 按 difficulty / SQL 结构切片准确率。"""
from __future__ import annotations
from collections import defaultdict
from panwen.eval.runner import EvalReport


def by_difficulty(report: EvalReport) -> dict[str, float]:
    buckets = defaultdict(list)
    for it in report.items:
        buckets[it.difficulty].append(it.correct)
    return {d: sum(v) / len(v) for d, v in buckets.items()}


def render(report: EvalReport) -> str:
    lines = [f"总体执行准确率: {report.exec_acc:.1%} ({report.n} 题)",
             f"平均 F1: {report.mean_f1:.3f}", "", "按难度切片:"]
    for d, acc in sorted(by_difficulty(report).items()):
        lines.append(f"  {d:12s} {acc:.1%}")
    return "\n".join(lines)
```

- [ ] **Step 8：跑 ablation 测试确认通过 + 加 make eval**

Modify `Makefile`，`.PHONY` 加 `eval`，新增：

```makefile
eval:
	mkdir -p data
	python scripts/run_eval.py
```

Create `scripts/run_eval.py`（一键复现入口；指标实测打印）：

```python
"""make eval 入口：跑全集 + ablation 矩阵，打印实测指标(spec §8.3)。

注意：指标全部实测，绝不编造。范围门增益为可选加分项(本脚本默认不跑)。
"""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from panwen.agent import backend, config
from panwen.agent.loop import run_query
from panwen.eval import runner, ablation, panel
from panwen.rag.embed import BgeEmbedder
from panwen.rag.schema_retrieever import SchemaRetriever
from panwen.rag.fewshot_store import FewshotStore

DATASET = "panwen/eval/dataset/questions.yaml"
EVAL_DB = "data/eval.duckdb"


def _build_rag_fewshot(cfg):
    emb = BgeEmbedder()
    rag = SchemaRetriever(emb, topk=cfg.schema_topk, cache_dir="data/rag_cache")
    fs = FewshotStore.from_dataset(DATASET, emb, k=cfg.fewshot_k)
    return rag, fs


def _predict(cfg):
    be = backend.make_backend("deepseek")
    rag, fs = _build_rag_fewshot(cfg)

    def fn(question):
        from panwen.data import db
        conn = db.connect(EVAL_DB, read_only=True)
        try:
            res = run_query(question, conn, be, rag, fs, cfg)
            return res.sql, res.rows
        finally:
            conn.close()
    return fn


def main():
    print("=" * 60)
    print("单配置(全开)评测")
    fn = _predict(config.AgentConfig())
    rep = runner.run_eval(DATASET, EVAL_DB, fn)
    print(panel.render(rep))

    print("\n" + "=" * 60)
    print("逐组件 ablation(边际贡献)")
    rows = ablation.run_ablation(DATASET, EVAL_DB,
                                 lambda cfg: runner.run_eval(DATASET, EVAL_DB, _predict(cfg)))
    print(f"{'配置':18s} {'exec_acc':>9s} {'mean_f1':>8s} {'边际':>8s}")
    for r in rows:
        m = "—" if r["marginal"] is None else f"{r['marginal']:+.1%}"
        print(f"{r['config']:18s} {r['exec_acc']:>8.1%} {r['mean_f1']:>8.3f} {m:>8s}")
    print("\n注：指标为自建冻结集实测，非跨域基准。范围门增益为可选加分项(未跑)。")


if __name__ == "__main__":
    main()
```

- [ ] **Step 9：跑测试 + 全量回归 + 提交**

Run: `pytest tests/eval/ -v`
Expected: PASS（loader + runner + ablation + substrate）。
Run: `pytest -v`（全量回归）
Expected: 全绿。

```bash
git add panwen/eval/runner.py panwen/eval/ablation.py panwen/eval/panel.py scripts/run_eval.py tests/eval/test_runner.py tests/eval/test_ablation.py Makefile
git commit -m "feat(eval): Task8 runner + ablation matrix + panel + make eval"
```

---

## 自检（Self-Review，执行前过一遍）

**1. Spec 覆盖**
- §2 锁定决策逐项：确定性管线(Task7)、DeepSeek(Task1)、bge(Task3)、150题(Task4)、ValidSQL全开(Task2)、N=3(Task7 config)、plan+generate一次调用(Task7 _generate)、范围门(Task6 normalize+clarify)、混合归一化(Task6) ✓
- §3 主架构(Task7)、§4 模块结构(文件结构表全对齐)、§5 数据流9步(Task7 run_query + Task6 ①②)、§6 ValidSQL(Task2 检查1-5 + Task7 检查6)、§7 RAG(Task3+5)、§8 评测(Task4+8)、§9 接口(types/backend/config/loop/validator/runner 签名一致)、§10 错误处理(Task7 try/except+trace+rootCause+降置信)、§11 测试(每 Task 测试覆盖 §11 清单)、§12 Task0前置(Task0) ✓
- §1 非目标：demo UI 明确排除（本计划不含，单独规划）✓

**2. 占位符扫描**：无 TBD/TODO；Task4 的「starter ~20 + 扩量到150」是内容任务（有具体 starter + 规则 + 校验脚本），非占位符。所有代码步骤含真实实现。

**3. 类型一致性**：
- `AgentResult.status` 枚举 `answered|clarified|out_of_scope|failed`（Task1 定义，Task6/7 使用一致）✓
- `NormQuery.intent` 同三值（Task1 定义，Task6/7 一致）✓
- `validate_sql(sql, schema_view, conn=None)` 签名（Task2 定义，Task7 调用 `validate_sql(sql, sv, conn=conn)` 一致）✓
- `SchemaRetriever.retrieve(question)`（Task3 定义）；Task7 `_rag.retrieve(question)` 一致 ✓
- `run_query(question, conn, backend, rag, fewshot, config)`（Task7 定义，Task8 `run_eval` predict_fn 包装一致）✓
- `EvalReport{exec_acc,mean_f1,n,items}`（Task8 runner 定义，ablation/panel 使用一致）✓

**4. 已知实现期裁决点**（非占位符，执行时按此对齐）：
- Task2 检查5参数化：生成 SQL 用 `?`，执行前用 norm.entities 内联绑定（loop Task7 Step6 已注）。
- Task4 冻结 as-of：Task0 Step8 实测后统一对齐 questions.yaml 的 `answerable_on`。
- Task4 starter→150：按 §8.1 配额补写，每条跑 `validate_gold.py`。
- Task7 one_shot_success 夹具的 SQL 若被 ROOT_UNPARAM 拦截，按「生成用 `?`」对齐夹具或接受走 1 轮自纠错。
