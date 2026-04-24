# chronoq-ranker

> Learning-to-rank scheduling library. Predict which queued job finishes fastest and run it first.

Trained LightGBM LambdaRank over 15 features, online incremental retraining, drift detection. Standalone ML library — zero runtime dependencies on Celery, Redis, FastAPI, or any queueing framework. Works with Celery via the companion [`chronoq-celery`](https://pypi.org/project/chronoq-celery/) package, or with any task system via the `predict_scores(candidates)` API.

## Install

```bash
pip install chronoq-ranker
```

## Why this exists

Python task queues — Celery, RQ, Dramatiq, and others — all dispatch in FIFO or static-priority order. On heavy-tail workloads (LLM inference, media transcoding, data pipelines), a 20 ms `resize` job waits behind a 1.8 s `transcode` for no good reason.

Ten-plus years of systems research says learned scheduling beats FIFO on these workloads. Chronoq packages that research as a reusable Python library: record job completion telemetry, let a LightGBM LambdaRank model learn the duration structure, then use `predict_scores()` to rank pending jobs before dispatch.

## Quick start

```python
from chronoq_ranker import TaskRanker, TaskCandidate

ranker = TaskRanker(storage="sqlite:///telemetry.db")

# Feed telemetry as jobs complete
ranker.record(task_type="resize",    payload_size=2048,  actual_ms=312.4)
ranker.record(task_type="transcode", payload_size=8000,  actual_ms=1780.1)
# ... enough records trigger auto-retraining from heuristic → LambdaRank ...

# Rank pending jobs shortest-first
scored = ranker.predict_scores([
    TaskCandidate(task_id="j1", task_type="transcode", payload_size=8000),
    TaskCandidate(task_id="j2", task_type="resize",    payload_size=500),
])
# scored[0] is the job LambdaRank predicts finishes fastest
for s in scored:
    print(f"rank={s.rank}  {s.task_id}  score={s.score:.4f}")
```

## What you get

- **LightGBM `LGBMRanker`** with lambdarank objective — pairwise learning with NDCG gain
- **Online incremental retraining** — warm-start via `init_model`; full refit every N incrementals to bound drift accumulation
- **15-feature default extractor** (`task_type`, `payload_size`, `hour_of_day`, `day_of_week`, `queue_depth`, `queue_depth_same_type`, `recent_mean_ms_this_type`, `recent_p95_ms_this_type`, `recent_count_this_type`, `time_since_last_retrain_s`, `worker_count_busy`, `worker_count_idle`, `prompt_length`, `user_tier`, `retry_count`) — or supply your own `FeatureExtractor`
- **Pluggable storage** — `"memory://"` for tests, `"sqlite:///path.db"` for persistence
- **Drift detection** — PSI over numeric features (warn >0.2, flag >0.3)
- **Rank-oriented evaluation** — Spearman ρ, Kendall τ, pairwise accuracy; MAE is secondary

## Evidence

Validated on 4 workload traces (synthetic Pareto, BurstGPT real LLM inference, Google Borg 2011 cluster-batch, Azure Functions 2019 serverless).

On the synthetic Pareto trace: **+32% mean JCT / +17.5% p99 vs FCFS at ρ=0.7**, within 13.4% of a clairvoyant SJF-oracle. On BurstGPT (real LLM inference): LambdaRank tracks the SJF-oracle upper bound **within 5.1% at p99**. On Google Borg: **+14–22% mean JCT at ρ ≥ 0.8** where queue-ordering decisions dominate.

All results reproducible with one command (`make bench`). Byte-identical `results.json` across macOS and Windows (SHA-256 verified). Full methodology and per-trace tables in [BENCHMARKS.md](https://github.com/Ahnaf19/chronoq/blob/main/docs/v2/BENCHMARKS.md).

## Configuration

```python
from chronoq_ranker import RankerConfig, TaskRanker

config = RankerConfig(
    cold_start_threshold=50,               # records before promoting to LambdaRank
    retrain_every_n=100,                   # auto-retrain trigger interval
    incremental_rounds=10,                 # warm-start boosting rounds per incremental fit
    full_refit_every_n_incrementals=20,    # force full refit every N incrementals
    min_groups=20,                         # minimum pairwise groups per fit
    num_leaves=31,                         # LightGBM num_leaves
    n_estimators=500,                      # LightGBM n_estimators
    learning_rate=0.05,                    # LightGBM learning rate
    storage_uri="sqlite:///telemetry.db",
)
ranker = TaskRanker(config=config)
```

## Custom feature extractor

The default extractor ships 15 features tuned for general-purpose task queues. Roll your own by subclassing `FeatureExtractor`:

```python
from chronoq_ranker import FeatureExtractor, FeatureSchema, TaskRanker

class MyExtractor(FeatureExtractor):
    schema = FeatureSchema(
        version="my-v1",
        numeric=["payload_size"],
        categorical=["task_type"],
    )

    def extract(self, candidate, context=None):
        return {
            "task_type": candidate.task_type,
            "payload_size": float(candidate.features.get("payload_size", 0)),
        }

    def extract_from_record(self, record):
        return {
            "task_type": record.task_type,
            "payload_size": float(record.payload_size),
        }

ranker = TaskRanker(feature_extractor=MyExtractor())
```

## Integration

- **Celery**: [`chronoq-celery`](https://pypi.org/project/chronoq-celery/) provides a 2-line `LearnedScheduler` drop-in with `fifo` / `shadow` / `active` modes
- **Any other task system**: call `ranker.predict_scores(candidates)` before dispatch, `ranker.record(...)` after completion

## Honest limitations

- **p99 starvation at ρ ≥ 0.8**: SJF-family tradeoff — short-first bias indefinitely delays long jobs at the tail. Pair with aging in production. An aging-aware scheduler is planned for v0.3.0.
- **Workload-dependent wins**: on traces where even a clairvoyant oracle cannot improve p99 (narrow duration variance, single task type), the ranker also cannot. The bench harness is a diagnostic tool for this — see the Azure Functions result in BENCHMARKS.md.
- **Pre-1.0 API**: breaking changes are allowed in minor-version bumps under the project's semver policy; deprecation shims land one minor ahead with a CHANGELOG "Breaking" entry.

## Runtime dependencies

`lightgbm>=4.3`, `numpy>=1.26`, `pydantic>=2.0`, `scikit-learn>=1.4`, `loguru>=0.7`. No Celery, Redis, FastAPI, or other queueing framework imports.

## Links

- Monorepo: https://github.com/Ahnaf19/chronoq
- Full benchmarks: https://github.com/Ahnaf19/chronoq/blob/main/docs/v2/BENCHMARKS.md
- Celery integration: https://pypi.org/project/chronoq-celery/
- MIT license
