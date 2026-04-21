# chronoq-predictor

Standalone ML library for predicting task execution time. **Zero dependency on chronoq-server, Redis, or FastAPI.**

## Package Structure

```
chronoq_ranker/
├── __init__.py       # Public exports: TaskPredictor, PredictorConfig, PredictionResult, RetrainResult, TaskRecord
├── predictor.py      # TaskPredictor — main orchestrator (predict/record/retrain)
├── schemas.py        # Pydantic v2 models (TaskRecord, PredictionResult, RetrainResult)
├── config.py         # PredictorConfig dataclass (thresholds, storage URI)
├── features.py       # extract_features() and extract_training_features()
├── models/
│   ├── base.py       # BaseEstimator ABC (fit, predict, version, model_type)
│   ├── heuristic.py  # HeuristicEstimator — per-type mean/std, cold-start fallback
│   └── gradient.py   # GradientEstimator — sklearn GBR, label-encoded task_type
└── storage/
    ├── base.py       # TelemetryStore ABC (save, get_all, get_by_type, count, count_since)
    ├── memory.py     # MemoryStore — list-backed, for testing
    ├── sqlite.py     # SqliteStore — thread-safe sqlite3 with JSON metadata
    └── __init__.py   # create_store(uri) factory
```

## Design Patterns

- **Strategy pattern**: `BaseEstimator` ABC with `HeuristicEstimator` and `GradientEstimator`. To add a new model, subclass `BaseEstimator` and implement `fit()`, `predict()`, `version()`, `model_type()`.
- **Pluggable storage**: `TelemetryStore` ABC. To add a new backend (PostgreSQL, DynamoDB, etc.), implement the 5 methods.
- **Factory**: `create_store(uri)` in `storage/__init__.py` dispatches on URI scheme.
- **Auto-promotion**: `predictor.retrain()` checks total record count vs `cold_start_threshold` to decide estimator type.

## Thread Safety

```
predict():  lock → read _estimator ref → unlock → call predict (no lock held)
record():   save to storage (storage has own lock) → check auto-retrain count
retrain():  fit new estimator (NO lock) → lock → swap _estimator ref → unlock
```

The lock is `threading.Lock` in `predictor.py`. It protects ONLY the `_estimator` pointer — never held during computation.

## Key Behaviors

- **Warm start**: On init, if storage has existing data, fits a model immediately.
- **Auto-retrain**: Triggered when `store.count_since(current_model_version) >= config.retrain_every_n`.
- **Auto-promotion**: When total records >= `cold_start_threshold`, retrain uses `GradientEstimator` instead of `HeuristicEstimator`. First promotion sets `promoted=True` in RetrainResult.
- **Heuristic fallback**: `GradientEstimator` keeps an internal `HeuristicEstimator` for unseen task types that weren't in the training data.
- **Confidence**: Heuristic: `1/(1 + std/max(mean, 1))`. Gradient: `max(0.1, min(1.0, 1 - mae/max(mean_pred, 1)))`.
- **Predictions clamped**: GradientEstimator clamps predictions to >= 1.0ms.

## Testing

```bash
uv run pytest tests/predictor/ -v           # All 47 predictor tests
uv run pytest tests/predictor/test_predictor.py -v  # Orchestrator tests
uv run pytest tests/predictor/test_predictor_integration.py -v  # Full lifecycle
```

Tests use `memory://` storage and low thresholds (`cold_start_threshold=10`, `retrain_every_n=20`) via `conftest.py` fixtures.

## When Modifying

- Adding a public type → update `__init__.py` `__all__` list
- Changing schemas → check test_schemas.py, and server code that constructs/reads these types
- Changing storage interface → update both MemoryStore and SqliteStore, plus their tests
- Changing model interface → update both HeuristicEstimator and GradientEstimator
- Changing features → update `features.py`, `gradient.py` (which consumes features), and test_features.py
