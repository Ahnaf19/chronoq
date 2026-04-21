# chronoq-ranker

Standalone ML library for task duration prediction. **Zero deps on server, Redis, FastAPI, Celery, vLLM.** Verify: `grep -r "chronoq_demo_server\|fastapi\|celery" .` returns nothing.

**Status:** Chunk 1 W3 complete. W1 renamed `TaskPredictor` → `TaskRanker`; W2 added `FeatureSchema` + `DefaultExtractor` (15 features) + `predict_scores()` batch API; W3 added `LambdaRankEstimator` (LightGBM `LGBMRanker`), `OracleRanker`, `drift.py` (`DriftDetector` + PSI), wired LambdaRank promotion/degrade into `TaskRanker.retrain()`, and 52 new tests (lambdarank, oracle, drift, hypothesis). 137 tests passing.

## Ownership

- **Public API** (`ranker.py`, `schemas.py`, `config.py`, `features.py`, `__init__.py`, `models/base.py`, `storage/base.py`) → `library-architect`. Any edit = run `/architecture-check` first.
- **Ranker internals** (`models/*.py`, `features.py`, `drift.py`) → `ml-engineer`. Review via `/ml-review`.
- **Tests** → `qa-validator` for gate-running; `ml-engineer` for ranker test design.

## Layout

```
chronoq_ranker/
├── __init__.py       # Public exports (TaskRanker, RankerConfig, FeatureSchema, DefaultExtractor, TaskCandidate, ScoredTask, ...) + legacy aliases via __getattr__
├── ranker.py         # TaskRanker — orchestrator (predict / predict_scores / record / retrain)
├── predictor.py      # DEPRECATED — 22-line shim re-exporting TaskRanker as TaskPredictor, emits DeprecationWarning on import
├── schemas.py        # TaskRecord (+ group_id, rank_label, feature_schema_version), PredictionResult, RetrainResult, FeatureSchema, TaskCandidate, QueueContext, ScoredTask
├── config.py         # RankerConfig (+ incremental_rounds, min_groups, full_refit_every_n_incrementals, psi_threshold); PredictorConfig alias retained
├── features.py       # FeatureExtractor ABC + DefaultExtractor (15 features) + DEFAULT_SCHEMA_V1; private _legacy_* helpers used by ranker.py and gradient.py
├── models/
│   ├── base.py       # BaseEstimator ABC + ModelType Literal
│   ├── heuristic.py  # Per-type mean/std — cold-start
│   ├── gradient.py   # sklearn GBR — used today; REPLACED by lambdarank.py in W3
│   ├── lambdarank.py # W3 — LightGBM LGBMRanker (lambdarank objective)
│   └── oracle.py     # W3 — SJF/SRPT using true actual_ms (benchmarks only)
├── storage/
│   ├── base.py       # TelemetryStore ABC
│   ├── memory.py     # MemoryStore — testing
│   └── sqlite.py     # SqliteStore — thread-safe, JSON metadata
└── drift.py          # NEW Chunk 1 — PSI + rolling MAE + DriftReport
```

## Chunk 1 — LambdaRank specifics

**Objective.** `LGBMRanker(objective="lambdarank", learning_rate=0.05, n_estimators=500, num_leaves=31, min_data_in_leaf=20)` — CPU-only, pairwise with NDCG gain.

**Pairwise label construction** (central algorithm):
- Group records by `group_id`. Default: 60s tumbling window of completion timestamps. Celery can pass a real `batch_id`.
- Within a group: `rank_label_i = (max_rank_in_group − rank_i)` where `rank_i` is ascending by `actual_ms`. Shortest job → highest label.
- Drop groups of size <2. Enforce `min_groups ≥ 20` per fit (`InsufficientGroupsError` if not).

**Incremental fit.** Warm-start via `init_model=<prev model path>`; add `incremental_rounds` new boosting rounds (default 10). Full refit every `full_refit_every_n_incrementals` (default 20) to bound drift accumulation. Reject new model if held-out Spearman ρ drops >0.1 vs previous.

**Feature schema** (versioned, user-declarable):
```python
class FeatureSchema(BaseModel):
    version: str                 # "v1-2026-04"
    numeric: list[str]
    categorical: list[str]
    required: list[str]
```
Attached to every `TaskRecord`. Retrain validates schema version match per record window.

**`DefaultExtractor` ships 15 features** (plan §3.3): `task_type`, `payload_size`, `hour_of_day`, `day_of_week`, `queue_depth`, `queue_depth_same_type`, `recent_mean_ms_this_type`, `recent_p95_ms_this_type`, `recent_count_this_type`, `time_since_last_retrain_s`, `worker_count_busy`, `worker_count_idle`, `prompt_length` (nullable), `user_tier` (cat, nullable), `retry_count`.

**No label leakage.** Features must be computable *before* the task runs. `actual_ms` is label-only.

## Metrics (ranker, not regressor)

Headline: **Spearman ρ**, **Kendall τ**, **pairwise accuracy** on held-out group. MAE/MAPE are secondary and must not lead any report. See `ml-engineer` agent spec for the full audit checklist.

## Thread safety

`threading.Lock` in `ranker.py` protects ONLY the `_estimator` pointer. Fit happens outside the lock. Storage has its own lock (`check_same_thread=False` for SQLite).

## Key behaviors (unchanged from v1)

- **Warm start**: init fits from existing storage if `count > 0`.
- **Auto-retrain**: triggered when `store.count_since(version) >= config.retrain_every_n`.
- **Heuristic fallback**: retained for cold start and unseen `task_type`s.

## Testing

```bash
uv run pytest tests/ranker/ -v              # 113 tests (47 original + 4 compat + 8 predict_scores + 25 lambdarank + 8 oracle + 11 drift + 8 hypothesis + 2 features)
```

Uses `memory://` storage and low thresholds (`cold_start_threshold=10`, `retrain_every_n=20`) via `conftest.py`. Hypothesis property tests in `test_lambdarank_hypothesis.py`: rank-label monotonicity, ρ range [-1,1], pairwise accuracy range [0,1], PSI non-negative.

## When modifying

- Any edit to `ranker.py`, `schemas.py`, `config.py`, `features.py`, `__init__.py`, `models/base.py`, `storage/base.py` → `/architecture-check` FIRST (library-architect).
- `predictor.py` is a frozen deprecation shim — don't edit unless removing it in a future major bump.
- Any edit to `models/*.py`, `features.py`, `drift.py` → `/ml-review` (ml-engineer).
- Changing schemas → update tests + demo-server code that uses them.
- Changing storage interface → update both Memory and Sqlite + tests.
- Changing model interface → update all estimators (heuristic + gradient + lambdarank + oracle).
