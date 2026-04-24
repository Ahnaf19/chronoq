# tests

All tests run locally with no external services required.

## Current count

Run `uv run pytest --collect-only -q | tail -1` for the current total.
Per-directory counts drift under sprint work; don't hard-code them here or in
other CLAUDE.md files — agents and contributors should re-query when needed.

Per-release totals are recorded in `CHANGELOG.md` at tag time.

## Layout

```
tests/
├── conftest.py              # shared fixtures
├── ranker/                  # schemas, config, storage, features, models, drift, hypothesis, retrain_trigger
├── server/                  # demo-server queue, scheduler, worker, api
├── bench/                   # metrics, traces, simulator, baselines, experiments, plots
└── celery/                  # rolling, scheduler, signals, examples
```

## Conventions

- `asyncio_mode = "auto"` — no `@pytest.mark.asyncio` needed.
- fakeredis: server tests use `FakeRedis(decode_responses=True)`.
- `tmp_path`: SQLite tests use pytest's isolated-dir fixture.
- Mocked `simulate_task`: integration tests patch to `asyncio.sleep(0.01)`.
- Low thresholds: `conftest.py`'s `predictor_config` has `cold_start_threshold=10`, `retrain_every_n=20` for speed.

## Run

```bash
uv run pytest -v                           # All tests
uv run pytest tests/ranker/ -v             # Ranker only
uv run pytest tests/server/ -v             # Demo-server only
uv run pytest tests/bench/ -v             # Bench only
uv run pytest tests/celery/ -v             # Celery only
uv run pytest -k "lambdarank" -v           # LambdaRank tests only
uv run pytest -k "hypothesis" -v          # Property tests only
uv run pytest --cov=chronoq_ranker --cov=chronoq_celery --cov-report=term-missing
```

## Adding tests

- Place per-package: `tests/<pkg>/test_<module>.py`.
- Use `memory_store` and `predictor_config` fixtures from `conftest.py` (the fixture is still named `predictor_config` for backward compat; returns a `RankerConfig` — rename deferred to the next major bump).
- Server tests: create `FakeRedis` + `TaskQueue` per-test or via fixture, not module-level.
- Keep fast: mock `simulate_task`, use `memory://`, use low thresholds.
- `hypothesis` property tests live in `tests/ranker/test_lambdarank_hypothesis.py` (rank-label monotonicity, ρ range, pairwise accuracy range, PSI non-negativity).
