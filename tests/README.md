# Tests

## Structure

```
tests/
├── conftest.py              # Shared fixtures (MemoryStore, PredictorConfig)
├── predictor/               # chronoq-predictor unit + integration tests
│   ├── test_schemas.py      # Pydantic model validation, serialization
│   ├── test_config.py       # PredictorConfig defaults and overrides
│   ├── test_memory_storage.py   # MemoryStore CRUD operations
│   ├── test_sqlite_storage.py   # SqliteStore persistence, metadata JSON
│   ├── test_features.py     # Feature extraction functions
│   ├── test_heuristic.py    # HeuristicEstimator: mean/std, unseen types
│   ├── test_gradient.py     # GradientEstimator: fit/predict, fallback
│   ├── test_predictor.py    # TaskPredictor orchestration, thread safety
│   └── test_predictor_integration.py  # Full lifecycle, SQLite persistence
└── server/                  # chronoq-server unit + integration tests
    ├── test_queue.py        # Redis sorted set SJF ordering (fakeredis)
    ├── test_scheduler.py    # Scheduler delegation to predictor + queue
    ├── test_worker.py       # WorkerPool task processing (mocked tasks)
    ├── test_api_tasks.py    # Task submission/status endpoints (httpx)
    ├── test_api_metrics.py  # Metrics/retrain endpoints (httpx)
    └── test_integration.py  # End-to-end: submit, drain, verify completion
```

## Running Tests

```bash
# All tests
uv run pytest -v

# Predictor tests only
uv run pytest tests/predictor/ -v

# Server tests only
uv run pytest tests/server/ -v

# With coverage
uv run pytest --cov=chronoq_predictor --cov=chronoq_server --cov-report=term-missing

# Single test file
uv run pytest tests/predictor/test_predictor.py -v
```

## Test Dependencies

- **fakeredis**: In-memory Redis mock for server tests (no real Redis needed)
- **httpx**: Async HTTP client for FastAPI test endpoints via ASGITransport
- **pytest-asyncio**: Async test support with `asyncio_mode = "auto"`

## Conventions

- Server tests mock `simulate_task` for speed (no actual `asyncio.sleep`)
- Each test creates its own isolated fixtures (no shared state between tests)
- SQLite tests use `tmp_path` for filesystem isolation
- Integration tests verify full data flow: submit -> process -> telemetry recorded
