# panwen/data/ingest/runner.py
import duckdb
from panwen.data.ingest.specs import Spec, _KEY
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
        df = _apply_const(df, spec.const_cols, key=None)
        return loader.upsert_df(conn, spec.table, df, spec.conflict_cols)

    # 迭代型: 选出待处理 keys,断点续传
    if spec.iteration == "per_code":
        # 区分 None(未提供 -> 自动发现全部 A 股)与 [](显式空,如板块表为空时
        # _key_source 返回 []);后者必须保持空,否则会回退到股票代码当作板块名。
        keys = code_source if code_source is not None else _all_codes(conn)
    elif spec.iteration == "per_period":
        keys = period_source or []
    else:
        raise ValueError(f"unknown iteration: {spec.iteration}")

    todo = keys if checkpoint is None else checkpoint.resume_iter(spec.name, keys)
    for k in todo:
        try:
            df = client.fetch(spec.source, **spec.arg_builder(k))
            df = mapping.map_columns(df, spec.rename_map)
            df = _apply_const(df, spec.const_cols, key=k)
            total += loader.upsert_df(conn, spec.table, df, spec.conflict_cols)
            if checkpoint:
                checkpoint.mark(spec.name, k)
        except Exception as e:
            # 单 key 失败不阻断整体;记录后继续(断点续传下次重试)
            print(f"[warn] {spec.name} key={k} failed: {e}")
    return total


def _apply_const(df, const_cols: dict, key):
    """Task 11: 在 map_columns 之后注入声明式常量列(Spec.const_cols)。

    - 值为 _KEY sentinel 时, 写入当前 per_code 迭代键(oneshot 传 key=None 时不应出现 _KEY)。
    - 否则写入字面常量值。
    - 空 const_cols 为 no-op(向后兼容; 未声明 const_cols 的 spec 不受影响)。
    """
    for col, val in const_cols.items():
        df[col] = key if val is _KEY else val
    return df


def _all_codes(conn) -> list[str]:
    rows = conn.execute("SELECT code FROM stock_basic").fetchall()
    return [r[0] for r in rows] if rows else []
