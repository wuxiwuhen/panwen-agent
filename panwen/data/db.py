import duckdb
from panwen.data import schema

def connect(path: str, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    return duckdb.connect(path, read_only=read_only)

def init_schema(conn: duckdb.DuckDBPyConnection) -> None:
    for ddl in schema.TABLE_DDL.values():
        conn.execute(ddl)
