# tests

73 tests: 47 predictor (in `tests/predictor/`, will move to `tests/ranker/` in Chunk 1) + 24 server (`tests/server/`) + 1 bench stub + 1 celery stub. No external services required.

## Layout

```
tests/
├── conftest.py          # Shared fixtures: memory_store, predictor_config (low thresholds)
├── predictor/           # 47 — schemas, config, storage, features, heuristic, gradient, orchestrator, integration
├── server/              # 24 — queue, scheduler, worker, api/*, integration
├── bench/               # 1 stub (populates in Chunk 2)
└── celery/              # 1 stub (populates in Chunk 3)
```

## Conventions

- `asyncio_mode = "auto"` — no `@pytest.mark.asyncio` needed.
- fakeredis: server tests use `FakeRedis(decode_responses=True)`.
- `tmp_path`: SQLite tests use pytest's isolated-dir fixture.
- Mocked `simulate_task`: integration tests patch to `asyncio.sleep(0.01)`.
- Low thresholds: `conftest.py`'s `predictor_config` has `cold_start_threshold=10`, `retrain_every_n=20` for speed.

## Run

```bash
uv run pytest -v                           # All
uv run pytest tests/predictor/ -v          # Predictor only
uv run pytest tests/server/ -v             # Server only
uv run pytest -k "test_predictor" -v       # By pattern
uv run pytest --cov=chronoq_ranker --cov=chronoq_demo_server
```

## Adding tests

- Place per-package: `tests/<pkg>/test_<module>.py`.
- Use `memory_store` and `predictor_config` fixtures from `conftest.py`.
- Server tests: create `FakeRedis` + `TaskQueue` per-test or via fixture, not module-level.
- Keep fast: mock `simulate_task`, use `memory://`, use low thresholds.
- Chunk 1+: add property tests via `hypothesis` for rank invariance.
