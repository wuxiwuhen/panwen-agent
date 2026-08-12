import pandas as pd
from panwen.data import db
from panwen.data.ingest import specs, runner, checkpoint, client as clientmod

def _conn(tmp_path):
    c = db.connect(str(tmp_path/"t.duckdb")); db.init_schema(c); return c

def test_stock_basic_spec_shape():
    s = specs.STOCK_BASIC_SPEC
    assert s.table == "stock_basic" and s.iteration == "oneshot"

def test_daily_quote_spec_uses_hfq():
    # 确认 arg_builder 里有 adjust=hfq
    args = specs.DAILY_QUOTE_SPEC.arg_builder("000001")
    assert args.get("adjust") == "hfq"

def test_quote_specs_run_on_seed(tmp_path, mocker):
    conn = _conn(tmp_path)
    # 先灌 stock_basic(给 _all_codes 用)
    mocker.patch("akshare.stock_info_a_code_name",
                 return_value=pd.DataFrame({"code": ["000001","600519"], "name": ["平安","茅台"]}))
    runner.run_ingest(conn, specs.STOCK_BASIC_SPEC, client=clientmod)
    # mock 行情
    mocker.patch("akshare.stock_zh_a_hist", return_value=pd.DataFrame({
        "日期":["2024-01-02"],"股票代码":["000001"],"开盘":[10.0],"收盘":[10.0],"最高":[10.0],
        "最低":[10.0],"成交量":[100],"成交额":[1000.0],"涨跌幅":[1.0],"换手率":[1.0]}))
    runner.run_ingest(conn, specs.DAILY_QUOTE_SPEC, client=clientmod,
                      code_source=["000001"])
    assert conn.execute("SELECT count(*) FROM daily_quote").fetchone()[0] == 1
