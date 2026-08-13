# panwen/agent/tools/types.py
"""Tier-2 工具层源契约（spec §9）。dataclass，无业务逻辑。"""
from __future__ import annotations
from dataclasses import dataclass


@dataclass
class Source:
    kind: str                 # "duckdb" | "web"(P2) | "rss"(P2)
    table: str | None = None
    sql: str | None = None
    as_of: str | None = None
    url: str | None = None


@dataclass
class ToolResult:
    ok: bool
    data: list[dict] | str
    source: Source
    note: str | None = None


@dataclass
class TableResult:
    title: str
    rows: list[dict] | str
    source: Source
