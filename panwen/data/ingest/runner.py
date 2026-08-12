# panwen/data/ingest/runner.py
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
    else:
        raise ValueError(f"unknown iteration: {spec.iteration}")

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
