# 盘问 / PanWen

> 用中文问盘：A 股自然语言查询 Agent

**状态 / Status:** Phase 1 数据层（Data layer）。本仓库当前只包含数据采集与建模层（akshare → DuckDB）；Agent 问答核心、ValidSQL 约束、RAG 与冻结评测（Eval）尚未实现，计划在 Plan 2/3 推进。请勿将其当作一个可用的端到端 Agent。

---

## 数据层（akshare → DuckDB）

盘问的数据来自 [akshare](https://akshare.akfamily.xyz)（MIT，免费无 token）。仓库**只发入库脚本不发数据**。

```bash
make install
make seed-backfill    # 开发: ~10 只种子快速验证
make data-backfill    # 生产: 全市场全量回填(数小时,建议夜间;支持断点续传)
make data-incremental # 每日增量(spot 全市场快照,1 调用)
make eval-freeze      # 冻结 live→eval,随仓提交以保证指标可复现
```

- 日行情存**后复权(hfq)**。
- ROE / ROA / 毛利率 / 净利率 / 资产负债率 取自财务指标接口 (`financial_indicator`)；PE / PB 取自实时行情快照 (`spot_snapshot`)。
- `data/live.duckdb`（gitignore，每日刷新）与 `data/eval.duckdb`（冻结，随仓提交）双库分离。
- 数据稳定性说明：北向资金因 2024-08-19 监管调整停止实时披露，本数据层不含此维度（改由资讯工具定性补充，见 Plan 2）。

### 已知限制 / Known limitations

- **未校准列名 (UNVERIFIED rename_maps):** 受限网络环境下，部分 eastmoney/sina 端点的中文列名未经实测校准（行情快照/板块/龙虎榜/十大股东/财务指标/三大报表等）。首次生产回填前需在开放网络用 `scripts/probe_akshare.py` 重新校准 —— `map_columns` 会静默丢弃未匹配的列，列名漂移会导致整张表写空。
- **融资融券行数上限:** `stock_margin_sse` 单次调用上限约 2000 行（约最近 8 年）；完整历史需要按年分窗口抓取（计划在 MVP 后增强）。
- **每日增量范围:** `run_daily` 当前仅刷新 `spot_snapshot`（全市场快照，1 次调用）；融资融券/龙虎榜/宏观等在下次全量 `data-backfill` 时刷新。
- 北向资金因 2024-08-19 监管调整停止实时披露，本数据层不含此维度。
