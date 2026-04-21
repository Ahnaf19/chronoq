# Tests

## Structure

```
tests/
├── conftest.py                    # Shared fixtures (MemoryStore, predictor_config returning RankerConfig)
├── ranker/                        # chronoq-ranker unit + integration tests (59)
│   ├── test_schemas.py            # Pydantic model validation, serialization
│   ├── test_config.py             # RankerConfig defaults and overrides
│   ├── test_memory_storage.py     # MemoryStore CRUD operations
│   ├── test_sqlite_storage.py     # SqliteStore persistence, metadata JSON
│   ├── test_features.py           # Feature extraction functions (legacy + DefaultExtractor)
│   ├── test_heuristic.py          # HeuristicEstimator: mean/std, unseen types
│   ├── test_gradient.py           # GradientEstimator: fit/predict, fallback
│   ├── test_predictor.py          # TaskRanker orchestration, thread safety
│   ├── test_predictor_integration.py  # Full lifecycle, SQLite persistence
│   ├── test_compat_shims.py       # v1 → v2 deprecation-alias regression
│   └── test_predict_scores.py     # predict_scores(list), ScoredTask, FeatureSchema, DefaultExtractor
├── server/                        # chronoq-demo-server unit + integration tests (24)
│   ├── test_queue.py              # Redis sorted set SJF ordering (fakeredis)
│   ├── test_scheduler.py          # Scheduler delegation to ranker + queue
│   ├── test_worker.py             # WorkerPool task processing (mocked tasks)
│   ├── test_api_tasks.py          # Task submission/status endpoints (httpx)
│   ├── test_api_metrics.py        # Metrics/retrain endpoints (httpx)
│   └── test_integration.py        # End-to-end: submit, drain, verify completion
├── bench/                         # Stub (1 import test; real suite lands Chunk 2)
└── celery/                        # Stub (1 import test; real suite lands Chunk 3)
```

## Running Tests

```bash
# All tests
uv run pytest -v                                # 85 tests

# Ranker tests only
uv run pytest tests/ranker/ -v                  # 59

# Server tests only
uv run pytest tests/server/ -v                  # 24

# With coverage
uv run pytest --cov=chronoq_ranker --cov=chronoq_demo_server --cov-report=term-missing

# Single test file
uv run pytest tests/ranker/test_predict_scores.py -v
```

## Test Dependencies

- **fakeredis**: In-memory Redis mock for server tests (no real Redis needed)
- **httpx**: Async HTTP client for FastAPI test endpoints via ASGITransport
- **pytest-asyncio**: Async test support with `asyncio_mode = "auto"`
- **hypothesis** (Chunk 1 W3+): property-based tests on rank invariance

## Conventions

- Server tests mock `simulate_task` for speed (no actual `asyncio.sleep`)
- Each test creates its own isolated fixtures (no shared state between tests)
- SQLite tests use `tmp_path` for filesystem isolation
- Integration tests verify full data flow: submit → process → telemetry recorded
- The shared `predictor_config` fixture still uses that name for backward compat but returns a `RankerConfig`; rename deferred to the next major bump.
