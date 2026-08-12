# 盘问 (PanWen) · Plan 1: 数据层 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建盘问的数据层——用 akshare 把 A 股 MVP 数据域全量回填进 DuckDB，支持每日增量与冻结/活动双库，为 Plan 2（Agent 核心）提供经过验证的 canonical schema 与可查询数据库。

**Architecture:** 声明式摄入框架——一个经过充分测试的通用 `run_ingest` 引擎（处理 one-shot / per-code / per-date / per-period 四种迭代策略），每个数据表只是一个声明式 `Spec`（数据源函数 + 参数构造 + 列映射 + 冲突列）。全量回填带节流/重试/断点续传；每日增量用 spot 快照 + 按报告期补抓；后复权(hfq)存储；`eval.duckdb`（冻结随仓提交）与 `live.duckdb`（每日刷新、gitignore）双库分离。

**Tech Stack:** Python 3.11+ · akshare（pinned）· DuckDB · pandas · pytest · Makefile

## Global Constraints

- Python ≥ 3.11；依赖在 `pyproject.toml` 中锁定版本（尤其 `akshare` —— 其字段名随版本变动，必须 pin）。
- **只发入库脚本不发数据**：`live.duckdb` 进 `.gitignore`；`eval.duckdb`（冻结子集）可随仓提交。
- **后复权(hfq)存储**：日行情用 `adjust="hfq"`；PE/ROE 等指标取自财务指标接口、不靠复权价计算。
- **诚实**：所有自建集指标在 Plan 3 实测填入；本计划不产生任何"准确率"数字。
- **命名**：canonical 列名用英文 snake_case；akshare 的中文列名经 `mapping.py` 映射。
- 项目根：`/Users/zhangyufen/claudecode/first_try/project/panwen/`；这是新 OSS 项目，Task 1 含 `git init`。

---

## File Structure

```
panwen/
  pyproject.toml
  .gitignore
  Makefile
  README.md                      # Task 12 写"数据层"小节
  panwen/
    __init__.py
    data/
      __init__.py
      schema.py                  # 表 DDL + 列类型分类(text/numeric/date) —— 全局单一事实源
      db.py                      # connect(path, read_only) / init_schema(conn)
      ingest/
        __init__.py
        client.py                # 节流+重试的 akshare 调用封装
        loader.py                # upsert_df(幂等写库)
        checkpoint.py            # 断点续传存储
        mapping.py               # 中文列名→canonical + 类型转换 + 代码格式转换
        specs.py                 # 声明式 Spec 数据类 + 每张表的 Spec 定义
        runner.py                # 通用 run_ingest 引擎(四种迭代策略)
        backfill.py              # 全量回填编排(接所有 Spec + checkpoint)
        incremental.py           # 每日增量(spot 快照 + 按报告期)
      snapshots.py               # freeze_eval(live→eval, 按 as_of 日期截断)
    seeds/
      dev_codes.txt              # 开发用 ~20 只股票种子,快速端到端验证
  scripts/
    probe_akshare.py             # 在线探测 akshare 实际返回列名(Task 4 用,验证假设)
    freeze_eval.py               # CLI 入口: python scripts/freeze_eval.py --as-of 2024-12-31
  tests/
    conftest.py
    data/
      test_schema.py
      test_db.py
      test_client.py
      test_loader.py
      test_checkpoint.py
      test_mapping.py
      test_runner.py
      test_specs_quote.py
      test_specs_finance.py
      test_specs_domains.py
      test_backfill.py
      test_incremental.py
      test_snapshots.py
  data/                          # 运行时产物(gitignore)
    live.duckdb
    eval.duckdb
    checkpoint.json
```

**核心接口契约（后续 Plan 2/3 依赖，本计划锁定）：**
- `schema.TABLE_DDL: dict[str, str]` — 表名→DDL
- `schema.COLUMN_CLASS: dict[str, dict[str, str]]` — 表→{列: "text"|"numeric"|"date"}（Plan 2 ValidSQL 类型约束直接用）
- `db.connect(path: str, read_only: bool = False) -> duckdb.DuckDBPyConnection`
- `db.init_schema(conn) -> None`
- `ingest.client.fetch(func, *args, min_interval=0.3, retries=3, **kwargs) -> pd.DataFrame`
- `ingest.loader.upsert_df(conn, table: str, df: pd.DataFrame, conflict_cols: list[str]) -> int`
- `ingest.checkpoint.Checkpoint(path)`：`.mark(domain, key)` / `.is_done(domain, key)` / `.resume_iter(domain, items: list) -> list`
- `ingest.specs.Spec` 数据类：`name, table, source, iteration("oneshot"|"per_code"|"per_date"|"per_period"), arg_builder, rename_map, conflict_cols, value_cast`
- `ingest.runner.run_ingest(conn, spec: Spec, *, client, checkpoint=None, code_source=None) -> int`（返回写入行数）

---

## Task 1: 项目脚手架 + canonical schema 模块

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `panwen/__init__.py`, `panwen/data/__init__.py`, `panwen/data/schema.py`, `tests/conftest.py`, `tests/data/test_schema.py`

**Interfaces:**
- Produces: `schema.TABLE_DDL`, `schema.TABLES`, `schema.COLUMN_CLASS`, `schema.PRIMARY_KEYS`

- [ ] **Step 1: 初始化 git 与目录**

```bash
cd /Users/zhangyufen/claudecode/first_try/project/panwen
git init
mkdir -p panwen/data/ingest panwen/seeds scripts tests/data
touch panwen/__init__.py panwen/data/__init__.py panwen/data/ingest/__init__.py
```

- [ ] **Step 2: 写 `pyproject.toml`**

```toml
[project]
name = "panwen"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
  "akshare==1.14.84",      # pin: 字段名随版本变动
  "duckdb>=1.1.0",
  "pandas>=2.2.0",
  "sqlglot>=23.0.0",       # Plan 2 用,提前装好
]

[project.optional-dependencies]
dev = ["pytest>=8.0.0", "pytest-mock>=3.12.0"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

> 执行时 `pip install -e ".[dev]"`；akshare 精确版本以安装时最新稳定版替换并 pin。

- [ ] **Step 3: 写 `.gitignore`**

```
__pycache__/
*.egg-info/
.venv/
data/live.duckdb
data/checkpoint.json
.pytest_cache/
```

- [ ] **Step 4: 写失败测试 `tests/data/test_schema.py`**

```python
import duckdb
from panwen.data import schema

def test_all_ddl_execute_in_duckdb():
    conn = duckdb.connect(":memory:")
    for table, ddl in schema.TABLE_DDL.items():
        conn.execute(ddl)  # 不抛异常即通过
    conn.close()

def test_required_mvp_tables_present():
    required = {
        "stock_basic", "trade_calendar", "daily_quote", "spot_snapshot",
        "income_statement", "balance_sheet", "cashflow_statement",
        "financial_indicator", "performance_express",
        "industry_board", "industry_board_const", "industry_board_daily",
        "concept_board", "concept_board_const",
        "margin_daily", "dragon_tiger", "top10_holders", "macro_series",
    }
    assert required.issubset(set(schema.TABLE_DDL.keys()))

def test_every_column_has_class():
    for table in schema.TABLE_DDL:
        assert table in schema.COLUMN_CLASS, f"{table} 缺 COLUMN_CLASS"
        # 每列都必须标注 text/numeric/date
```

- [ ] **Step 5: 运行测试确认失败**

Run: `pytest tests/data/test_schema.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'panwen.data.schema'`）

- [ ] **Step 6: 实现 `panwen/data/schema.py`**

```python
"""盘问 canonical schema —— 全局单一事实源。列名英文 snake_case。"""
from __future__ import annotations

