"""Task 6 deploy-artifact guard: root app.py + requirements.txt + README Demo UI.

These are static artifact checks (no Gradio launch, no network). They pin the
deploy surface: the root entry must import without launching; the Space
requirements must list runtime deps and MUST NOT list akshare (Approach-A
Space-lightness guarantee); the README must document the Demo UI section.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # tests/ui → repo root


def test_requirements_has_gradio_not_akshare():
    text = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert "gradio" in text
    assert "akshare" not in text  # 方案 A 硬约束


def test_requirements_has_runtime_deps():
    text = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    for dep in ["duckdb", "pandas", "sqlglot", "openai", "pyyaml", "sentence-transformers"]:
        assert dep in text


def test_root_app_py_imports_build_app():
    # 根 app.py 在 __main__ guard 内 launch；import 不应触发 launch
    import importlib.util
    spec = importlib.util.spec_from_file_location("root_app", ROOT / "app.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # 不应抛、不应调 launch（__main__ guard）
    assert hasattr(mod, "build_app")


def test_readme_has_demo_ui_section():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "## Demo UI" in text
