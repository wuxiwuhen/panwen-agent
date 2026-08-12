import pandas as pd
from panwen.data import db
from panwen.data.ingest.specs import Spec
from panwen.data.ingest import runner, checkpoint

def _conn(tmp_path):
    c = db.connect(str(tmp_path / "t.duckdb")); db.init_schema(c); return c

class FakeClient:
    """测试用 client: 暴露 .fetch,直接转发给 source 函数(不经节流/重试)。"""
    def fetch(self, func, **kw):
        return func(**kw)

def test_run_ingest_oneshot(tmp_path, mocker):
    conn = _conn(tmp_path)
    fake_src = mocker.Mock(return_value=pd.DataFrame({
        "代码": ["000001"], "名称": ["平安"], "最新价": [10.0], "涨跌幅": [1.0]}))
    spec = Spec(name="spot", table="spot_snapshot", source=fake_src, iteration="oneshot",
                rename_map={"代码": "code", "名称": "name", "最新价": "price", "涨跌幅": "pct_chg"},
                conflict_cols=["code"])
    # DDL 无 NOT NULL,缺失列写 NULL,可接受
    n = runner.run_ingest(conn, spec, client=FakeClient())
    assert n >= 1
    assert conn.execute("SELECT code FROM spot_snapshot").fetchone()[0] == "000001"

def test_run_ingest_per_code_with_checkpoint(tmp_path, mocker):
    conn = _conn(tmp_path)
    fake_src = mocker.Mock(side_effect=lambda symbol: pd.DataFrame({
        "日期": ["2024-01-02"], "股票代码": [symbol], "收盘": [10.0], "开盘": [10.0],
        "最高": [10.0], "最低": [10.0], "成交量": [100], "成交额": [1000.0],
        "涨跌幅": [1.0], "换手率": [1.0]}))
    spec = Spec(name="daily_quote", table="daily_quote", source=fake_src, iteration="per_code",
                rename_map={"日期": "date", "股票代码": "code", "收盘": "close", "开盘": "open",
                            "最高": "high", "最低": "low", "成交量": "volume", "成交额": "amount",
                            "涨跌幅": "pct_chg", "换手率": "turnover"},
                conflict_cols=["code", "date"], arg_builder=lambda code: {"symbol": code})
    cp = checkpoint.Checkpoint(str(tmp_path / "cp.json"))
    runner.run_ingest(conn, spec, client=FakeClient(), checkpoint=cp,
                      code_source=["000001", "000002"])
    assert cp.is_done("daily_quote", "000001") and cp.is_done("daily_quote", "000002")
    # 第二次跑: 全部跳过,不再调用 source
    fake_src.side_effect = AssertionError("不该再调用")
    runner.run_ingest(conn, spec, client=FakeClient(), checkpoint=cp,
                      code_source=["000001", "000002"])  # 不抛即通过
