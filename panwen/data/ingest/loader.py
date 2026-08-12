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
