# panwen/data/ingest/backfill.py
"""全量回填编排(Task 11)。

按 quote + finance + domain 的顺序遍历所有 canonical 表的 Spec,委托 run_ingest 执行。
常量列注入(margin.market / macro.indicator / fin_indicator.code /
industry_board_daily.board_name)由 Spec.const_cols 声明、在 run_ingest._apply_const 内
完成,本模块不再使用 wrapper-client(原设计无法获取 per_code 迭代键)。

板块键路由: per_code 板块 spec(INDUSTRY_CONST/INDUSTRY_BOARD_DAILY/CONCEPT_CONST)通过
Spec.key_domain 声明其迭代键来源,本模块 _key_source 据此从板块表读取板块名(而非股票代码)。
build_domain_specs() 已保证 oneshot 板块-LIST spec 排在依赖它的 per_code 板块 spec 之前。
"""
from __future__ import annotations
import duckdb
from panwen.data.ingest import specs, runner, client as clientmod
from panwen.data.ingest.checkpoint import Checkpoint


def run_all(conn: duckdb.DuckDBPyConnection, *, seed_path: str | None = None,
            periods: list[str] | None = None, client=clientmod,
            checkpoint: Checkpoint | None = None) -> None:
    """Full backfill over all domain specs.

    Constant-column injection (margin.market, macro.indicator, fin_indicator.code,
    industry_board_daily.board_name) is handled declaratively via Spec.const_cols
    inside run_ingest, NOT here.

    Known limitations (re-probe/extend on open network before production backfill):
    - stock_margin_sse caps at ~2000 rows/call (~8 most-recent years); full pre-2018
      margin history requires yearly-windowed fetching (post-MVP enhancement).
    - N eastmoney rename_maps are UNVERIFIED in proxied envs (board/concept/lhb/holders/
      financial endpoints): see `# UNVERIFIED` annotations in specs.py.
    - INCOME/BALANCE/CASHFLOW/PERFORMANCE rename_maps 仍未校验(sina/em 上游 ProxyError)。
    """
    code_source = _load_seed(seed_path) if seed_path else None
    for spec in (specs.build_quote_specs() + specs.build_finance_specs()
                 + specs.build_domain_specs()):
        kw = dict(client=client, checkpoint=checkpoint)
        if spec.iteration == "per_code":
            kw["code_source"] = _key_source(conn, spec, code_source)
        elif spec.iteration == "per_period":
            kw["period_source"] = periods or []
        runner.run_ingest(conn, spec, **kw)


def _key_source(conn, spec, codes):
    """Pick the per_code iteration keys by spec.key_domain.

    "code"           -> 股票代码(codes 来自 seed; 为 None 时 run_ingest 回退 _all_codes)
    "industry_board" -> industry_board.name(板块名)
    "concept_board"  -> concept_board.name(板块名)
    """
    if spec.key_domain == "industry_board":
        return [r[0] for r in conn.execute("SELECT name FROM industry_board").fetchall()]
    if spec.key_domain == "concept_board":
        return [r[0] for r in conn.execute("SELECT name FROM concept_board").fetchall()]
    return codes  # "code": None -> run_ingest falls back to _all_codes(conn)


def _load_seed(path: str) -> list[str]:
    with open(path, encoding="utf-8") as f:
        return [line.strip() for line in f
                if line.strip() and not line.startswith("#")]
