# tests

85 tests: 59 ranker (`tests/ranker/`: 47 original + 4 compat shims + 8 predict_scores) + 24 server (`tests/server/`) + 1 bench stub + 1 celery stub. No external services required.

## Layout

```
tests/
├── conftest.py              # Shared fixtures: memory_store, predictor_config (low thresholds)
├── ranker/                  # 59 — schemas, config, storage, features, heuristic, gradient, orchestrator, integration, compat shims, predict_scores
├── server/                  # 24 — queue, scheduler, worker, api/*, integration
├── bench/                   # 1 stub (populates in Chunk 2)
└── celery/                  # 1 stub (populates in Chunk 3)
```

## Conventions

- `asyncio_mode = "auto"` — no `@pytest.mark.asyncio` needed.
- fakeredis: server tests use `FakeRedis(decode_responses=True)`.
- `tmp_path`: SQLite tests use pytest's isolated-dir fixture.
- Mocked `simulate_task`: integration tests patch to `asyncio.sleep(0.01)`.
- Low thresholds: `conftest.py`'s `predictor_config` has `cold_start_threshold=10`, `retrain_every_n=20` for speed.

## Run

```bash
uv run pytest -v                           # All 85
uv run pytest tests/ranker/ -v             # Ranker only (59)
uv run pytest tests/server/ -v             # Server only (24)
uv run pytest -k "predict_scores" -v       # By pattern
uv run pytest --cov=chronoq_ranker --cov=chronoq_demo_server
```

## Adding tests

- Place per-package: `tests/<pkg>/test_<module>.py`.
- Use `memory_store` and `predictor_config` fixtures from `conftest.py` (the fixture is still named `predictor_config` for backward compat; returns a `RankerConfig` — rename deferred to the next major bump).
- Server tests: create `FakeRedis` + `TaskQueue` per-test or via fixture, not module-level.
- Keep fast: mock `simulate_task`, use `memory://`, use low thresholds.
- Chunk 1+: add property tests via `hypothesis` for rank invariance.
