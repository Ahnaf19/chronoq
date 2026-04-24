# chronoq-celery

Celery integration for `chronoq-ranker`. Ships `LearnedScheduler` — a pre-broker gate
with `fifo` / `shadow` / `active` modes that routes tasks in predicted-duration order
without touching the Celery broker.

**Status:** Shipped. `LearnedScheduler`, `TypeStatsTracker`, `attach_signals` in production-ready
state. Examples: `examples/toggle_demo.py` (eager-mode A/B, no Docker) and
`examples/celery-docker/` (Docker Compose A/B stack with Redis + worker + producer).
All v0.2.0 Windows unicode fixes applied.

## Why pre-broker gate?

Celery uses Redis LISTS (`LPUSH`/`BLPOP`) — there is no broker-level "select next task"
hook. `LearnedScheduler` acts as an in-process gate: callers pass an `apply_fn` alongside
the task metadata. In active mode tasks are held in a `heapq` scored by predicted duration
and dispatched in score order via `dispatch_next()`, which is called from `task_success`.

## Layout

```
chronoq_celery/
├── __init__.py         # LearnedScheduler, TypeStatsTracker, attach_signals
├── rolling.py          # TypeStatsTracker — per-type ring buffer (mean/p95/count)
├── scheduler.py        # LearnedScheduler — fifo/shadow/active + heap dispatch
└── signals.py          # attach_signals() — task_prerun/task_success/task_failure wiring
demo.py                 # 200-task Pareto JCT comparison; no chronoq_bench import
examples/
├── toggle_demo.py      # eager-mode A/B demo (CHRONOQ_MODE=fifo|active, no Docker)
├── celery-docker/      # Docker Compose A/B stack (redis + worker + producer + plot)
└── README.md           # run instructions and caveats
```

## Modes

| Mode     | Ranker | apply_fn order | Use when |
|----------|--------|----------------|----------|
| `fifo`   | never instantiated | immediate (arrival) | trust escape hatch |
| `shadow` | instantiated, scores logged | immediate (arrival) | validation |
| `active` | instantiated + heap dispatch | score order | production |

## Ownership

- `rolling.py`, `scheduler.py`, `signals.py`, `__init__.py` → `senior-backend-dev`
- Any new public interface → notify `library-architect`
- Tests → `qa-validator` for gate-running; `senior-backend-dev` for design

## Scoring path

The scoring path replicates `LambdaRankScheduler._score()` from
`bench/chronoq_bench/experiments/jct_vs_load.py` — do NOT call `predict_scores()` as it
strips per-candidate context:

```python
mean, p95, count = stats_tracker.snapshot(task_type)
ctx = QueueContext(recent_mean_ms_this_type=mean, ...)
features = extractor.extract(candidate, context=ctx)
score = estimator.predict_batch([features])[0][0]
```

`recent_mean_ms_this_type` carries ~80% of ranking signal (from ablation experiment).

## Handoff context

- `task_success` → `record_completion()` → `TypeStatsTracker.record()` + `ranker.record()` → `dispatch_next()`
- `task_prerun` → `record_start()` writes `start_ms = time.monotonic() * 1000`
- `task_failure` → `cleanup_registry()` only; `ranker.record()` is NOT called for failed tasks
- Seed `TypeStatsTracker` from training type means before active benchmark to avoid cold start
- `mode="fifo"` → `self._ranker is None`; assert in tests via `test_fifo_ranker_never_instantiated`

## Testing

```bash
uv run pytest tests/celery/ -v
```

No Docker, no real Redis, no real broker. Scheduler tests use fresh in-memory rankers.
Signal tests use mocks. All tests pass with no external services.

## Rules

- Run `/boundary-check` after any change to `integrations/celery/` — `grep -r "celery" ranker/` must return nothing.
- `mode="fifo"` MUST short-circuit before any ranker call — tested with `test_fifo_ranker_never_instantiated`.
- No new dependencies in `chronoq-ranker` — all framework deps belong here.
- `attach_signals()` uses TYPE_CHECKING imports for `Celery` and `LearnedScheduler` — do not move to runtime imports.
- **task_id uniqueness contract**: `submit()` raises `ValueError("task_id already registered: ...")` on duplicate task_id. Callers must pass unique task_ids per scheduler instance lifetime.
- **task_revoked wired**: `attach_signals()` wires `task_revoked` → `cleanup_registry(task_id)`. Without this, cancelled tasks leak registry entries forever.
- **record_completion passes queue context**: passes `metadata={"recent_mean_ms_this_type": ..., "queue_depth": ..., ...}` to `ranker.record()` via `TypeStatsTracker.snapshot()`. This eliminates train-serve feature skew (10/15 features were 0.0 before this fix).