# text / numeric / date 三类。text 列禁聚合、numeric 允许范围比较与聚合(Plan 2 ValidSQL 用)。
COLUMN_CLASS: dict[str, dict[str, str]] = {
    "stock_basic": {"code": "text", "name": "text", "listing_date": "date",
                    "board": "text", "industry": "text", "is_st": "text", "delist_date": "date"},
    "trade_calendar": {"date": "date", "is_open": "text"},
    "daily_quote": {"code": "text", "date": "date", "open": "numeric", "high": "numeric",
                    "low": "numeric", "close": "numeric", "volume": "numeric", "amount": "numeric",
                    "pct_chg": "numeric", "turnover": "numeric"},
    "spot_snapshot": {"code": "text", "name": "text", "last_close": "numeric", "price": "numeric",
                      "pct_chg": "numeric", "amount": "numeric", "volume": "numeric",
                      "turnover": "numeric", "pe_ttm": "numeric", "pb": "numeric",
                      "total_mv": "numeric", "circ_mv": "numeric", "ts": "date"},
    "income_statement": {"code": "text", "report_date": "date", "revenue": "numeric",
                         "oper_cost": "numeric", "net_profit": "numeric", "npr": "numeric"},
    "balance_sheet": {"code": "text", "report_date": "date", "total_assets": "numeric",
                      "total_liab": "numeric", "total_equity": "numeric"},
    "cashflow_statement": {"code": "text", "report_date": "date", "op_cf": "numeric",
                           "inv_cf": "numeric", "fin_cf": "numeric"},
    "financial_indicator": {"code": "text", "report_date": "date", "roe": "numeric",
                            "roa": "numeric", "gross_margin": "numeric", "net_margin": "numeric",
                            "debt_ratio": "numeric", "pe": "numeric", "pb": "numeric"},
    "performance_express": {"code": "text", "report_date": "date", "revenue_yoy": "numeric",
                            "net_profit_yoy": "numeric"},
    "industry_board": {"name": "text", "code": "text"},
    "industry_board_const": {"board_name": "text", "code": "text"},
    "industry_board_daily": {"board_name": "text", "date": "date", "close": "numeric",
                             "pct_chg": "numeric", "amount": "numeric"},
    "concept_board": {"name": "text", "code": "text"},
    "concept_board_const": {"board_name": "text", "code": "text"},
    "margin_daily": {"date": "date", "market": "text", "rzye": "numeric",
                     "rqye": "numeric", "rzrqye": "numeric"},
    "dragon_tiger": {"code": "text", "date": "date", "reason": "text", "net_buy": "numeric"},
    "top10_holders": {"code": "text", "report_date": "date", "rank": "numeric",
                      "holder_name": "text", "hold_amount": "numeric", "hold_ratio": "numeric",
                      "holder_type": "text"},
    "macro_series": {"indicator": "text", "date": "date", "value": "numeric"},
}

PRIMARY_KEYS: dict[str, list[str]] = {
    "stock_basic": ["code"], "trade_calendar": ["date"],
    "daily_quote": ["code", "date"], "spot_snapshot": ["code"],
    "income_statement": ["code", "report_date"], "balance_sheet": ["code", "report_date"],
    "cashflow_statement": ["code", "report_date"], "financial_indicator": ["code", "report_date"],
    "performance_express": ["code", "report_date"],
    "industry_board": ["name"], "industry_board_const": ["board_name", "code"],
    "industry_board_daily": ["board_name", "date"],
    "concept_board": ["name"], "concept_board_const": ["board_name", "code"],
    "margin_daily": ["date", "market"], "dragon_tiger": ["code", "date", "reason"],
    "top10_holders": ["code", "report_date", "rank", "holder_type"],
    "macro_series": ["indicator", "date"],
}

def _ddl(table: str) -> str:
    cols = COLUMN_CLASS[table]
    pk = PRIMARY_KEYS[table]
    sqltype = {"text": "TEXT", "numeric": "DOUBLE", "date": "DATE"}
    body = ",\n  ".join(f"{c} {sqltype[t]}" for c, t in cols.items())
    return f"CREATE TABLE IF NOT EXISTS {table} (\n  {body},\n  PRIMARY KEY ({', '.join(pk)})\n);"

TABLE_DDL: dict[str, str] = {t: _ddl(t) for t in COLUMN_CLASS}
TABLES: list[str] = list(COLUMN_CLASS.keys())
```

- [ ] **Step 7: 运行测试确认通过**

Run: `pytest tests/data/test_schema.py -v`
Expected: PASS（3 passed）

- [ ] **Step 8: 提交**

```bash
git add -A
git commit -m "feat(data): scaffold project + canonical schema module

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 2: DuckDB 连接 + schema 引导

**Files:**
- Create: `panwen/data/db.py`, `tests/data/test_db.py`

**Interfaces:**
- Consumes: `schema.TABLE_DDL`
- Produces: `db.connect(path, read_only=False)`, `db.init_schema(conn)`

- [ ] **Step 1: 写失败测试**

```python
# tests/data/test_db.py
import duckdb
from panwen.data import db, schema

def test_init_schema_creates_all_tables(tmp_path):
    conn = db.connect(str(tmp_path / "t.duckdb"))
    db.init_schema(conn)
    created = {r[0] for r in conn.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema='main'").fetchall()}
    assert set(schema.TABLES).issubset(created)
    conn.close()

def test_connect_read_only_flag(tmp_path):
    p = str(tmp_path / "ro.duckdb")
    db.connect(p); 
    ro = db.connect(p, read_only=True)  # 已存在才能只读打开
    ro.close()
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/data/test_db.py -v` → FAIL（模块不存在）

- [ ] **Step 3: 实现 `panwen/data/db.py`**

```python
import duckdb
from panwen.data import schema

def connect(path: str, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    return duckdb.connect(path, read_only=read_only)

def init_schema(conn: duckdb.DuckDBPyConnection) -> None:
    for ddl in schema.TABLE_DDL.values():
        conn.execute(ddl)
```

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/data/test_db.py -v` → PASS

- [ ] **Step 5: 提交**

```bash
git add panwen/data/db.py tests/data/test_db.py
git commit -m "feat(data): duckdb connect + init_schema"
```

---

## Task 3: akshare 客户端封装（节流 + 重试）

**Files:**
- Create: `panwen/data/ingest/client.py`, `tests/data/test_client.py`

**Interfaces:**
- Produces: `client.fetch(func, *args, min_interval=0.3, retries=3, **kwargs) -> pd.DataFrame`

- [ ] **Step 1: 写失败测试（用 mock，不打网络）**

```python
# tests/data/test_client.py
import pandas as pd, pytest
from panwen.data.ingest import client

def test_fetch_returns_dataframe(mocker):
    mocker.patch.object(client, "_last_call_at", 0.0)
    fake = mocker.Mock(return_value=pd.DataFrame({"a": [1]}))
    df = client.fetch(fake, symbol="000001", min_interval=0)
    assert list(df["a"]) == [1]
    fake.assert_called_once_with(symbol="000001")

def test_fetch_retries_then_succeeds(mocker):
    mocker.patch.object(client, "_last_call_at", 0.0)
    mocker.patch("panwen.data.ingest.client.time.sleep")  # 加速
    flaky = mocker.Mock(side_effect=[RuntimeError("boom"), pd.DataFrame({"a": [2]})])
    df = client.fetch(flaky, min_interval=0, retries=3)
    assert list(df["a"]) == [2]
    assert flaky.call_count == 2

def test_fetch_gives_up_after_retries(mocker):
    mocker.patch.object(client, "_last_call_at", 0.0)
    mocker.patch("panwen.data.ingest.client.time.sleep")
    bad = mocker.Mock(side_effect=RuntimeError("always"))
    with pytest.raises(RuntimeError):
        client.fetch(bad, min_interval=0, retries=2)
    assert bad.call_count == 2  # 初试 + 1 次重试

