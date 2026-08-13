# panwen/agent/tools/schemas.py
"""喂给 LLM 的 tool 定义（Task 8 agent-loop 消费）。

name / description / input_schema 三元组，遵循 Anthropic tool-use schema。
"""
from __future__ import annotations

TOOLS_SCHEMA: list[dict] = [
    {
        "name": "get_stock_profile",
        "description": "查股票基本信息(名称/板块/行业/ST)",
        "input_schema": {
            "type": "object",
            "properties": {"code": {"type": "string"}},
            "required": ["code"],
        },
    },
    {
        "name": "get_financials",
        "description": "查最新财务(营收/净利/资产/现金流/ROE 等)",
        "input_schema": {
            "type": "object",
            "properties": {
                "code": {"type": "string"},
                "report_date": {"type": "string"},
            },
            "required": ["code"],
        },
    },
    {
        "name": "get_recent_quotes",
        "description": "查近 N 日行情",
        "input_schema": {
            "type": "object",
            "properties": {
                "code": {"type": "string"},
                "days": {"type": "integer"},
            },
            "required": ["code"],
        },
    },
    {
        "name": "get_performance",
        "description": "查业绩快报(营收/净利同比)",
        "input_schema": {
            "type": "object",
            "properties": {"code": {"type": "string"}},
            "required": ["code"],
        },
    },
    {
        "name": "query_database",
        "description": "任意自然语言子问题 → SQL 查询(通用兜底)",
        "input_schema": {
            "type": "object",
            "properties": {"question": {"type": "string"}},
            "required": ["question"],
        },
    },
]
