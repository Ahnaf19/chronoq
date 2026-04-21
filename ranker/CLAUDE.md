# chronoq-ranker

Standalone ML library for task duration prediction. **Zero deps on server, Redis, FastAPI, Celery, vLLM.** Verify: `grep -r "chronoq_demo_server\|fastapi\|celery" .` returns nothing.

**Status:** v1 = point-regression (sklearn GBR) + auto-promoting heuristic. Chunk 1 replaces regressor with LightGBM `LGBMRanker` (lambdarank objective), renames `TaskPredictor` → `TaskRanker`, and adds user-declarable `FeatureSchema`.

## Layout

```
chronoq_ranker/
├── __init__.py       # Public exports (v2 additions arrive in Chunk 1)
├── predictor.py      # TaskPredictor — orchestrator (renamed TaskRanker in Chunk 1)
├── schemas.py        # Pydantic: TaskRecord, PredictionResult, RetrainResult
├── config.py         # PredictorConfig (renamed RankerConfig in Chunk 1)
├── features.py       # extract_features (becomes FeatureExtractor + FeatureSchema in Chunk 1)
├── models/
│   ├── base.py       # BaseEstimator ABC
│   ├── heuristic.py  # Per-type mean/std — cold-start fallback (kept as baseline in v2)
│   └── gradient.py   # sklearn GBR regressor — REPLACED by lambdarank.py in Chunk 1
└── storage/
    ├── base.py       # TelemetryStore ABC
    ├── memory.py     # MemoryStore — testing
    └── sqlite.py     # SqliteStore — thread-safe, JSON metadata column
```

## Patterns

- **Strategy**: `BaseEstimator` ABC. Chunk 1 adds `LambdaRankEstimator` + `OracleRanker` (SJF/SRPT baselines).
- **Pluggable storage**: `TelemetryStore` ABC + `create_store(uri)` factory. Add backend → implement the 5 methods.
- **Auto-promotion** (v1): `retrain()` checks total records vs `cold_start_threshold` to pick estimator type.
- **Thread safety**: `threading.Lock` in `predictor.py` protects ONLY the `_estimator` pointer. Fit happens outside the lock. Storage has its own lock.

## Key behaviors

- **Warm start**: init fits from existing storage if `count > 0`.
- **Auto-retrain**: triggered when `store.count_since(version) >= config.retrain_every_n`.
- **Heuristic fallback**: `GradientEstimator` keeps an internal `HeuristicEstimator` for unseen task types.
- **Predictions clamped**: `GradientEstimator` clamps to ≥1.0ms.

## Testing

```bash
uv run pytest tests/predictor/ -v           # 47 tests
```

Tests use `memory://` storage and low thresholds (`cold_start_threshold=10`, `retrain_every_n=20`) via `conftest.py`.

## When modifying

- **Any change to `ranker.py`/`predictor.py`, `schemas.py`, `config.py`, `features.py`, `__init__.py` → invoke `/architecture-check` FIRST** (library-architect agent).
- Changing schemas → update tests + demo-server code that uses them.
- Changing storage interface → update both Memory and Sqlite + tests.
- Changing model interface → update all estimators (heuristic + gradient + coming: lambdarank + oracle).