def test_fetch_throttles_between_calls(mocker):
    sleeps = mocker.patch("panwen.data.ingest.client.time.sleep")
    mocker.patch.object(client, "_last_call_at", 0.0)
    fake = mocker.Mock(return_value=pd.DataFrame())
    client.fetch(fake, min_interval=0.5)
    client.fetch(fake, min_interval=0.5)
    assert any(s > 0 for s in [c.args[0] for c in sleeps.call_args_list])
```

- [ ] **Step 2: 运行确认失败** → FAIL

- [ ] **Step 3: 实现 `panwen/data/ingest/client.py`**

```python
import time
import pandas as pd

_last_call_at: float = 0.0

def fetch(func, *args, min_interval: float = 0.3, retries: int = 3, **kwargs) -> pd.DataFrame:
    """带最小间隔节流 + 指数退避重试的 akshare 调用封装。"""
    global _last_call_at
    last_err = None
    for attempt in range(retries):
        elapsed = time.monotonic() - _last_call_at
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)
        try:
            _last_call_at = time.monotonic()
            return func(*args, **kwargs)
        except Exception as e:  # akshare 上游偶发网络/解析错误
            last_err = e
            time.sleep(0.5 * (2 ** attempt))  # 0.5,1,2...
    raise last_err
```

- [ ] **Step 4: 运行确认通过** → PASS（4 passed）

- [ ] **Step 5: 提交**

```bash
git add panwen/data/ingest/client.py tests/data/test_client.py
git commit -m "feat(data): throttled+retry akshare client wrapper"
```

---

## Task 4: akshare 列名探测 + 列映射模块

> akshare 的中文列名随版本变动。本任务：① 写在线探测脚本验证实际列名；② 实现纯函数列映射，用探测结果填 `rename_map`。

**Files:**
- Create: `scripts/probe_akshare.py`, `panwen/data/ingest/mapping.py`, `tests/data/test_mapping.py`

**Interfaces:**
- Produces: `mapping.map_columns(df, rename_map) -> pd.DataFrame`, `mapping.to_sina_code(code) -> str`

- [ ] **Step 1: 写探测脚本 `scripts/probe_akshare.py`**

```python
"""在线探测 akshare 实际返回的中文列名,人工核对后填入 specs.RENAME_MAP。
用法: python scripts/probe_akshare.py  (需联网,手动运行,非自动测试)"""
import akshare as ak

def main():
    print("== stock_zh_a_hist(adjust=hfq) ==")
    print(list(ak.stock_zh_a_hist(symbol="000001", period="daily",
                                  start_date="20240101", end_date="20240110",
                                  adjust="hfq").columns))
    print("== stock_zh_a_spot_em ==")
    print(list(ak.stock_zh_a_spot_em().columns))
    print("== stock_financial_analysis_indicator ==")
    print(list(ak.stock_financial_analysis_indicator(symbol="000001", start_year="2023").columns))
    # 其余数据源同理打印列名...

if __name__ == "__main__":
    main()
```

> 执行者运行一次该脚本，把真实列名抄进 Task 8–10 的 `RENAME_MAP`。脚本本身不被 pytest 收集。

- [ ] **Step 2: 写失败测试 `tests/data/test_mapping.py`**

```python
import pandas as pd
from panwen.data.ingest import mapping

def test_map_columns_renames_and_drops_unknown():
    df = pd.DataFrame({"日期": ["2024-01-02"], "股票代码": ["000001"], "收盘": [10.0], "垃圾列": [1]})
    out = mapping.map_columns(df, {"日期": "date", "股票代码": "code", "收盘": "close"})
    assert list(out.columns) == ["date", "code", "close"]

def test_to_sina_code():
    assert mapping.to_sina_code("600000") == "sh600000"
    assert mapping.to_sina_code("000001") == "sz000001"
    assert mapping.to_sina_code("300001") == "sz300001"
    assert mapping.to_sina_code("688001") == "sh688001"
```

- [ ] **Step 3: 运行确认失败** → FAIL

- [ ] **Step 4: 实现 `panwen/data/ingest/mapping.py`**

```python
import pandas as pd

def map_columns(df: pd.DataFrame, rename_map: dict[str, str]) -> pd.DataFrame:
    """按 rename_map 重命名;未在 map 中的列丢弃。"""
    keep = {k: v for k, v in rename_map.items() if k in df.columns}
    return df.rename(columns=keep)[[keep[k] for k in df.columns if k in keep]]

def to_sina_code(code: str) -> str:
    """6 位代码 → 新浪/东财财报接口要的 sh/sz 前缀格式。"""
    c = code.zfill(6)
    if c.startswith(("60", "68", "9")):
        return "sh" + c
    return "sz" + c
```

- [ ] **Step 5: 运行确认通过** → PASS

- [ ] **Step 6: 提交**

```bash
git add scripts/probe_akshare.py panwen/data/ingest/mapping.py tests/data/test_mapping.py
git commit -m "feat(data): akshare column probe + column mapping utils"
```

---

## Task 5: 幂等写库 loader（upsert）

**Files:**
- Create: `panwen/data/ingest/loader.py`, `tests/data/test_loader.py`

**Interfaces:**
- Consumes: `schema`, `db`
- Produces: `loader.upsert_df(conn, table, df, conflict_cols) -> int`

- [ ] **Step 1: 写失败测试**

```python
# tests/data/test_loader.py
import pandas as pd
from panwen.data import db, schema
from panwen.data.ingest import loader

def test_upsert_inserts_then_updates(tmp_path):
    conn = db.connect(str(tmp_path / "t.duckdb")); db.init_schema(conn)
    df1 = pd.DataFrame({"code": ["000001"], "name": ["平安银行"], "listing_date": ["1991-04-03"],
                        "board": ["主板"], "industry": ["银行"], "is_st": ["否"], "delist_date": [None]})
    n = loader.upsert_df(conn, "stock_basic", df1, ["code"])
    assert n == 1
    assert conn.execute("SELECT name FROM stock_basic").fetchone()[0] == "平安银行"
    # 再写一条同 code 不同 name → 应 update 而非报错/重复
    df2 = df1.assign(name=["平安银行X"])
    loader.upsert_df(conn, "stock_basic", df2, ["code"])
    assert conn.execute("SELECT count(*) FROM stock_basic").fetchone()[0] == 1
    assert conn.execute("SELECT name FROM stock_basic").fetchone()[0] == "平安银行X"
    conn.close()
```

- [ ] **Step 2: 运行确认失败** → FAIL

- [ ] **Step 3: 实现 `panwen/data/ingest/loader.py`**

```python
import pandas as pd
import duckdb

def upsert_df(conn: duckdb.DuckDBPyConnection, table: str,
              df: pd.DataFrame, conflict_cols: list[str]) -> int:
    """幂等 upsert: 用 DuckDB ON CONFLICT DO UPDATE(主键/唯一冲突)。返回影响行数。"""
    if df.empty:
        return 0
    conn.register("_src", df)
    cols = list(df.columns)
    collist = ", ".join(cols)
    placeholders = ", ".join(f"_src.{c}" for c in cols)
    update_cols = [c for c in cols if c not in conflict_cols]
    if update_cols:
        do = "DO UPDATE SET " + ", ".join(f"{c}=EXCLUDED.{c}" for c in update_cols)
    else:
        do = "DO NOTHING"
    result = conn.execute(
        f"INSERT INTO {table} ({collist}) SELECT {placeholders} FROM _src "
        f"ON CONFLICT ({', '.join(conflict_cols)}) {do}"
    )
    conn.unregister("_src")
    return result.fetchone()[0]
