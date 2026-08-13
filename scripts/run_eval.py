"""make eval 入口：跑全集 + ablation 矩阵，打印实测指标(spec §8.3)。

注意：指标全部实测，绝不编造。范围门增益为可选加分项(本脚本默认不跑)。
"""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from panwen.agent import backend, config
from panwen.agent.loop import run_query
from panwen.eval import runner, ablation, panel
from panwen.rag.embed import BgeEmbedder
from panwen.rag.schema_retrieever import SchemaRetriever
from panwen.rag.fewshot_store import FewshotStore

DATASET = "panwen/eval/dataset/questions.yaml"
EVAL_DB = "data/eval.duckdb"


def _build_rag_fewshot(cfg):
    emb = BgeEmbedder()
    rag = SchemaRetriever(emb, topk=cfg.schema_topk, cache_dir="data/rag_cache")
    fs = FewshotStore.from_dataset(DATASET, emb, k=cfg.fewshot_k)
    return rag, fs


def _predict(cfg):
    be = backend.make_backend("deepseek")
    rag, fs = _build_rag_fewshot(cfg)

    def fn(question):
        from panwen.data import db
        conn = db.connect(EVAL_DB, read_only=True)
        try:
            res = run_query(question, conn, be, rag, fs, cfg)
            return res.sql, res.rows
        finally:
            conn.close()
    return fn


def main():
    print("=" * 60)
    print("单配置(全开)评测")
    fn = _predict(config.AgentConfig())
    rep = runner.run_eval(DATASET, EVAL_DB, fn)
    print(panel.render(rep))

    print("\n" + "=" * 60)
    print("逐组件 ablation(边际贡献)")
    rows = ablation.run_ablation(DATASET, EVAL_DB,
                                 lambda cfg: runner.run_eval(DATASET, EVAL_DB, _predict(cfg)))
    print(f"{'配置':18s} {'exec_acc':>9s} {'mean_f1':>8s} {'边际':>8s}")
    for r in rows:
        m = "—" if r["marginal"] is None else f"{r['marginal']:+.1%}"
        print(f"{r['config']:18s} {r['exec_acc']:>8.1%} {r['mean_f1']:>8.3f} {m:>8s}")
    print("\n注：指标为自建冻结集实测，非跨域基准。范围门增益为可选加分项(未跑)。")


if __name__ == "__main__":
    main()
