import shutil
import duckdb
from panwen.data import schema


def freeze_eval(live_path: str, eval_path: str, as_of: str) -> None:
    """把 live.duckdb 复制为 eval.duckdb,并删除所有日期型列 > as_of 的行,实现冻结。

    duckdb 不会自动创建父目录,调用方需保证 eval_path 的父目录存在
    (Makefile 的 eval-freeze 目标已 `mkdir -p data`)。
    """
    shutil.copyfile(live_path, eval_path)
    conn = duckdb.connect(eval_path)
    for table, cols in schema.COLUMN_CLASS.items():
        date_cols = [c for c, t in cols.items() if t == "date"]
        if not date_cols:
            continue
        where = " OR ".join(f"{c} > '{as_of}'" for c in date_cols)
        conn.execute(f"DELETE FROM {table} WHERE {where}")
    conn.close()
