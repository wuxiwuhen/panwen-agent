.PHONY: install seed-backfill data-backfill data-incremental task0-financials eval-freeze test

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

# Task 0: sina 财务定向扩量 —— 4 张财务表从 2 股扩到 eval_codes 种子(~30 股)。
# 只跑 sina 端点(income/balance/cashflow/fin_indicator),避开 eastmoney 限流。
# 写入 data/live.duckdb(已存在则 upsert,幂等)。需联网,约数分钟。
task0-financials:
	mkdir -p data
	python scripts/expand_financials.py

# 冻结 live→eval,eval.duckdb 随仓提交以保证指标可复现。
# --as-of 实测自 income_statement.max(report_date) (Step 8 of Task 0, 2026-08-12):
# sina 4 端点回填后 max(report_date)=2026-06-30 (Q2 2026 中报已披露),按"实测冻结日"原则采用。
eval-freeze:
	mkdir -p data
	python scripts/freeze_eval.py --as-of 2026-06-30

test:
	pytest -v
