"""盘问 PanWen · Demo UI 入口（HF Spaces / 本地）。

Space 运行此文件；本地：pip install gradio 后 python app.py。
默认连冻结 eval.duckdb；本地连实时库：export PANWEN_DB=data/live.duckdb。
"""
import os
from panwen.ui.app import build_app

if __name__ == "__main__":
    demo = build_app()
    demo.launch(server_name="0.0.0.0", server_port=int(os.environ.get("PORT", 7860)))
