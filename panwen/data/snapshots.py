import shutil
import duckdb
from panwen.data import schema


def freeze_eval(live_path: str, eval_path: str, as_of: str) -> None:
    """把 live.duckdb 复制为 eval.duckdb,并删除所有日期型列 > as_of 的行,实现冻结。

    duckdb 不会自动创建父目录,调用方需保证 eval_path 的父目录存在
    (Makefile 的 eval-freeze 目标已 `mkdir -p data`)。
    """
    shutil.copyfile(live_path, eval_path)
    # Fix 3: 用 with 上下文保证 conn.close() 始终执行。原代码末尾裸 conn.close(),
    # 若任一 DELETE 抛错则连接泄漏、eval.duckdb 半截截断(部分表已删部分未删)-> 冻结
    # 不可复现。with 语义下即使中途异常也会关闭连接。
    with duckdb.connect(eval_path) as conn:
        for table, cols in schema.COLUMN_CLASS.items():
            date_cols = [c for c, t in cols.items() if t == "date"]
            if not date_cols:
                continue
            where = " OR ".join(f"{c} > '{as_of}'" for c in date_cols)
            conn.execute(f"DELETE FROM {table} WHERE {where}")