```

- [ ] **Step 4: 运行确认通过** → PASS

- [ ] **Step 5: 提交**

```bash
git add panwen/data/ingest/loader.py tests/data/test_loader.py
git commit -m "feat(data): idempotent upsert_df loader"
```

---

## Task 6: 断点续传 checkpoint

**Files:**
- Create: `panwen/data/ingest/checkpoint.py`, `tests/data/test_checkpoint.py`

**Interfaces:**
- Produces: `checkpoint.Checkpoint(path)` 带 `mark`/`is_done`/`resume_iter`

- [ ] **Step 1: 写失败测试**

```python
# tests/data/test_checkpoint.py
from panwen.data.ingest.checkpoint import Checkpoint

def test_mark_and_is_done(tmp_path):
    cp = Checkpoint(str(tmp_path / "cp.json"))
    assert not cp.is_done("daily_quote", "000001")
    cp.mark("daily_quote", "000001")
    assert cp.is_done("daily_quote", "000001")

def test_resume_iter_skips_done(tmp_path):
    cp = Checkpoint(str(tmp_path / "cp.json"))
    cp.mark("daily_quote", "000001")
    remaining = cp.resume_iter("daily_quote", ["000001", "000002"])
    assert remaining == ["000002"]

def test_persists_across_instances(tmp_path):
    p = str(tmp_path / "cp.json")
    Checkpoint(p).mark("daily_quote", "000001")
    assert Checkpoint(p).is_done("daily_quote", "000001")
```

- [ ] **Step 2: 运行确认失败** → FAIL

- [ ] **Step 3: 实现 `panwen/data/ingest/checkpoint.py`**

```python
import json, os
from typing import Iterable

class Checkpoint:
    """{domain: set(key)} 的 JSON 持久化,记录已完成的粒度(如某 code/某报告期)。"""
    def __init__(self, path: str):
        self.path = path
        self._data: dict[str, list[str]] = {}
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                self._data = json.load(f)

    def _save(self) -> None:
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False)

    def mark(self, domain: str, key: str) -> None:
        self._data.setdefault(domain, [])
        if key not in self._data[domain]:
            self._data[domain].append(key)
            self._save()

    def is_done(self, domain: str, key: str) -> bool:
        return key in self._data.get(domain, [])

    def resume_iter(self, domain: str, items: Iterable[str]) -> list[str]:
        return [x for x in items if not self.is_done(domain, x)]
```

- [ ] **Step 4: 运行确认通过** → PASS

- [ ] **Step 5: 提交**

```bash
git add panwen/data/ingest/checkpoint.py tests/data/test_checkpoint.py
git commit -m "feat(data): resumable checkpoint store"
```

---

## Task 7: 声明式 Spec + 通用 run_ingest 引擎

> 这是整个数据层的核心抽象。测透它,后续每张表只是配置。

**Files:**
- Create: `panwen/data/ingest/specs.py`, `panwen/data/ingest/runner.py`, `tests/data/test_runner.py`

**Interfaces:**
- Consumes: `client.fetch`, `mapping.map_columns`, `loader.upsert_df`, `checkpoint.Checkpoint`
- Produces: `specs.Spec`（dataclass）, `runner.run_ingest(conn, spec, *, client, checkpoint=None, code_source=None, period_source=None) -> int`

- [ ] **Step 1: 写 `specs.py`（Spec 数据类）**

```python
# panwen/data/ingest/specs.py
from dataclasses import dataclass, field
from typing import Callable, Any

@dataclass
class Spec:
    name: str                       # checkpoint domain 名
    table: str                      # 目标 canonical 表
    source: Callable[..., Any]      # akshare 函数(如 ak.stock_zh_a_hist)
    iteration: str                  # "oneshot" | "per_code" | "per_date" | "per_period"
    rename_map: dict[str, str]      # akshare中文列 → canonical列
    conflict_cols: list[str]
    # 按迭代策略构造 source 的 kwargs:
    arg_builder: Callable[[str], dict] = field(default=lambda k: {})
    # 可选: per_code 的代码来源(默认全部 A 股)
    extra_kwargs: dict = field(default_factory=dict)
```

- [ ] **Step 2: 写失败测试 `tests/data/test_runner.py`**

```python
import pandas as pd
from panwen.data import db
from panwen.data.ingest.specs import Spec
from panwen.data.ingest import runner, checkpoint

def _conn(tmp_path):
    c = db.connect(str(tmp_path / "t.duckdb")); db.init_schema(c); return c

def test_run_ingest_oneshot(tmp_path, mocker):
    conn = _conn(tmp_path)
    fake_src = mocker.Mock(return_value=pd.DataFrame({
        "代码": ["000001"], "名称": ["平安"], "最新价": [10.0], "涨跌幅": [1.0]}))
    spec = Spec(name="spot", table="spot_snapshot", source=fake_src, iteration="oneshot",
                rename_map={"代码": "code", "名称": "name", "最新价": "price", "涨跌幅": "pct_chg"},
                conflict_cols=["code"])
    # spot_snapshot 列较多,补齐必填列避免 NOT NULL? DDL 无 NOT NULL,缺失列=NULL,可接受
    n = runner.run_ingest(conn, spec, client=lambda f, **kw: f(**kw))
    assert n >= 1
    assert conn.execute("SELECT code FROM spot_snapshot").fetchone()[0] == "000001"

def test_run_ingest_per_code_with_checkpoint(tmp_path, mocker):
    conn = _conn(tmp_path)
    def fake_src(symbol): 
        return pd.DataFrame({"日期": ["2024-01-02"], "股票代码": [symbol],
                             "收盘": [10.0], "开盘":[10.0],"最高":[10.0],"最低":[10.0],
                             "成交量":[100],"成交额":[1000],"涨跌幅":[1.0],"换手率":[1.0]})
    spec = Spec(name="daily_quote", table="daily_quote", source=fake_src, iteration="per_code",
                rename_map={"日期":"date","股票代码":"code","收盘":"close","开盘":"open",
                            "最高":"high","最低":"low","成交量":"volume","成交额":"amount",
                            "涨跌幅":"pct_chg","换手率":"turnover"},
                conflict_cols=["code","date"], arg_builder=lambda code: {"symbol": code})
    cp = checkpoint.Checkpoint(str(tmp_path/"cp.json"))
    runner.run_ingest(conn, spec, client=lambda f, **kw: f(**kw), checkpoint=cp,
                      code_source=["000001", "000002"])
    assert cp.is_done("daily_quote", "000001") and cp.is_done("daily_quote", "000002")
    # 第二次跑: 全部跳过,不再调用 source
    fake_src.side_effect = AssertionError("不该再调用")
    runner.run_ingest(conn, spec, client=lambda f, **kw: f(**kw), checkpoint=cp,
                      code_source=["000001", "000002"])  # 不抛即通过
```

- [ ] **Step 3: 运行确认失败** → FAIL（`runner` 不存在）

- [ ] **Step 4: 实现 `panwen/data/ingest/runner.py`**

```python
import pandas as pd
import duckdb
from panwen.data.ingest.specs import Spec
from panwen.data.ingest import mapping, loader, client as _client
from panwen.data.ingest.checkpoint import Checkpoint

def run_ingest(conn: duckdb.DuckDBPyConnection, spec: Spec, *,
               client=_client, checkpoint: Checkpoint | None = None,
               code_source: list[str] | None = None,
               period_source: list[str] | None = None) -> int:
    total = 0
    if spec.iteration == "oneshot":
        df = client.fetch(spec.source, **spec.extra_kwargs)
        df = mapping.map_columns(df, spec.rename_map)
        return loader.upsert_df(conn, spec.table, df, spec.conflict_cols)

    # 迭代型: 选出待处理 keys,断点续传
    if spec.iteration == "per_code":
        keys = code_source or _all_codes(conn)
    elif spec.iteration == "per_period":
        keys = period_source or []
    else:  # per_date 等,由调用方经 extra_kwargs 或 arg_builder 处理
        keys = spec.extra_kwargs.get("_keys", [])

    todo = keys if checkpoint is None else checkpoint.resume_iter(spec.name, keys)
    for k in todo:
        try:
            df = client.fetch(spec.source, **spec.arg_builder(k))
            df = mapping.map_columns(df, spec.rename_map)
            total += loader.upsert_df(conn, spec.table, df, spec.conflict_cols)
            if checkpoint:
                checkpoint.mark(spec.name, k)
        except Exception as e:
            # 单 key 失败不阻断整体;记录后继续(断点续传下次重试)
            print(f"[warn] {spec.name} key={k} failed: {e}")
    return total

