# chronoq-ranker

Standalone ML library for task duration prediction. **Zero deps on server, Redis, FastAPI, Celery, vLLM.** Verify: `grep -r "chronoq_demo_server\|fastapi\|celery" .` returns nothing.

**Status:** v1 = point-regression (sklearn GBR) + auto-promoting heuristic. Chunk 1 replaces regressor with LightGBM `LGBMRanker` (lambdarank objective), renames `TaskPredictor` → `TaskRanker`, adds user-declarable `FeatureSchema`, adds drift detector.

## Ownership

- **Public API** (`ranker.py`, `schemas.py`, `config.py`, `features.py`, `__init__.py`, `models/base.py`, `storage/base.py`) → `library-architect`. Any edit = run `/architecture-check` first.
- **Ranker internals** (`models/*.py`, `features.py`, `drift.py`) → `ml-engineer`. Review via `/ml-review`.
- **Tests** → `qa-validator` for gate-running; `ml-engineer` for ranker test design.

## Layout (during Chunk 1 transition)

```
chronoq_ranker/
├── __init__.py       # Public exports — v2 additions arrive in Chunk 1
├── predictor.py      # → ranker.py in Chunk 1 (TaskPredictor → TaskRanker)
├── schemas.py        # TaskRecord (+ group_id, rank_label, feature_schema_version in Chunk 1)
├── config.py         # PredictorConfig → RankerConfig in Chunk 1
├── features.py       # → FeatureExtractor + DefaultExtractor + versioned FeatureSchema (Chunk 1)
├── models/
│   ├── base.py       # BaseEstimator ABC (extend with incremental_fit in Chunk 1)
│   ├── heuristic.py  # Per-type mean/std — cold-start, retained as RankByMeanEstimator
│   ├── gradient.py   # sklearn GBR — REPLACED by lambdarank.py in Chunk 1
│   ├── lambdarank.py # NEW Chunk 1 — LightGBM LGBMRanker (lambdarank objective)
│   └── oracle.py     # NEW Chunk 1 — SJF/SRPT using true actual_ms (benchmarks only)
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
uv run pytest tests/predictor/ -v           # 47 tests (moves to tests/ranker/ in Chunk 1)
```

Chunk 1+: add `hypothesis` property tests on rank invariance (swapping within-group features preserves ordering by ρ ≥ 0.95).

Tests use `memory://` storage and low thresholds (`cold_start_threshold=10`, `retrain_every_n=20`) via `conftest.py`.

## When modifying

- Any edit to `ranker.py`/`predictor.py`, `schemas.py`, `config.py`, `features.py`, `__init__.py` → `/architecture-check` FIRST (library-architect).
- Any edit to `models/*.py`, `features.py`, `drift.py` → `/ml-review` (ml-engineer).
- Changing schemas → update tests + demo-server code that uses them.
- Changing storage interface → update both Memory and Sqlite + tests.
- Changing model interface → update all estimators (heuristic + gradient + lambdarank + oracle).
