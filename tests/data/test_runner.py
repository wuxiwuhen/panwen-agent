import pandas as pd
import pytest
from panwen.data import db
from panwen.data.ingest.specs import Spec, _KEY
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


# ---- Fix 1 回归: 列漂移保护(最高杠杆修复) ----

def _per_code_spec(source):
    return Spec(
        name="daily_quote", table="daily_quote", source=source, iteration="per_code",
        rename_map={"日期": "date", "股票代码": "code", "收盘": "close", "开盘": "open",
                    "最高": "high", "最低": "low", "成交量": "volume", "成交额": "amount",
                    "涨跌幅": "pct_chg", "换手率": "turnover"},
        conflict_cols=["code", "date"], arg_builder=lambda code: {"symbol": code})


def test_drift_skips_mark_and_warns(tmp_path, capsys):
    """Fix 1 核心回归: 源有数据但列与 rename_map 0 命中(列漂移)时,
    不得 upsert、不得 checkpoint.mark —— 该 key 必须下次重试;并须发出 [drift] 警告。
    旧实现: map_columns -> 0 列 -> upsert 0 行(不抛) -> mark DONE -> 永久静默丢失。
    """
    conn = _conn(tmp_path)
    # 源返回有数据(1 行),但列名与 rename_map 完全不匹配 -> 漂移
    drift_src = lambda **kw: pd.DataFrame({"WRONG_COL": ["x"], "OTHER": ["y"]})
    spec = _per_code_spec(drift_src)
    cp = checkpoint.Checkpoint(str(tmp_path / "cp.json"))
    n = runner.run_ingest(conn, spec, client=FakeClient(), checkpoint=cp,
                          code_source=["000001"])
    # 未写任何行
    assert n == 0
    assert conn.execute("SELECT count(*) FROM daily_quote").fetchone()[0] == 0
    # 关键: 未 mark done -> 下次会重试
    assert not cp.is_done("daily_quote", "000001")
    # 且 resum_iter 仍应包含该 key(待重试)
    assert "000001" in cp.resume_iter("daily_quote", ["000001"])
    # 警告已发出
    out = capsys.readouterr().out
    assert "[drift]" in out and "000001" in out


def test_genuinely_empty_source_is_marked_done(tmp_path, capsys):
    """Fix 1 关键语义对照: 源真返回 0 行(raw_rows==0)是合法空,仍应 mark done
    (空股票重试无意义)。不可把"合法空"与"漂移"混为一谈 -> 否则空股票会无限重试。
    """
    conn = _conn(tmp_path)
    empty_src = lambda **kw: pd.DataFrame(
        {"日期": [], "股票代码": [], "收盘": [], "开盘": [], "最高": [], "最低": [],
         "成交量": [], "成交额": [], "涨跌幅": [], "换手率": []})
    spec = _per_code_spec(empty_src)
    cp = checkpoint.Checkpoint(str(tmp_path / "cp.json"))
    runner.run_ingest(conn, spec, client=FakeClient(), checkpoint=cp,
                      code_source=["000001"])
    # 合法空 -> mark done(下次不重试)
    assert cp.is_done("daily_quote", "000001")
    assert "000001" not in cp.resume_iter("daily_quote", ["000001"])
    # 合法空不应触发漂移警告
    out = capsys.readouterr().out
    assert "[drift]" not in out


def test_drift_does_not_mask_subsequent_keys(tmp_path, capsys):
    """Fix 1 边界: 一个 key 漂移(跳过)后,同轮回填对其它 key 仍正常处理 ——
    漂移仅影响该 key,不应外泄为整轮异常(与 per-key 隔离哲学一致)。
    """
    conn = _conn(tmp_path)
    good_row = {"日期": ["2024-01-02"], "股票代码": ["000002"], "收盘": [10.0],
                "开盘": [10.0], "最高": [10.0], "最低": [10.0], "成交量": [100],
                "成交额": [1000.0], "涨跌幅": [1.0], "换手率": [1.0]}

    def src(symbol):
        if symbol == "000001":
            return pd.DataFrame({"WRONG": ["x"]})  # 漂移
        return pd.DataFrame(good_row)  # 正常

    spec = _per_code_spec(src)
    cp = checkpoint.Checkpoint(str(tmp_path / "cp.json"))
    runner.run_ingest(conn, spec, client=FakeClient(), checkpoint=cp,
                      code_source=["000001", "000002"])
    # 漂移 key 未 mark;正常 key 已 mark 且落库
    assert not cp.is_done("daily_quote", "000001")
    assert cp.is_done("daily_quote", "000002")
    assert conn.execute("SELECT count(*) FROM daily_quote").fetchone()[0] == 1


def test_oneshot_drift_warns(tmp_path, capsys):
    """Fix 1 oneshot 分支: 源有数据但 0 列命中(如 SPOT rename_map 猜错)时发声。
    oneshot 无 key/checkpoint,故只警告(仍返回 0)。"""
    conn = _conn(tmp_path)
    drift_src = lambda **kw: pd.DataFrame({"UNMATCHED": [1, 2]})
    spec = Spec(name="spot", table="spot_snapshot", source=drift_src, iteration="oneshot",
                rename_map={"代码": "code", "名称": "name", "最新价": "price"},
                conflict_cols=["code"])
    n = runner.run_ingest(conn, spec, client=FakeClient())
    assert n == 0
    out = capsys.readouterr().out
    assert "[drift]" in out and "spot" in out