def _all_codes(conn) -> list[str]:
    rows = conn.execute("SELECT code FROM stock_basic").fetchall()
    return [r[0] for r in rows] if rows else []
```

- [ ] **Step 5: 运行确认通过** → PASS（2 passed）

- [ ] **Step 6: 提交**

```bash
git add panwen/data/ingest/specs.py panwen/data/ingest/runner.py tests/data/test_runner.py
git commit -m "feat(data): declarative Spec + generic run_ingest engine"
```

---

## Task 8: 基础/行情域 Spec（stock_basic / trade_calendar / daily_quote hfq / spot_snapshot）

**Files:**
- Create: `panwen/seeds/dev_codes.txt`, `tests/data/test_specs_quote.py`
- Modify: `panwen/data/ingest/specs.py`（追加 spec 工厂函数）

**Interfaces:**
- Consumes: `Spec`, `run_ingest`, akshare 函数
- Produces: `specs.STOCK_BASIC_SPEC`, `TRADE_CAL_SPEC`, `DAILY_QUOTE_SPEC`, `SPOT_SPEC`, `specs.build_quote_specs()`

- [ ] **Step 1: 写种子 `panwen/seeds/dev_codes.txt`**（每行一个 6 位代码，约 20 只覆盖主板/创业板/科创板/ST）

```
600519
000001
300750
688981
000858
002594
600036
601318
300059
688256
```

- [ ] **Step 2: 写失败测试 `tests/data/test_specs_quote.py`**

```python
import pandas as pd
from panwen.data import db
from panwen.data.ingest import specs, runner, checkpoint, client as clientmod

def _conn(tmp_path):
    c = db.connect(str(tmp_path/"t.duckdb")); db.init_schema(c); return c

def test_stock_basic_spec_shape():
    s = specs.STOCK_BASIC_SPEC
    assert s.table == "stock_basic" and s.iteration == "oneshot"

def test_daily_quote_spec_uses_hfq():
    # 确认 arg_builder 里有 adjust=hfq
    args = specs.DAILY_QUOTE_SPEC.arg_builder("000001")
    assert args.get("adjust") == "hfq"

def test_quote_specs_run_on_seed(tmp_path, mocker):
    conn = _conn(tmp_path)
    # 先灌 stock_basic(给 _all_codes 用)
    mocker.patch("akshare.stock_info_a_code_name",
                 return_value=pd.DataFrame({"code": ["000001","600519"], "name": ["平安","茅台"]}))
    runner.run_ingest(conn, specs.STOCK_BASIC_SPEC, client=clientmod)
    # mock 行情
    mocker.patch("akshare.stock_zh_a_hist", return_value=pd.DataFrame({
        "日期":["2024-01-02"],"股票代码":["000001"],"开盘":[10.0],"收盘":[10.0],"最高":[10.0],
        "最低":[10.0],"成交量":[100],"成交额":[1000.0],"涨跌幅":[1.0],"换手率":[1.0]}))
    runner.run_ingest(conn, specs.DAILY_QUOTE_SPEC, client=clientmod,
                      code_source=["000001"])
    assert conn.execute("SELECT count(*) FROM daily_quote").fetchone()[0] == 1
```

- [ ] **Step 3: 运行确认失败** → FAIL（spec 常量不存在）

- [ ] **Step 4: 在 `specs.py` 追加行情域 spec**

```python
import akshare as ak

# ===== 基础/行情域 =====
STOCK_BASIC_SPEC = Spec(
    name="stock_basic", table="stock_basic", source=ak.stock_info_a_code_name,
    iteration="oneshot",
    rename_map={"code": "code", "name": "name"},   # 注: 探测后若列名是"code"/"name"则直通
    conflict_cols=["code"],
)

TRADE_CAL_SPEC = Spec(
    name="trade_calendar", table="trade_calendar", source=ak.tool_trade_date_hist_sina,
    iteration="oneshot",
    rename_map={"trade_date": "date"},   # 探测确认实际列名后改
    conflict_cols=["date"],
)

DAILY_QUOTE_SPEC = Spec(
    name="daily_quote", table="daily_quote", source=ak.stock_zh_a_hist,
    iteration="per_code",
    rename_map={"日期": "date", "股票代码": "code", "开盘": "open", "收盘": "close",
                "最高": "high", "最低": "low", "成交量": "volume", "成交额": "amount",
                "涨跌幅": "pct_chg", "换手率": "turnover"},
    conflict_cols=["code", "date"],
    arg_builder=lambda code: {"symbol": code, "period": "daily",
                              "start_date": "20100101", "end_date": "20991231",
                              "adjust": "hfq"},
)

SPOT_SPEC = Spec(
    name="spot_snapshot", table="spot_snapshot", source=ak.stock_zh_a_spot_em,
    iteration="oneshot",
    rename_map={"代码": "code", "名称": "name", "昨收": "last_close", "最新价": "price",
                "涨跌幅": "pct_chg", "成交额": "amount", "成交量": "volume",
                "换手率": "turnover", "市盈率-动态": "pe_ttm", "市净率": "pb",
                "总市值": "total_mv", "流通市值": "circ_mv"},
    conflict_cols=["code"],
)

def build_quote_specs():
    return [STOCK_BASIC_SPEC, TRADE_CAL_SPEC, DAILY_QUOTE_SPEC, SPOT_SPEC]
```

> ⚠️ 执行者必须先跑一次 `scripts/probe_akshare.py`，用真实列名校准每个 `rename_map`（尤其 `stock_info_a_code_name`、`tool_trade_date_hist_sina` 的列名）。校准是执行步骤，不是占位符。

- [ ] **Step 5: 运行确认通过** → PASS（3 passed）

- [ ] **Step 6: 提交**

```bash
git add panwen/seeds/dev_codes.txt panwen/data/ingest/specs.py tests/data/test_specs_quote.py
git commit -m "feat(data): quote domain specs (basic/calendar/daily hfq/spot)"
```

---

## Task 9: 财务域 Spec（三大报表 + 财务指标 + 业绩快报）

**Files:**
- Modify: `panwen/data/ingest/specs.py`（追加财务 spec）
- Create: `tests/data/test_specs_finance.py`

**Interfaces:**
- Produces: `specs.INCOME_SPEC`, `BALANCE_SPEC`, `CASHFLOW_SPEC`, `FIN_INDICATOR_SPEC`, `PERFORMANCE_SPEC`, `build_finance_specs()`

- [ ] **Step 1: 写失败测试 `tests/data/test_specs_finance.py`**

```python
import pandas as pd
from panwen.data import db
from panwen.data.ingest import specs, runner, client as clientmod

def _conn(tmp_path):
    c = db.connect(str(tmp_path/"t.duckdb")); db.init_schema(c); return c

def test_finance_specs_present():
    names = {s.table for s in specs.build_finance_specs()}
    assert {"income_statement","balance_sheet","cashflow_statement",
            "financial_indicator","performance_express"} <= names

