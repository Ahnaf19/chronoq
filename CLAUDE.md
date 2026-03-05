# Chronoq

Self-optimizing task queue with ML-based Shortest Job First (SJF) scheduling.

## Monorepo Layout

- `chronoq_predictor/` — standalone pip-installable ML predictor library (zero Redis/FastAPI deps)
- `chronoq_server/` — full task queue: Redis sorted set SJF queue, async workers, FastAPI API
- `tests/predictor/` — predictor unit + integration tests
- `tests/server/` — server unit + integration tests (fakeredis)

## Tech Stack

- Python 3.11, uv workspace
- Pydantic v2 for schemas, scikit-learn for ML, loguru for logging
- FastAPI + uvicorn for API, redis-py async for queue
- pytest + pytest-asyncio for tests, fakeredis for Redis mocking

## Conventions

- Ruff: line-length=100, target-version="py311", double quotes
- Type hints on all public functions, `X | None` union style
- Google-style docstrings on public classes/methods
- `datetime.now(timezone.utc)` for timestamps
- Thread safety via `threading.Lock` on shared state (predictor estimator reference)

## Commands

```bash
uv sync                         # install all deps
uv run pytest -v                # run all tests
uv run pytest tests/predictor/  # predictor tests only
uv run pytest tests/server/     # server tests only
uv run ruff check .             # lint
uv run ruff format .            # format
```

## Architecture

1. Client submits task → predictor estimates duration → task enters Redis sorted set (score = predicted_ms)
2. Workers pop lowest-score task (SJF) → execute → record actual time → predictor learns
3. After cold_start_threshold records, predictor auto-promotes heuristic → GradientBoosting
4. Auto-retrain every retrain_every_n new records
