# tests

71 tests total: 47 predictor + 24 server. All run without external services (no real Redis, no real DB).

## Structure

```
tests/
├── conftest.py              # Shared fixtures: memory_store, predictor_config (low thresholds)
├── predictor/               # 47 tests
│   ├── test_schemas.py      # Pydantic validation, defaults, round-trip
│   ├── test_config.py       # PredictorConfig defaults, overrides, mutable safety
│   ├── test_memory_storage.py   # MemoryStore CRUD operations
│   ├── test_sqlite_storage.py   # SqliteStore CRUD + persistence + JSON metadata
│   ├── test_features.py     # Feature extraction keys, defaults, ranges
│   ├── test_heuristic.py    # Heuristic predict/fit, unseen types, confidence bounds
│   ├── test_gradient.py     # GradientBoosting fit/predict, unseen fallback, clamping
│   ├── test_predictor.py    # TaskPredictor orchestrator: zero-state, auto-retrain, auto-promote, thread safety
│   └── test_predictor_integration.py  # Full lifecycle: 100+ records, promotion, SQLite persistence
└── server/                  # 24 tests
    ├── test_queue.py        # SJF ordering, empty dequeue, peek, status updates
    ├── test_scheduler.py    # Delegation to predictor and queue
    ├── test_worker.py       # Worker processes task, feeds telemetry, clean stop
    ├── test_api_tasks.py    # Submit, get status, batch, queue snapshot, 404
    ├── test_api_metrics.py  # Metrics response, retrain, empty predictions
    └── test_integration.py  # Submit-and-drain, SJF tendency verification
```

## Conventions

- **asyncio_mode = "auto"** — async test functions are auto-detected, no `@pytest.mark.asyncio` needed
- **fakeredis**: Server tests create `FakeRedis(decode_responses=True)` — same API as real redis-py async
- **tmp_path**: SQLite tests use pytest's `tmp_path` fixture for isolated DB files
- **Mocked simulate_task**: Integration tests patch `simulate_task` to `asyncio.sleep(0.01)` for speed
- **Low thresholds**: `conftest.py` provides `predictor_config` with `cold_start_threshold=10`, `retrain_every_n=20`

## Running

```bash
uv run pytest -v                           # All tests
uv run pytest tests/predictor/ -v          # Predictor only
uv run pytest tests/server/ -v             # Server only
uv run pytest -k "test_predictor" -v       # By name pattern
uv run pytest --cov=chronoq_predictor --cov=chronoq_server  # With coverage
```

## Adding Tests

- Place predictor tests in `tests/predictor/test_<module>.py`
- Place server tests in `tests/server/test_<module>.py`
- Use `memory_store` and `predictor_config` fixtures from conftest.py
- Server tests: create FakeRedis + TaskQueue in the test or fixture, not as module-level state
- Keep tests fast: mock `simulate_task`, use `memory://` storage, use low thresholds