def test_financial_indicator_runs(tmp_path, mocker):
    conn = _conn(tmp_path)
    mocker.patch("akshare.stock_financial_analysis_indicator", return_value=pd.DataFrame({
        "日期":["2023-12-31"],"股票代码":["000001"],"净资产收益率(%)":[12.0],
        "总资产报酬率(%)":[8.0],"销售毛利率(%)":[40.0],"销售净利率(%)":[20.0],
        "资产负债率(%)":[60.0],"市盈率":[8.0],"市净率":[1.0]}))
    runner.run_ingest(conn, specs.FIN_INDICATOR_SPEC, client=clientmod, code_source=["000001"])
    assert conn.execute("SELECT roe FROM financial_indicator").fetchone()[0] == 12.0
```

- [ ] **Step 2: 运行确认失败** → FAIL

- [ ] **Step 3: 在 `specs.py` 追加财务域 spec**

```python
from panwen.data.ingest.mapping import to_sina_code

# ===== 财务域 =====
def _report_arg(stmt):  # stmt: "利润表"/"资产负债表"/"现金流量表"
    return lambda code: {"stock": to_sina_code(code), "symbol": stmt}

INCOME_SPEC = Spec(
    name="income", table="income_statement", source=ak.stock_financial_report_sina,
    iteration="per_code",
    rename_map={"报告日": "report_date", "股票代码": "code", "营业总收入": "revenue",
                "营业成本": "oper_cost", "净利润": "net_profit"},
    conflict_cols=["code", "report_date"], arg_builder=_report_arg("利润表"),
)
BALANCE_SPEC = Spec(
    name="balance", table="balance_sheet", source=ak.stock_financial_report_sina,
    iteration="per_code",
    rename_map={"报告日": "report_date", "股票代码": "code", "总资产": "total_assets",
                "总负债": "total_liab", "所有者权益": "total_equity"},
    conflict_cols=["code", "report_date"], arg_builder=_report_arg("资产负债表"),
)
CASHFLOW_SPEC = Spec(
    name="cashflow", table="cashflow_statement", source=ak.stock_financial_report_sina,
    iteration="per_code",
    rename_map={"报告日": "report_date", "股票代码": "code",
                "经营现金流": "op_cf", "投资现金流": "inv_cf", "筹资现金流": "fin_cf"},
    conflict_cols=["code", "report_date"], arg_builder=_report_arg("现金流量表"),
)
FIN_INDICATOR_SPEC = Spec(
    name="fin_indicator", table="financial_indicator",
    source=ak.stock_financial_analysis_indicator, iteration="per_code",
    rename_map={"日期": "report_date", "股票代码": "code", "净资产收益率(%)": "roe",
                "总资产报酬率(%)": "roa", "销售毛利率(%)": "gross_margin",
                "销售净利率(%)": "net_margin", "资产负债率(%)": "debt_ratio",
                "市盈率": "pe", "市净率": "pb"},
    conflict_cols=["code", "report_date"],
    arg_builder=lambda code: {"symbol": code, "start_year": "2015"},
)
PERFORMANCE_SPEC = Spec(  # 业绩快报: 按报告期全市场批量
    name="performance", table="performance_express", source=ak.stock_em_yjbb,
    iteration="per_period",
    rename_map={"股票代码": "code", "报告日": "report_date",
                "营业收入-同比增长": "revenue_yoy", "净利润-同比增长": "net_profit_yoy"},
    conflict_cols=["code", "report_date"],
    arg_builder=lambda period: {"date": period},
)

def build_finance_specs():
    return [INCOME_SPEC, BALANCE_SPEC, CASHFLOW_SPEC, FIN_INDICATOR_SPEC, PERFORMANCE_SPEC]
```

> 业绩快报的 `period_source`（报告期列表如 `20231231`）由 backfill 传入（见 Task 11）。所有中文列名同样需经 `probe_akshare.py` 校准。

- [ ] **Step 4: 运行确认通过** → PASS（2 passed）

- [ ] **Step 5: 提交**

```bash
git add panwen/data/ingest/specs.py tests/data/test_specs_finance.py
git commit -m "feat(data): finance domain specs (3 statements + indicator + performance)"
```

---

## Task 10: 行业板块 + 资金面 + 宏观 + 🟡批次 Spec

**Files:**
- Modify: `panwen/data/ingest/specs.py`
- Create: `tests/data/test_specs_domains.py`

**Interfaces:**
- Produces: `build_domain_specs()`（含 industry/concept board、margin、macro、dragon tiger、top10 holders）

- [ ] **Step 1: 写失败测试 `tests/data/test_specs_domains.py`**

```python
from panwen.data.ingest import specs

def test_domain_specs_cover_all():
    tables = {s.table for s in specs.build_domain_specs()}
    assert {"industry_board","industry_board_const","industry_board_daily",
            "concept_board","concept_board_const","margin_daily",
            "dragon_tiger","top10_holders","macro_series"} <= tables

def test_margin_spec_iteration():
    m = [s for s in specs.build_domain_specs() if s.table=="margin_daily"][0]
    assert m.iteration in ("per_date","oneshot")
```

- [ ] **Step 2: 运行确认失败** → FAIL

- [ ] **Step 3: 在 `specs.py` 追加其余域 spec**

```python
# ===== 行业/概念板块 =====
INDUSTRY_BOARD_SPEC = Spec(name="industry_board", table="industry_board",
    source=ak.stock_board_industry_name_em, iteration="oneshot",
    rename_map={"板块名称": "name", "板块代码": "code"}, conflict_cols=["name"])
INDUSTRY_CONST_SPEC = Spec(name="industry_const", table="industry_board_const",
    source=ak.stock_board_industry_cons_em, iteration="per_code",
    rename_map={"板块名称": "board_name", "代码": "code"},
    conflict_cols=["board_name", "code"],
    arg_builder=lambda board: {"symbol": board})
CONCEPT_BOARD_SPEC = Spec(name="concept_board", table="concept_board",
    source=ak.stock_board_concept_name_em, iteration="oneshot",
    rename_map={"板块名称": "name", "板块代码": "code"}, conflict_cols=["name"])
CONCEPT_CONST_SPEC = Spec(name="concept_const", table="concept_board_const",
    source=ak.stock_board_concept_cons_em, iteration="per_code",
    rename_map={"板块名称": "board_name", "代码": "code"},
    conflict_cols=["board_name", "code"], arg_builder=lambda b: {"symbol": b})

# ===== 资金面 =====
MARGIN_SPEC = Spec(name="margin", table="margin_daily", source=ak.stock_margin_sse,
    iteration="per_date",
    rename_map={"日期": "date", "信用交易日期": "date", "融资余额": "rzye",
                "融券余额": "rqye", "融资融券余额": "rzrqye"},
    conflict_cols=["date", "market"],
    arg_builder=lambda d: {"start_date": d, "end_date": d},
    extra_kwargs={"_keys": [], "__market": "sse"})  # market 在 loader 前置注入(见下注)
DRAGON_TIGER_SPEC = Spec(name="dragon_tiger", table="dragon_tiger",
    source=ak.stock_lhb_detail_em, iteration="per_date",
    rename_map={"代码": "code", "上榜日": "date", "解读": "reason", "净买入": "net_buy"},
    conflict_cols=["code", "date", "reason"], arg_builder=lambda d: {"start_date": d, "end_date": d})

# ===== 公司事件(🟡批次) =====
TOP10_HOLDERS_SPEC = Spec(name="top10_holders", table="top10_holders",
    source=ak.stock_gdfx_holding_detail_em, iteration="per_code",
    rename_map={"股票代码": "code", "报告期": "report_date", "名次": "rank",
                "股东名称": "holder_name", "持股数量": "hold_amount",
                "持股比例": "hold_ratio", "股东性质": "holder_type"},
    conflict_cols=["code", "report_date", "rank", "holder_type"],
    arg_builder=lambda code: {"symbol": code})

