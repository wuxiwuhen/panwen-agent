import pandas as pd
from panwen.data import db
from panwen.data.ingest import specs, runner, client as clientmod

def _conn(tmp_path):
    c = db.connect(str(tmp_path/"t.duckdb")); db.init_schema(c); return c

def test_finance_specs_present():
    names = {s.table for s in specs.build_finance_specs()}
    assert {"income_statement","balance_sheet","cashflow_statement",
            "financial_indicator","performance_express"} <= names

def test_financial_indicator_runs(tmp_path, mocker):
    conn = _conn(tmp_path)
    mocker.patch("akshare.stock_financial_analysis_indicator", return_value=pd.DataFrame({
        "日期":["2023-12-31"],"股票代码":["000001"],"净资产收益率(%)":[12.0],
        "总资产报酬率(%)":[8.0],"销售毛利率(%)":[40.0],"销售净利率(%)":[20.0],
        "资产负债率(%)":[60.0],"市盈率":[8.0],"市净率":[1.0]}))
    runner.run_ingest(conn, specs.FIN_INDICATOR_SPEC, client=clientmod, code_source=["000001"])
    assert conn.execute("SELECT roe FROM financial_indicator").fetchone()[0] == 12.0
