"""后端装配 + 懒加载单例。复用 scripts/run_eval.py 的构造法。
启动时构造一次（bge ~1.3GB 在首次提问时加载），复用到所有请求。
"""
from __future__ import annotations
import os
from dataclasses import dataclass

from panwen.agent.backend import AgentBackend, make_backend
from panwen.agent.config import AgentConfig
from panwen.agent.agent_loop import run_agent, AgentRun
from panwen.agent.loop import run_query
from panwen.agent.session import SessionStore
from panwen.agent.types import AgentResult
from panwen.data import db
from panwen.rag.embed import BgeEmbedder, Embedder
from panwen.rag.fewshot_store import FewshotStore
from panwen.rag.schema_retriever import SchemaRetriever

DATASET = "panwen/eval/dataset/questions.yaml"
DEFAULT_DB = "data/eval.duckdb"


@dataclass
class Runtime:
    conn: object               # duckdb 只读连接
    backend: AgentBackend
    rag: SchemaRetriever
    fewshot: FewshotStore


def build_runtime(db_path: str | None = None, provider: str = "deepseek",
                  embedder: Embedder | None = None,
                  cache_dir: str = "data/rag_cache") -> Runtime:
    """构造 Runtime。embedder 可注入 FakeEmbedder 跳过 bge 下载（测试用）。"""
    cfg = AgentConfig()
    emb = embedder if embedder is not None else BgeEmbedder()
    rag = SchemaRetriever(embedder=emb, topk=cfg.schema_topk, cache_dir=cache_dir)
    fewshot = FewshotStore.from_dataset(DATASET, emb, k=cfg.fewshot_k)
    backend = make_backend(provider)
    conn = db.connect(db_path or os.environ.get("PANWEN_DB", DEFAULT_DB), read_only=True)
    return Runtime(conn=conn, backend=backend, rag=rag, fewshot=fewshot)


_RUNTIME: Runtime | None = None

# 多轮会话存储（模块级单例）。run_agent 在多轮间累积上下文；
# reset_runtime 会一并清空，保证测试隔离。
_STORE: SessionStore = SessionStore()


def get_runtime(db_path: str | None = None, provider: str = "deepseek",
                embedder: Embedder | None = None) -> Runtime:
    """懒加载单例：首次调用构造，之后复用（忽略后续 embedder 参数）。"""
    global _RUNTIME
    if _RUNTIME is None:
        _RUNTIME = build_runtime(db_path=db_path, provider=provider, embedder=embedder)
    return _RUNTIME


def reset_runtime() -> None:
    """测试用：清空 Runtime 单例与会话存储。"""
    global _RUNTIME, _STORE
    _RUNTIME = None
    _STORE = SessionStore()


def ask(question: str, config: AgentConfig, runtime: Runtime | None = None) -> AgentResult:
    """run_query 单查入口（toggle 用）。runtime 为 None 时取懒单例。"""
    rt = runtime if runtime is not None else get_runtime()
    return run_query(question, rt.conn, rt.backend, rt.rag, rt.fewshot, config)


def ask_agent(question: str, session_id: str, config: AgentConfig,
              runtime: Runtime | None = None) -> AgentRun:
    """run_agent 多轮入口：透传 session_id + 模块级 _STORE 维系多轮上下文。
    runtime 为 None 时取懒单例（首次触发 bge 加载）。
    """
    rt = runtime if runtime is not None else get_runtime()
    return run_agent(question, session_id, rt.conn, rt.backend, rt.rag, rt.fewshot,
                     config, _STORE)
