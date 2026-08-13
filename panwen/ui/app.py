"""Gradio Blocks 应用：布局 + 事件接线。MVP trace 完成后回放（零改动 loop.py）。
gradio 在 build_app 内 lazy-import，使 handle_query 可在无 gradio 环境下测试。
"""
from __future__ import annotations

import pandas as pd

from panwen.ui import config_bridge, examples, render, runtime

ABOUT_MD = """## 关于盘问 PanWen

**9 步确定性管线**：① normalize（规则+LLM，含意图/范围门）→ ② dispatch（确定性三分支：out_of_scope / needs_clarify / sql_answerable）→ ③④ 双路 RAG 上下文 → ⑤ plan+generate → ⑥ ValidSQL 校验 → ⑦ 只读执行（超时保护）→ ⑧ 有界自纠错（N=3）→ ⑨ 解释。

**ValidSQL（sqlglot AST 6 项）**：只写白名单 / 表列存在 / 类型约束 / 防笛卡尔 / 参数化 / 执行超时。

**诚实口径**
- 本演示跑在**冻结 `eval.duckdb`**（as-of 2026-06-30 快照）；本地可用 `PANWEN_DB=data/live.duckdb` 连实时库。
- ValidSQL check 5（参数化）在 MVP 为**顾问式**（记入 trace 但不阻断）。
- 仓库**不预填准确率数字**；指标须由 `make eval` 实测。
- 跨域基准（如 Hermes、GRPO）为他人成果，仅作对比，不冒认为本项目指标。
"""


def handle_query(question, use_fewshot, use_validsql, use_selfcorrect, schema_topk,
                 _runtime=None):
    """查询 handler：toggle→config→runtime.ask→render。
    返回 (sql, table(DataFrame), explanation, trace, reply)，对应 build_app 的 outputs 顺序。
    _runtime 注入用于测试。
    """
    if not question or not question.strip():
        return "", pd.DataFrame(), "", [], "请输入问句。"
    cfg = config_bridge.to_config(use_fewshot, use_validsql, use_selfcorrect, schema_topk)
    try:
        res = runtime.ask(question.strip(), cfg, runtime=_runtime)
    except Exception as e:  # 后端初始化失败（无 API key / 模型加载失败）兜底，不崩 UI
        return "", pd.DataFrame(), "", [], f"⚠️ 后端错误：{e}"
    headers, rows = render.result_table(res)
    table = pd.DataFrame(rows, columns=headers) if headers else pd.DataFrame()
    return (render.sql_block(res), table, render.explanation_md(res),
            render.trace_rows(res), render.status_reply(res))


def build_app():
    """构造 Gradio Blocks。gradio 在此 lazy-import。"""
    import gradio as gr

    with gr.Blocks(title="盘问 PanWen · A股自然语言查询 Agent") as demo:
        gr.Markdown("# 盘问 PanWen · A股自然语言查询 Agent")
        with gr.Tabs():
            with gr.Tab("问答"):
                with gr.Row():
                    with gr.Column(scale=3):
                        question = gr.Textbox(label="问句",
                                              placeholder="例：贵州茅台最近一年的净利润是多少",
                                              lines=2)
                        ask_btn = gr.Button("查询 Ask", variant="primary")
                        gr.Examples(examples=examples.example_questions(), inputs=question)
                    with gr.Column(scale=2):
                        use_fewshot = gr.Checkbox(value=True, label="Few-shot RAG")
                        use_validsql = gr.Checkbox(value=True, label="ValidSQL 校验")
                        use_selfcorrect = gr.Checkbox(value=True, label="有界自纠错")
                        schema_topk = gr.Slider(minimum=1, maximum=10, value=5, step=1,
                                                label="schema top_k")
                gr.Markdown("### 生成的 SQL")
                sql_out = gr.Markdown()
                gr.Markdown("### 结果表")
                table_out = gr.DataFrame(interactive=False)
                gr.Markdown("### 解释")
                expl_out = gr.Markdown()
                gr.Markdown("### 推理 trace")
                trace_out = gr.DataFrame(headers=["stage", "ok", "detail", "rootCause"],
                                         interactive=False)
                reply_out = gr.Markdown()
            with gr.Tab("关于 / 架构"):
                gr.Markdown(ABOUT_MD)

        outputs = [sql_out, table_out, expl_out, trace_out, reply_out]
        inputs = [question, use_fewshot, use_validsql, use_selfcorrect, schema_topk]
        ask_btn.click(fn=handle_query, inputs=inputs, outputs=outputs)
        question.submit(fn=handle_query, inputs=inputs, outputs=outputs)
    return demo
