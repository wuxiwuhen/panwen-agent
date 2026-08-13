"""run_query —— 9 步确定性管线 + ⑧ 有界自纠错(spec §5)。

每阶段受 config 开关控制；失败不中断，记 trace。
"""
from __future__ import annotations
from pathlib import Path

from panwen.agent.backend import AgentBackend
from panwen.agent.config import AgentConfig
from panwen.agent.safe_sql import run_safe_sql
from panwen.agent.types import (AgentResult, Message, TraceStep, NormQuery, Explanation)
from panwen.agent.normalize import normalize
from panwen.agent.clarify import dispatch
from panwen.agent.explainer import explain
from panwen.validsql.validator import build_schema_view
from panwen.rag.schema_retriever import SchemaRetriever
from panwen.rag.fewshot_store import FewshotStore

# Directive 1: parents[1] = panwen/(prompts/ 在此)；brief 的 parents[2] 指向 repo 根 → FileNotFoundError。
_PLAN_GEN_PROMPT = (Path(__file__).resolve().parents[1] / "prompts" / "v1" / "plan_generate.txt").read_text(encoding="utf-8")


def _sql_tool(use_plan: bool) -> dict:
    """emit_sql 工具定义；use_plan 控制是否含 plan 字段。"""
    props = {"sql": {"type": "string"}}
    if use_plan:
        props["plan"] = {"type": "string"}
    return {
        "name": "emit_sql",
        "description": "输出一条只读 SQL 查询(覆盖 plan_generate 指令)",
        "input_schema": {"type": "object", "properties": props, "required": ["sql"]},
    }


def _generate(norm: NormQuery, schema_subset, fewshot, backend: AgentBackend,
              feedback: str | None, prev_sql: str | None,
              use_plan: bool = True) -> tuple[str | None, str | None]:
    """⑤ 一次 LLM 调用出 (sql, plan)。feedback 非空 = 自纠错回灌错误。

    强制 tool_use(emit_sql)；无 tool_use → (None, None)。
    Directive 3: 弃用 brief 里未使用的 conn/config 形参；use_plan 从 config 传入。
    """
    schema_text = "\n".join(f"- {e.table}{'.'+e.column if e.column else ''}: {e.doc}" for e in schema_subset)
    fewshot_text = "\n".join(f"Q: {e.question}\nSQL: {e.sql}" for e in fewshot) if fewshot else "(无)"
    user = (f"问题: {norm.question}\n日期区间: {norm.date_range}\ntop_k: {norm.top_k} 排序: {norm.order}\n"
            f"实体: {norm.entities}\n\n相关 schema:\n{schema_text}\n\nfew-shot:\n{fewshot_text}")
    if feedback:
        user += f"\n\n上一条 SQL 失败，错误反馈:\n{feedback}\n上次SQL:\n{prev_sql}\n请修正。"
    resp = backend.chat(
        [Message(role="system", content=_PLAN_GEN_PROMPT), Message(role="user", content=user)],
        tools=[_sql_tool(use_plan)], tool_choice={"type": "tool", "name": "emit_sql"},
        temperature=0.0)
    if resp.tool_calls:
        inp = resp.tool_calls[0]["input"]
        return inp.get("sql"), inp.get("plan")
    return None, None


def run_query(question: str, conn, backend: AgentBackend, rag: SchemaRetriever,
              fewshot: FewshotStore, config: AgentConfig) -> AgentResult:
    trace: list[TraceStep] = []

    # ① normalize(含意图/范围门)
    try:
        norm = normalize(question, backend)
        trace.append(TraceStep("normalize", True, f"intent={norm.intent}"))
    except Exception as e:
        return _failed(question, backend, trace, f"normalize 异常: {e}", config)

    # ② dispatch(三分支早退)
    early = dispatch(norm, backend)
    if early is not None:
        early.trace = trace
        return early

    # ③④ rag 上下文(常开 schema；fewshot 受开关)
    schema_subset = rag.retrieve(question)[:config.schema_topk] if hasattr(rag, "retrieve") else []
    shots = fewshot.retrieve(question)[:config.fewshot_k] if config.use_fewshot else []
    trace.append(TraceStep("rag", True, f"schema={len(schema_subset)} fewshot={len(shots)}"))

    sv = build_schema_view()
    feedback: str | None = None
    prev_sql: str | None = None
    last_sql, last_rows, last_root = None, None, None
    budget = config.selfcorrect_budget + 1 if config.use_selfcorrect else 1

    for attempt in range(budget):
        # ⑤ generate
        sql, _plan = _generate(norm, schema_subset, shots, backend, feedback, prev_sql,
                                use_plan=config.use_plan)
        trace.append(TraceStep("generate", sql is not None, f"attempt={attempt} sql={'有' if sql else '无'}"))
        if not sql:
            break
        prev_sql = sql
        last_sql = sql

        # ⑥⑦ 合并为一次 run_safe_sql(守卫+执行原语)。
        # run_safe_sql 内部按 config.use_validsql 决定是否跑 ValidSQL
        # (False→issues=[]→无 blocking→直接执行)，与旧 ⑥ 分支语义一致。
        sr = run_safe_sql(sql, conn, config, sv)
        if sr.blocking:
            last_root = sr.blocking[0].rootCause
            feedback = "; ".join(f"{i.code}:{i.message}" for i in sr.blocking)
            trace.append(TraceStep("validate", False, feedback[:80], last_root))
            continue
        advisory = " +ROOT_UNPARAM(advisory)" if sr.advisory else ""
        trace.append(TraceStep("validate", True,
                               ("skipped(use_validsql=False)" if not config.use_validsql
                                else f"checks 1-5 pass{advisory}")))
        last_rows, last_root = sr.rows, sr.rootCause
        if sr.ok:
            trace.append(TraceStep("execute", True, f"{len(sr.rows)} rows"))
            break
        feedback = sr.rootCause
        trace.append(TraceStep("execute", False, sr.rootCause[:80], sr.rootCause))

    # ⑨ explain
    answered = last_rows is not None and last_root is None
    status = "answered" if answered else "failed"
    explanation = explain(question, last_sql, last_rows,
                          low_confidence=(not answered), backend=backend)
    trace.append(TraceStep("explain", True, f"conf={explanation.confidence}"))
    return AgentResult(status=status, sql=last_sql, rows=last_rows, reply=None,
                       explanation=explanation, trace=trace)


def _failed(question, backend, trace, detail, config) -> AgentResult:
    return AgentResult(status="failed", sql=None, rows=None, reply=None,
                       explanation=Explanation([], 0.0, detail), trace=trace)
