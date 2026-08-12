import pandas as pd

def map_columns(df: pd.DataFrame, rename_map: dict[str, str]) -> pd.DataFrame:
    """按 rename_map 重命名;未在 map 中的列丢弃。"""
    keep = {k: v for k, v in rename_map.items() if k in df.columns}
    return df.rename(columns=keep)[[keep[k] for k in df.columns if k in keep]]

def to_sina_code(code: str) -> str:
    """6 位代码 → 新浪/东财财报接口要的 sh/sz 前缀格式。"""
    c = code.zfill(6)
    if c.startswith(("60", "68", "9")):
        return "sh" + c
    return "sz" + c
