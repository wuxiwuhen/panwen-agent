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
    """从 DuckDB EXPLAIN 输出里粗估行数(MVP：扫文本找 ~N rows)。

    DuckDB 在 explain_value 里以 ``~222,517 rows`` 形式输出(带千分位逗号、
    小写 rows、~ 前缀)。正则捕获 ``[\\d,]+`` 后剥掉逗号再 int。
    多个算子各自输出一行 ``~N rows``，取**最大值** —— 笛卡尔风险查询会
    在某个算子上膨胀(如根 join 输出 222,517)，取 max 才能捕捉到。
    """
    import re
    text = "\n".join(str(r) for r in plan_rows)
    matches = re.findall(r"~([\d,]+)\s*rows", text, re.IGNORECASE)
    if not matches:
        return None
    return max(int(m.replace(",", "")) for m in matches)
