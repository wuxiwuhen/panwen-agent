import pandas as pd
from panwen.data.ingest import mapping

def test_map_columns_renames_and_drops_unknown():
    df = pd.DataFrame({"日期": ["2024-01-02"], "股票代码": ["000001"], "收盘": [10.0], "垃圾列": [1]})
    out = mapping.map_columns(df, {"日期": "date", "股票代码": "code", "收盘": "close"})
    assert list(out.columns) == ["date", "code", "close"]

def test_to_sina_code():
    assert mapping.to_sina_code("600000") == "sh600000"
    assert mapping.to_sina_code("000001") == "sz000001"
    assert mapping.to_sina_code("300001") == "sz300001"
    assert mapping.to_sina_code("688001") == "sh688001"
