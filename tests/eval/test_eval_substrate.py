"""Task 0: 评测基板 —— load_codes 契约 + sina spec 集校验。"""
from pathlib import Path
from panwen.data.ingest import specs
from panwen.eval.seeds import load_codes

ROOT = Path(__file__).resolve().parents[2]
SEED = ROOT / "panwen" / "seeds" / "eval_codes.txt"


def test_load_codes_parses_seed():
    """eval_codes.txt 解析为 6 位代码列表(>=30 只，含茅台/平安)。"""
    codes = load_codes(str(SEED))
    assert len(codes) >= 30, f"期望 >=30 只，实际 {len(codes)}"
    assert all(len(c) == 6 and c.isdigit() for c in codes)
    assert "600519" in codes and "000001" in codes


def test_load_codes_ignores_comments_and_blanks(tmp_path):
    f = tmp_path / "s.txt"
    f.write_text("# 注释\n600519\n\n  \n000001\n", encoding="utf-8")
    assert load_codes(str(f)) == ["600519", "000001"]


def test_financial_specs_used_are_sina_only():
    """Task 0 只跑 sina 4 spec，绝不带 eastmoney PERFORMANCE_SPEC。"""
    sina = [specs.INCOME_SPEC, specs.BALANCE_SPEC, specs.CASHFLOW_SPEC, specs.FIN_INDICATOR_SPEC]
    names = {s.name for s in sina}
    assert {"income", "balance", "cashflow", "fin_indicator"} <= names
    assert "performance" not in names  # eastmoney yjbb —— 禁入 Task 0
