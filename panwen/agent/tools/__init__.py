"""盘问 Tier-2 工具层。

- types: Source / ToolResult / TableResult 源契约
- narrow: 4 个窄 tool（固定 SQL recipe，零幻觉）
- query_database: 通用自然语言兜底（包装 run_query 管线）
- schemas: 喂给 LLM 的 tool JSON 定义（Task 8 消费）
"""
