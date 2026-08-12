import pandas as pd
from panwen.data import db, schema
from panwen.data.ingest import loader

def test_upsert_inserts_then_updates(tmp_path):
    conn = db.connect(str(tmp_path / "t.duckdb")); db.init_schema(conn)
    df1 = pd.DataFrame({"code": ["000001"], "name": ["平安银行"], "listing_date": ["1991-04-03"],
                        "board": ["主板"], "industry": ["银行"], "is_st": ["否"], "delist_date": [None]})
    n = loader.upsert_df(conn, "stock_basic", df1, ["code"])
    assert n == 1
    assert conn.execute("SELECT name FROM stock_basic").fetchone()[0] == "平安银行"
    # 再写一条同 code 不同 name → 应 update 而非报错/重复
    df2 = df1.assign(name=["平安银行X"])
    loader.upsert_df(conn, "stock_basic", df2, ["code"])
    assert conn.execute("SELECT count(*) FROM stock_basic").fetchone()[0] == 1
    assert conn.execute("SELECT name FROM stock_basic").fetchone()[0] == "平安银行X"
    conn.close()
