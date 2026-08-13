# panwen/agent/safe_sql.py
from __future__ import annotations
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from dataclasses import dataclass, field
from panwen.agent.config import AgentConfig
from panwen.validsql.validator import validate_sql, build_schema_view, SchemaView, ValidationIssue

@dataclass
class SqlResult:
    ok: bool
    rows: list[dict] | None
    sql: str
    blocking: list[ValidationIssue] = field(default_factory=list)
    advisory: list[ValidationIssue] = field(default_factory=list)
    rootCause: str | None = None
    elapsed_ms: int | None = None

def _execute(sql, conn, timeout_s):
    def _run():
        cur = conn.execute(sql)
        cols = [d[0] for d in cur.description] if cur.description else []
        return [dict(zip(cols, r)) for r in cur.fetchall()]
    try:
        with ThreadPoolExecutor(max_workers=1) as ex:
            return ex.submit(_run).result(timeout=timeout_s), None
    except FuturesTimeout:
        return None, "ROOT_TIMEOUT"
    except Exception as e:
        return None, f"ROOT_EXEC:{type(e).__name__}:{e}"

_BLOCKING = {"ROOT_PARSE", "ROOT_WRITE_OP", "ROOT_UNKNOWN_TABLE",
             "ROOT_UNKNOWN_COL", "ROOT_TYPE_AGG", "ROOT_CARTESIAN"}

def run_safe_sql(sql, conn, config: AgentConfig, schema_view: SchemaView | None = None) -> SqlResult:
    sv = schema_view or build_schema_view()
    issues = validate_sql(sql, sv, conn=conn) if config.use_validsql else []
    blocking = [i for i in issues if i.code in _BLOCKING]
    advisory = [i for i in issues if i.code == "ROOT_UNPARAM"]
    if blocking:
        return SqlResult(False, None, sql, blocking=blocking, advisory=advisory,
                         rootCause=blocking[0].rootCause)
    t0 = time.perf_counter()
    rows, root = _execute(sql, conn, config.exec_timeout_s)
    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    if root is None:
        return SqlResult(True, rows, sql, advisory=advisory, elapsed_ms=elapsed_ms)
    return SqlResult(False, None, sql, advisory=advisory, rootCause=root, elapsed_ms=elapsed_ms)
