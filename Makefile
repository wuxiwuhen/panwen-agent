.PHONY: install seed-backfill data-backfill data-incremental eval-freeze test

install:
	pip install -e ".[dev]"

# 开发: 用种子(~10 只)快速端到端验证。DuckDB 不自动建父目录,需先 mkdir。
seed-backfill:
	mkdir -p data
	python -c "from panwen.data import db; from panwen.data.ingest import backfill, checkpoint, client; \
	c=db.connect('data/live.duckdb'); db.init_schema(c); \
	backfill.run_all(c, seed_path='panwen/seeds/dev_codes.txt', periods=['20231231'], \
	checkpoint=checkpoint.Checkpoint('data/checkpoint.json'), client=client); c.close()"

# 生产: 全市场全量回填(数小时,夜间跑,支持断点续传)。
# 注意: periods 仅驱动 per_period spec(目前为 performance_express/业绩快报,
# 源自 eastmoney stock_yjbb_em,常被 rate-limit;best-effort,失败由 spec 级隔离吞掉)。
# 首次生产回填应把 periods 扩展为完整报告期历史(如 2015Q1 至最近一期),而非仅 2015 四个季度。
# macOS 无 coreutils `timeout`;长跑请用 nohup 或直接在夜间窗口运行。
data-backfill:
	mkdir -p data
	python -c "from panwen.data import db; from panwen.data.ingest import backfill, checkpoint, client; \
	c=db.connect('data/live.duckdb'); db.init_schema(c); \
	backfill.run_all(c, periods=['20150331','20150630','20150930','20151231'], \
	checkpoint=checkpoint.Checkpoint('data/checkpoint.json'), client=client); c.close()"

# 每日增量: 仅 spot 全市场快照(1 调用)。融资融券/龙虎榜/宏观等在下次 data-backfill 时刷新。
data-incremental:
	mkdir -p data
	python -c "from panwen.data import db; from panwen.data.ingest import incremental, client; \
	c=db.connect('data/live.duckdb'); db.init_schema(c); incremental.run_daily(c, client=client); c.close()"

# 冻结 live→eval,eval.duckdb 随仓提交以保证指标可复现。
eval-freeze:
	mkdir -p data
	python scripts/freeze_eval.py --as-of 2024-12-31

test:
	pytest -v
