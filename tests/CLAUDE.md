# tests

185 tests: 113 ranker (`tests/ranker/`) + 24 demo-server (`tests/server/`) + 43 bench (`tests/bench/`) + 1 bench stub + 1 celery stub (2 stubs remain for Chunk 3+). No external services required.

## Layout

```
tests/
├── conftest.py              # Shared fixtures: memory_store, predictor_config (low thresholds)
├── ranker/                  # 113 — schemas, config, storage, features, heuristic, gradient, orchestrator, integration, compat shims, predict_scores, lambdarank, oracle, drift, hypothesis
├── server/                  # 24 — queue, scheduler, worker, api/*, integration
├── bench/                   # 43 — test_metrics (15), test_traces (9), test_simulator (12), test_baselines (5), test_stub (1) + Chunk 2
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
uv run pytest -v                           # All 185
uv run pytest tests/ranker/ -v             # Ranker only (113)
uv run pytest tests/server/ -v             # Demo-server only (24)
uv run pytest tests/bench/ -v             # Bench only (43)
uv run pytest -k "lambdarank" -v           # LambdaRank tests only
uv run pytest -k "hypothesis" -v          # Property tests only
uv run pytest --cov=chronoq_ranker --cov=chronoq_demo_server
```

## Adding tests

- Place per-package: `tests/<pkg>/test_<module>.py`.
- Use `memory_store` and `predictor_config` fixtures from `conftest.py` (the fixture is still named `predictor_config` for backward compat; returns a `RankerConfig` — rename deferred to the next major bump).
- Server tests: create `FakeRedis` + `TaskQueue` per-test or via fixture, not module-level.
- Keep fast: mock `simulate_task`, use `memory://`, use low thresholds.
- Chunk 1+: `hypothesis` property tests live in `tests/ranker/test_lambdarank_hypothesis.py` (8 tests covering rank-label monotonicity, ρ range, pairwise accuracy range, PSI non-negativity).
