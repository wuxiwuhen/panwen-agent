import sys


def test_ui_import_chain_does_not_load_akshare():
    sys.modules.pop("akshare", None)
    import panwen.ui.runtime   # 查询路径核心
    import panwen.ui.app       # handler + 布局入口（gradio 在 build_app 内 lazy-import）
    assert "akshare" not in sys.modules, "UI import 链不得加载 akshare（Space 轻量硬约束）"
