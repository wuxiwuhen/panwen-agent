"""评测种子加载(Task 0)。读种子文件 → 6 位代码列表(去注释/空行)。"""
from __future__ import annotations
from pathlib import Path


def load_codes(path: str) -> list[str]:
    out = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            out.append(line)
    return out
