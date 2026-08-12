import pandas as pd
from panwen.data import db
from panwen.data.ingest import loader
from panwen.data import snapshots

def test_freeze_eval_truncates_future_rows(tmp_path):
    live = str(tmp_path/"live.duckdb"); ev = str(tmp_path/"eval.duckdb")
    c = db.connect(live); db.init_schema(c)
    loader.upsert_df(c, "daily_quote", pd.DataFrame({
        "code":["000001","000001"], "date":["2024-01-02","2025-01-02"],
        "open":[1,1],"high":[1,1],"low":[1,1],"close":[1,1],"volume":[1,1],
        "amount":[1,1],"pct_chg":[1,1],"turnover":[1,1]}), ["code","date"])
    c.close()
    snapshots.freeze_eval(live, ev, as_of="2024-12-31")
    ro = db.connect(ev, read_only=True)
    assert ro.execute("SELECT count(*) FROM daily_quote WHERE date>'2024-12-31'").fetchone()[0] == 0
    assert ro.execute("SELECT count(*) FROM daily_quote").fetchone()[0] == 1
    ro.close()
