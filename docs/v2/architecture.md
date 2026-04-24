---
status: current
last-synced-to-plan: 2026-04-24
source: "plan §3"
---

# Architecture — Chronoq v2

## v1 → v2 component map

All v1 components listed below have been migrated. Status column uses v0.X.Y release labels.

| v1 component | v2 fate | Status |
|---|---|---|
| `TaskPredictor` (`predictor/chronoq_predictor/predictor.py`) | Renamed to `TaskRanker` in `ranker/chronoq_ranker/ranker.py`; v1 import retained as 22-line deprecated shim that emits `DeprecationWarning` | ✅ v0.2.0 |
| `HeuristicEstimator` | Retained unchanged as cold-start fallback | ✅ v0.2.0 |
| `GradientEstimator` (sklearn GBR) | Replaced by `LambdaRankEstimator` (LightGBM `LGBMRanker`, lambdarank objective) | ✅ v0.2.0 |
| `extract_features` free function | Rewritten as `DefaultExtractor` + versioned `FeatureSchema` (15 features). Legacy shim retained with `DeprecationWarning`; internal callers use private `_legacy_*` helpers | ✅ v0.2.0 |
| `TaskRecord` | Extended with `group_id`, `rank_label`, `feature_schema_version` (all defaulted → v1 records deserialize unchanged). `SqliteStore` migrated via idempotent `ALTER TABLE ADD COLUMN` | ✅ v0.2.0 |
| `PredictorConfig` | Renamed `RankerConfig`; added `incremental_rounds`, `min_groups`, `full_refit_every_n_incrementals`, `psi_threshold`. `PredictorConfig` silent alias retained | ✅ v0.2.0 |
| `SqliteStore` / `MemoryStore` | Retained | ✅ v0.2.0 |
| `TaskQueue` (Redis) | Demoted to `demo-server/` reference | ✅ v0.2.0 |
| `Scheduler`, `WorkerPool` | Demoted to `demo-server/`; real scheduling moved to `chronoq-celery` | ✅ v0.2.0 |
| `simulate_task()` | Replaced by SimPy + real traces in `chronoq-bench` | ✅ v0.2.0 |
| `PredictionTracker` | Moved to `bench/chronoq_bench/metrics/` + ρ/τ/pairwise metrics added | ✅ v0.2.0 |
| Alembic migrations | Deleted (overkill for a CLI tool) | ✅ v0.2.0 |
| 47 predictor tests | Moved to `tests/ranker/`; compat-shim + predict_scores tests added | ✅ v0.2.0 |
| `TaskCandidate`, `ScoredTask`, `QueueContext`, `FeatureSchema`, `FeatureExtractor`, `predict_scores(list)` method, `DEFAULT_SCHEMA_V1` | New public surface (additive) | ✅ v0.2.0 |
| `LambdaRankEstimator`, `OracleRanker`, `drift.py` (PSI + rolling MAE) | New modules | ✅ v0.2.0 |

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
├── bench/                     # chronoq-bench
│   └── chronoq_bench/
│       ├── simulator.py       # SimPy DES
│       ├── traces/            # burstgpt.py, borg.py, azure.py, synthetic.py
│       ├── baselines/         # fcfs, priority_fcfs, sjf_oracle, srpt_oracle, random
│       ├── metrics/           # ranking.py (ρ,τ,pairwise), jct.py (p50/95/99, HoL, Jain)
│       └── experiments/       # jct_vs_load, drift_recovery, ablation_features, jct_vs_concurrency
├── integrations/
│   ├── celery/                # chronoq-celery
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
