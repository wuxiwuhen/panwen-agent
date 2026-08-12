import pandas as pd
from panwen.data import db
from panwen.data.ingest import incremental, client as clientmod

def test_run_daily_upserts_spot(tmp_path, mocker):
    conn = db.connect(str(tmp_path/"t.duckdb")); db.init_schema(conn)
    mocker.patch("akshare.stock_zh_a_spot_em", return_value=pd.DataFrame({
        "代码":["000001"],"名称":["平安"],"最新价":[11.0],"涨跌幅":[1.0]}))
    incremental.run_daily(conn, client=clientmod)
    assert conn.execute("SELECT price FROM spot_snapshot").fetchone()[0] == 11.0