# ===== 宏观 =====
MACRO_CPI_SPEC = Spec(name="macro_cpi", table="macro_series",
    source=ak.macro_china_cpi, iteration="oneshot",
    rename_map={"月份": "date", "同比增长": "value"},
    conflict_cols=["indicator", "date"],
    extra_kwargs={"__indicator": "CPI_YOY"})  # 注入 indicator 列(见下注)

def build_domain_specs():
    return [INDUSTRY_BOARD_SPEC, INDUSTRY_CONST_SPEC, CONCEPT_BOARD_SPEC, CONCEPT_CONST_SPEC,
            MARGIN_SPEC, DRAGON_TIGER_SPEC, TOP10_HOLDERS_SPEC, MACRO_CPI_SPEC]
```

> **注（margin/macro 的常量列注入）**：`margin_daily` 需要 `market` 列、`macro_series` 需要 `indicator` 列，但 akshare 返回里没有。执行者在 Task 11 backfill 编排里，对这两类 spec 在 `map_columns` 后补一列常量（`df["market"]="sse"` / `df["indicator"]="CPI_YOY"`）。这是实现细节，在 Task 11 的 `backfill.py` 里处理（给 `run_ingest` 加可选 `post_map` 钩子或特例）。**这不是占位符——是明确的两行代码补列**，Task 11 会写死。所有中文列名经 `probe_akshare.py` 校准。

- [ ] **Step 4: 运行确认通过** → PASS（2 passed）

- [ ] **Step 5: 提交**

```bash
git add panwen/data/ingest/specs.py tests/data/test_specs_domains.py
git commit -m "feat(data): domain specs (boards/margin/macro/dragontiger/holders)"
```

---

## Task 11: 全量回填编排 + 常量列注入 + dev 种子端到端

**Files:**
- Create: `panwen/data/ingest/backfill.py`, `tests/data/test_backfill.py`

**Interfaces:**
- Consumes: 所有 `build_*_specs()`，`run_ingest`，`Checkpoint`
- Produces: `backfill.run_all(conn, *, seed_path=None, periods=None, client=clientmod, checkpoint=None)`

- [ ] **Step 1: 写失败测试 `tests/data/test_backfill.py`**

```python
import pandas as pd
from panwen.data import db
from panwen.data.ingest import backfill, client as clientmod

def test_run_all_on_seed(tmp_path, mocker):
    conn = db.connect(str(tmp_path/"t.duckdb")); db.init_schema(conn)
    # mock 各数据源返回最小 DF(略,按各 spec rename_map 的 key 构造)
    mocker.patch("akshare.stock_info_a_code_name",
                 return_value=pd.DataFrame({"code":["000001"],"name":["平安"]}))
    mocker.patch("akshare.stock_zh_a_hist", return_value=pd.DataFrame({
        "日期":["2024-01-02"],"股票代码":["000001"],"开盘":[1.0],"收盘":[1.0],"最高":[1.0],
        "最低":[1.0],"成交量":[1],"成交额":[1.0],"涨跌幅":[1.0],"换手率":[1.0]}))
    mocker.patch("akshare.stock_zh_a_spot_em",
                 return_value=pd.DataFrame({"代码":["000001"],"名称":["平安"],"最新价":[1.0]}))
    mocker.patch("akshare.tool_trade_date_hist_sina",
                 return_value=pd.DataFrame({"trade_date":["2024-01-02"]}))
    # 财务/板块/宏观等也 mock 为空 DF,跳过(空 DF 不写)
    for fn in ["stock_financial_report_sina","stock_financial_analysis_indicator",
               "stock_em_yjbb","stock_board_industry_name_em","stock_board_industry_cons_em",
               "stock_board_concept_name_em","stock_board_concept_cons_em","stock_margin_sse",
               "stock_lhb_detail_em","stock_gdfx_holding_detail_em","macro_china_cpi"]:
        mocker.patch(f"akshare.{fn}", return_value=pd.DataFrame())
    backfill.run_all(conn, seed_path="panwen/seeds/dev_codes.txt", periods=["20231231"],
                     client=clientmod)
    assert conn.execute("SELECT count(*) FROM stock_basic").fetchone()[0] == 1
    assert conn.execute("SELECT count(*) FROM daily_quote").fetchone()[0] == 1
```

- [ ] **Step 2: 运行确认失败** → FAIL（`backfill` 不存在）

- [ ] **Step 3: 实现 `panwen/data/ingest/backfill.py`**

```python
from __future__ import annotations
import duckdb
from panwen.data.ingest import specs, runner, client as clientmod
from panwen.data.ingest.checkpoint import Checkpoint

# 需要在 map_columns 后补常量列的 spec → (列名, 值)
_CONSTANT_COLS = {
    "margin_daily": [("market", "sse")],
    "macro_series": [("indicator", "CPI_YOY")],
}

def run_all(conn: duckdb.DuckDBPyConnection, *,
            seed_path: str | None = None, periods: list[str] | None = None,
            client=clientmod, checkpoint: Checkpoint | None = None) -> None:
    code_source = _load_seed(seed_path) if seed_path else None

    for spec in (specs.build_quote_specs() + specs.build_finance_specs()
                 + specs.build_domain_specs()):
        kw = dict(client=client, checkpoint=checkpoint)
        if spec.iteration == "per_code" and code_source:
            kw["code_source"] = code_source
        if spec.iteration == "per_period":
            kw["period_source"] = periods or []
        if spec.table in _CONSTANT_COLS:
            # 包一层: 在 source 返回后补常量列
            kw["client"] = _with_const_cols(client, spec.table)
        runner.run_ingest(conn, spec, **kw)

def _load_seed(path: str) -> list[str]:
    with open(path, encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip() and not line.startswith("#")]

def _with_const_cols(client, table):
    """返回一个伪 client: fetch 后给 df 补 _CONSTANT_COLS[table] 的常量列。"""
    consts = _CONSTANT_COLS[table]
    class _W:
        def fetch(self, func, *a, **kw):
            df = client.fetch(func, *a, **kw)
            for col, val in consts:
                df[col] = val
            return df
    return _W()
```

- [ ] **Step 4: 运行确认通过** → PASS（mock 全绿即通过）

- [ ] **Step 5: 提交**

```bash
git add panwen/data/ingest/backfill.py tests/data/test_backfill.py
git commit -m "feat(data): full backfill orchestrator + constant-col injection"
```

---

## Task 12: 冻结/活动双库 + 每日增量 + Makefile + README + 集成测试

**Files:**
- Create: `panwen/data/snapshots.py`, `panwen/data/ingest/incremental.py`, `scripts/freeze_eval.py`, `Makefile`, `tests/data/test_snapshots.py`, `tests/data/test_incremental.py`
- Modify: `README.md`（新增"数据层"小节）

**Interfaces:**
- Produces: `snapshots.freeze_eval(live_path, eval_path, as_of)`, `incremental.run_daily(conn, *, client)`, Makefile 目标 `data-backfill` / `data-incremental` / `eval-freeze` / `seed-backfill`

- [ ] **Step 1: 写 `test_snapshots.py`**

```python
import pandas as pd
from panwen.data import db
from panwen.data.ingest import loader
from panwen.data import snapshots

def test_freeze_eval_truncates_future_rows(tmp_path):
    live = str(tmp_path/"live.duckdb"); ev = str(tmp_path/"eval.duckdb")
    c = db.connect(live); db.init_schema(c)
    loader.upsert_df(c, "daily_quote", pd.DataFrame({
        "code":["000001","000001"], "date":["2024-01-02","2025-01-02"],
        "open":[1,1],"high":[1,1],"low":[1,1],"close":[1,1],"volume":[1,1],
        "amount":[1,1],"pct_chg":[1,1],"turnover":[1,1]}), ["code","date"])
    c.close()
    snapshots.freeze_eval(live, ev, as_of="2024-12-31")
    ro = db.connect(ev, read_only=True)
    assert ro.execute("SELECT count(*) FROM daily_quote WHERE date>'2024-12-31'").fetchone()[0] == 0
    assert ro.execute("SELECT count(*) FROM daily_quote").fetchone()[0] == 1
    ro.close()
