from __future__ import annotations
import duckdb
from panwen.data.ingest import specs, runner, client as clientmod


def run_daily(conn: duckdb.DuckDBPyConnection, *, client=clientmod) -> None:
    """每日增量: spot 全市场快照(1 调用)。

    其余 oneshot/per_date 域(融资融券/龙虎榜/宏观/板块/财报等)当前不在每日增量范围内 ——
    它们在下次全量 `data-backfill` 时刷新。范围说明见 README"已知限制"。
    财报按报告期补抓由 backfill 在披露季手动触发(periods 传新报告期)。
    """
    runner.run_ingest(conn, specs.SPOT_SPEC, client=client)
    # 其余 oneshot/per_date 域可在此追加今日日期的 per_date 调用