def test_oneshot_with_key_const_col_asserts(tmp_path):
    """Fix 5 回归: oneshot spec 若在 const_cols 用 _KEY(无迭代键可用)应断言失败。
    oneshot 会注入 None;若该列是 PK 则 upsert 折叠/违约束 —— 潜在 footgun,需前置断言。
    """
    conn = _conn(tmp_path)
    spec = Spec(name="spot", table="spot_snapshot",
                source=lambda **kw: pd.DataFrame({"代码": ["000001"], "名称": ["x"]}),
                iteration="oneshot",
                rename_map={"代码": "code", "名称": "name"},
                conflict_cols=["code"],
                const_cols={"code": _KEY})  # oneshot 不该用 _KEY
    with pytest.raises(AssertionError):
        runner.run_ingest(conn, spec, client=FakeClient())


# ---- 真实数据回归: 日期格式规范化(2026-08-12 暴露) ----

def test_date_normalization_compact_to_iso(tmp_path, mocker):
    """真实回填 2026-08-12 暴露的 bug 回归: stock_financial_report_sina 返回紧凑式
    报告日 '20240630',而 DuckDB DATE 列要求 'YYYY-MM-DD',不规范化会导致 upsert 整批
    'invalid date field format' 失败(income/balance/cashflow 因此写 0 行)。
    runner._normalize_dates 须把 date 类列(见 schema.COLUMN_CLASS)统一为 YYYY-MM-DD。
    """
    conn = _conn(tmp_path)
    # 紧凑式日期 + 中文财务列(模拟 stock_financial_report_sina 利润表返回)
    fake_src = mocker.Mock(return_value=pd.DataFrame({
        "报告日": ["20240630", "20231231"],   # 紧凑式,非 ISO
        "营业总收入": [100.0, 90.0],
        "营业成本": [60.0, 55.0],
        "净利润": [40.0, 35.0]}))
    spec = Spec(name="income", table="income_statement", source=fake_src,
                iteration="per_code",
                rename_map={"报告日": "report_date", "营业总收入": "revenue",
                            "营业成本": "oper_cost", "净利润": "net_profit"},
                conflict_cols=["code", "report_date"],
                arg_builder=lambda code: {"symbol": code},
                const_cols={"code": _KEY})  # 端点不返回股票代码,从迭代键注入
    n = runner.run_ingest(conn, spec, client=FakeClient(), code_source=["600519"])
    assert n == 2  # 两行都应成功落库(未规范化则 0 行)
    # DATE 列读回为 datetime.date -> 用 cast 取字符串,确认已规范化为 ISO
    rows = conn.execute(
        "SELECT cast(report_date as varchar) FROM income_statement "
        "ORDER BY report_date").fetchall()
    assert [r[0] for r in rows] == ["2023-12-31", "2024-06-30"]
    # code 列由 const_cols(_KEY)注入,确认非空
    assert conn.execute("SELECT code FROM income_statement LIMIT 1").fetchone()[0] == "600519"


def test_date_normalization_already_iso_is_noop(tmp_path, mocker):
    """已合规的 ISO 日期('2024-06-30')经 _normalize_dates 应保持不变(no-op),
    不得误伤(如截断成 NULL)。对照上例的紧凑式,确保规范化对两种格式都安全。
    """
    conn = _conn(tmp_path)
    fake_src = mocker.Mock(return_value=pd.DataFrame({
        "报告日": ["2024-06-30", "2023-12-31"],   # 已是 ISO 带横线
        "营业总收入": [100.0, 90.0],
        "营业成本": [60.0, 55.0],
        "净利润": [40.0, 35.0]}))
    spec = Spec(name="income", table="income_statement", source=fake_src,
                iteration="per_code",
                rename_map={"报告日": "report_date", "营业总收入": "revenue",
                            "营业成本": "oper_cost", "净利润": "net_profit"},
                conflict_cols=["code", "report_date"],
                const_cols={"code": _KEY})
    runner.run_ingest(conn, spec, client=FakeClient(), code_source=["600519"])
    rows = conn.execute(
        "SELECT cast(report_date as varchar) FROM income_statement "
        "ORDER BY report_date").fetchall()
    assert [r[0] for r in rows] == ["2023-12-31", "2024-06-30"]


def test_date_normalization_chinese_month(tmp_path, mocker):
    """真实回填 2026-08-12 暴露: macro_china_cpi 的 月份 为中文 '2026年07月份' (仅年月无日),
    通用 pd.to_datetime 无法解析 -> NaT -> NULL -> macro_series.date(PK)违约, 整批写 0 行。
    _normalize_dates 须剥离 年/月份 token 后解析, 仅年月者默认取该月 1 号 ('2026-07-01')。"""
    conn = _conn(tmp_path)
    fake_src = mocker.Mock(return_value=pd.DataFrame({
        "月份": ["2026年07月份", "2025年12月份"],   # 中文年月, 无日
        "全国-同比增长": [2.7, -0.3],
    }))
    spec = Spec(name="macro_cpi", table="macro_series", source=fake_src,
                iteration="oneshot",
                rename_map={"月份": "date", "全国-同比增长": "value"},
                conflict_cols=["indicator", "date"],
                const_cols={"indicator": "CPI_YOY"})  # indicator 由 const_cols 注入
    n = runner.run_ingest(conn, spec, client=FakeClient())
    assert n == 2  # 未规范化则 0 行(中文月份 PK 违约)
    rows = conn.execute(
        "SELECT cast(date as varchar) FROM macro_series ORDER BY date").fetchall()
    assert [r[0] for r in rows] == ["2025-12-01", "2026-07-01"]  # 年月 -> 该月 1 号
    assert conn.execute("SELECT indicator FROM macro_series LIMIT 1").fetchone()[0] == "CPI_YOY"