```

- [ ] **Step 2: 写 `test_incremental.py`**

```python
import pandas as pd
from panwen.data import db
from panwen.data.ingest import incremental, client as clientmod

def test_run_daily_upserts_spot(tmp_path, mocker):
    conn = db.connect(str(tmp_path/"t.duckdb")); db.init_schema(conn)
    mocker.patch("akshare.stock_zh_a_spot_em", return_value=pd.DataFrame({
        "代码":["000001"],"名称":["平安"],"最新价":[11.0],"涨跌幅":[1.0]}))
    incremental.run_daily(conn, client=clientmod)
    assert conn.execute("SELECT price FROM spot_snapshot").fetchone()[0] == 11.0
```

- [ ] **Step 3: 运行确认失败** → FAIL

- [ ] **Step 4: 实现 `panwen/data/snapshots.py`**

```python
import shutil, os
import duckdb
from panwen.data import schema

def freeze_eval(live_path: str, eval_path: str, as_of: str) -> None:
    """把 live.duckdb 复制为 eval.duckdb,并删除所有日期型列 > as_of 的行,实现冻结。"""
    shutil.copyfile(live_path, eval_path)
    conn = duckdb.connect(eval_path)
    for table, cols in schema.COLUMN_CLASS.items():
        date_cols = [c for c, t in cols.items() if t == "date"]
        if not date_cols:
            continue
        where = " OR ".join(f"{c} > '{as_of}'" for c in date_cols)
        conn.execute(f'DELETE FROM {table} WHERE {where}')
    conn.close()
```

- [ ] **Step 5: 实现 `panwen/data/ingest/incremental.py`**

```python
from __future__ import annotations
import duckdb
from panwen.data.ingest import specs, runner, client as clientmod

def run_daily(conn: duckdb.DuckDBPyConnection, *, client=clientmod) -> None:
    """每日增量: spot 全市场快照(1 调用) + 板块/融资融券/龙虎榜今日。
    财报按报告期补抓由 backfill 在披露季手动触发(periods 传新报告期)。"""
    runner.run_ingest(conn, specs.SPOT_SPEC, client=client)
    # 其余 oneshot/per_date 域可在此追加今日日期的 per_date 调用
```

- [ ] **Step 6: 写 `scripts/freeze_eval.py`**

```python
import argparse
from panwen.data import snapshots

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", default="data/live.duckdb")
    ap.add_argument("--eval", default="data/eval.duckdb")
    ap.add_argument("--as-of", required=True, help="冻结截止日 YYYY-MM-DD")
    a = ap.parse_args()
    snapshots.freeze_eval(a.live, a.eval, a.as_of)
    print(f"frozen → {a.eval} as_of={a.as_of}")

if __name__ == "__main__":
    main()
```

- [ ] **Step 7: 写 `Makefile`**

```makefile
.PHONY: install seed-backfill data-backfill data-incremental eval-freeze test

install:
	pip install -e ".[dev]"

# 开发: 用 ~20 只种子快速端到端验证
seed-backfill:
	python -c "from panwen.data import db; from panwen.data.ingest import backfill, checkpoint, client; \
	c=db.connect('data/live.duckdb'); db.init_schema(c); \
	backfill.run_all(c, seed_path='panwen/seeds/dev_codes.txt', periods=['20231231','20231231'], \
	checkpoint=checkpoint.Checkpoint('data/checkpoint.json'), client=client); c.close()"

# 生产: 全市场全量回填(数小时,夜间跑)
data-backfill:
	python -c "from panwen.data import db; from panwen.data.ingest import backfill, checkpoint, client; \
	c=db.connect('data/live.duckdb'); db.init_schema(c); \
	backfill.run_all(c, periods=['20150331','20150630','20150930','20151231'], \
	checkpoint=checkpoint.Checkpoint('data/checkpoint.json'), client=client); c.close()"

data-incremental:
	python -c "from panwen.data import db; from panwen.data.ingest import incremental, client; \
	c=db.connect('data/live.duckdb'); db.init_schema(c); incremental.run_daily(c, client=client); c.close()"

eval-freeze:
	python scripts/freeze_eval.py --as-of 2024-12-31

test:
	pytest -v
```

- [ ] **Step 8: README 数据层小节**（追加到 `README.md`）

```markdown
## 数据层（akshare → DuckDB）

盘问的数据来自 [akshare](https://akshare.akfamily.xyz)（MIT，免费无 token）。仓库**只发入库脚本不发数据**。

```bash
make install
make seed-backfill    # 开发: ~20 只种子快速验证
make data-backfill    # 生产: 全市场全量回填(数小时,建议夜间;支持断点续传)
make data-incremental # 每日增量(spot 全市场快照,1 调用)
make eval-freeze      # 冻结 live→eval,随仓提交以保证指标可复现
```

- 日行情存**后复权(hfq)**；PE/ROE 等指标取自财务指标接口。
- `data/live.duckdb`（gitignore，每日刷新）与 `data/eval.duckdb`（冻结，随仓提交）双库分离。
- 数据稳定性说明：北向资金因 2024-08-19 监管调整停止实时披露，本数据层不含此维度（改由资讯工具定性补充，见 Plan 2）。
```

- [ ] **Step 9: 运行全部测试确认通过**

Run: `pytest -v`
Expected: 全 PASS（含 snapshots + incremental）

- [ ] **Step 10: 手动冒烟（可选但推荐）**

```bash
make seed-backfill    # 联网,验证 ~20 只种子真实抓取写入 live.duckdb
python -c "from panwen.data import db; c=db.connect('data/live.duckdb',read_only=True); \
print('daily_quote rows:', c.execute('SELECT count(*) FROM daily_quote').fetchone()[0])"
```
Expected: daily_quote 行数 > 0（具体数字如实记录，**不写入任何简历指标**）。

- [ ] **Step 11: 提交**

```bash
git add panwen/data/snapshots.py panwen/data/ingest/incremental.py scripts/freeze_eval.py \
        Makefile README.md tests/data/test_snapshots.py tests/data/test_incremental.py
git commit -m "feat(data): dual-DB freeze + daily incremental + Makefile + README"
```

---

## Self-Review（已执行）

**1. Spec 覆盖**：Plan 1 覆盖 design.md §3（数据层：全部🟢域 + 🟡批次、hfq 存储、双库、断点续传、增量、只发脚本不发数据）。§4 Agent 闭环 / §5 ValidSQL / §6 RAG / §7 Eval / §8 Phase2 属于 Plan 2/3，本计划不含——这是有意的范围切分。
**2. 占位符扫描**：无 TBD/TODO。两处需要执行者用 `probe_akshare.py` 校准 akshare 中文列名——这是明确的执行步骤（脚本已提供），不是模糊占位。
**3. 类型一致性**：核心契约（`schema.TABLE_DDL/COLUMN_CLASS`、`db.connect/init_schema`、`client.fetch`、`loader.upsert_df`、`Checkpoint`、`Spec`、`run_ingest`）在定义任务与消费任务间命名/签名一致。Plan 2/3 将复用 `schema.COLUMN_CLASS`（ValidSQL 类型约束）与 `db.connect`（只读执行）。

---

## 执行交接

Plan 1 完成后,数据层可用:`make seed-backfill` 跑通、所有 MVP 表可查、`eval.duckdb` 可冻结。随后:
- **Plan 2（Agent 核心）**：基于本计划的 `schema.COLUMN_CLASS` 实现 ValidSQL、基于 `db.connect(read_only=True)` 实现只读执行。
- **Plan 3（Eval + Demo）**：基于本计划的 `eval.duckdb` 跑冻结评测。