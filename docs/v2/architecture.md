---
status: current
last-synced-to-plan: 2026-04-21
source: `/Users/ahnaftanjid/.claude/plans/ok-i-want-golden-knuth.md` §3
---

# Architecture — Chronoq v2

## v1 → v2 component map

| v1 component | File | v2 fate |
|---|---|---|
| `TaskPredictor` | `predictor/chronoq_predictor/predictor.py:15` | **Keep orchestration, rename to `TaskRanker`; swap regressor→ranker semantics** |
| `HeuristicEstimator` | `predictor/chronoq_predictor/models/heuristic.py` | **Keep as `RankByMeanEstimator` cold-start fallback** |
| `GradientEstimator` (sklearn GBR) | `predictor/chronoq_predictor/models/gradient.py:15` | **Scrap. Replace with `LambdaRankEstimator` (LightGBM)** |
| `extract_features` | `predictor/chronoq_predictor/features.py:8` | **Rewrite as `DefaultExtractor` + versioned `FeatureSchema` (15 features)** |
| `TaskRecord` | schemas.py:9 | **Extend with `group_id`, `rank_label`, `feature_schema_version`** |
| `PredictorConfig` | config.py | **Rename `RankerConfig`; add `incremental_rounds`, `min_groups`, `psi_threshold`** |
| `SqliteStore` / `MemoryStore` | storage/ | **Keep; add Parquet export helper for bench** |
| `TaskQueue` (Redis) | server/chronoq_server/core/queue.py | **Demote to `demo-server/` reference** |
| `Scheduler`, `WorkerPool` | server/chronoq_server/core/ | **Demote; rewrite to consume `chronoq-ranker`** |
| `simulate_task()` | server/chronoq_server/task_registry.py:35 | **Scrap. SimPy + real traces in `chronoq-bench`** |
| `PredictionTracker` | server/chronoq_server/api/metrics.py:12 | **Move to `bench/chronoq_bench/metrics/tracker.py`; add ρ/τ/pairwise** |
| Alembic migrations | migrations/ | **Deleted** (overkill for a CLI tool) |
| 47 predictor tests | tests/predictor/ | **~60% survive rename; 40% rewritten for ranker semantics** |

## Repo layout (v2)

```
chronoq/
├── ranker/                    # chronoq-ranker (library)
│   └── chronoq_ranker/
│       ├── ranker.py          # TaskRanker (predict_scores/record/retrain)
│       ├── schemas.py         # TaskRecord, FeatureSchema, ScoredTask
│       ├── config.py          # RankerConfig
│       ├── features.py        # FeatureExtractor + DefaultExtractor (15 features)
│       ├── models/            # base.py, heuristic.py, lambdarank.py, oracle.py
│       ├── storage/           # base.py, memory.py, sqlite.py
│       └── drift.py           # DriftDetector (PSI + rolling MAE)
├── bench/                     # chronoq-bench (Chunk 2)
│   └── chronoq_bench/
│       ├── simulator.py       # SimPy DES
│       ├── traces/            # burstgpt.py, synthetic.py
│       ├── baselines/         # fcfs, priority_fcfs, sjf_oracle, srpt_oracle, random
│       ├── metrics/           # ranking.py (ρ,τ,pairwise), jct.py (p50/95/99, HoL, Jain)
│       └── experiments/       # jct_vs_load, drift_recovery, ablation_features
├── integrations/
│   ├── celery/                # chronoq-celery (Chunk 3)
│   ├── hatchet/               # sidecar stub (Chunk 4)
│   └── vllm/                  # deferred
├── demo-server/               # v1 demoted to reference
└── tests/                     # tests/{ranker,bench,celery,demo_server}/
```

## Key interfaces

### `TaskRanker` public API

```python
class TaskRanker:
    def __init__(self, config=None, storage=None, feature_extractor=None): ...
    def predict_scores(self, candidates: list[TaskCandidate],
                       group_id: str | None = None) -> list[ScoredTask]: ...
    def record(self, task_id, task_type, features, actual_ms, completion_context=None): ...
    def retrain(self, mode: Literal["full", "incremental"] = "incremental") -> RetrainResult: ...
    def drift_status(self) -> DriftReport: ...
```

**Key departure from v1:** `predict_scores` takes a LIST and returns relative scores (not per-item ms). LTR semantics.

### `FeatureSchema` — versioned, user-declarable

```python
class FeatureSchema(BaseModel):
    version: str                 # "v1-2026-04"
    numeric: list[str]
    categorical: list[str]
    required: list[str]
```

Attached to every `TaskRecord` at write time. Retrain validates schema version match.

### `DefaultExtractor` — 15 features

`task_type` (cat), `payload_size`, `hour_of_day`, `day_of_week`, `queue_depth`, `queue_depth_same_type`, `recent_mean_ms_this_type`, `recent_p95_ms_this_type`, `recent_count_this_type`, `time_since_last_retrain_s`, `worker_count_busy`, `worker_count_idle`, `prompt_length` (nullable), `user_tier` (cat, nullable), `retry_count`.

### `BaseRanker` ABC

`fit`, `incremental_fit`, `predict_scores`, `version`, `export`, `load`. Implementations: `RankByMeanEstimator`, `LambdaRankEstimator`, `OracleRanker`.

## Key algorithms

**Pairwise label construction (LambdaRank):**
1. Group records by `group_id` (default: 60s tumbling window of completions; Celery can pass `batch_id`).
2. Label = ascending rank by `actual_ms`; shortest job → highest label.
3. Drop groups of size <2; enforce `min_groups` (default 20) per fit.

**Incremental fit:**
- `init_model=<prev model path>` on LGBMRanker; add `incremental_rounds` new boosting rounds.
- Full refit every `full_refit_every_n_incrementals` (default 20).
- Validate: Spearman ρ on held-out 10%. Reject new model if ρ drops >0.1.

**Predict-score-order at runtime:**
1. Queue receives N candidates.
2. `extractor.extract(cand, ctx)` → feature matrix.
3. `ranker.predict_scores(X, group_sizes=[N])` → scores.
4. Return `argsort(-scores)` (highest = serve first).

**Feedback recording (Celery signals):** `task_prerun` captures `t_dequeued`; `task_success` computes `actual_ms` → `ranker.record()`; `task_failure` marks `failed=True` (excluded from training by default).

## Thread safety

`threading.Lock` in `ranker.py` protects ONLY the `_estimator` pointer. Fitting happens outside the lock. Storage has its own lock (`check_same_thread=False` for SQLite).
