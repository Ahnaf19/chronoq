# chronoq-celery

> Learning-to-rank scheduling for Celery. Replace FIFO with an online LambdaRank. 2-line drop-in, three safety modes.

Pre-broker gate for Celery that re-orders pending tasks by predicted duration, shortest first. Works alongside [`chronoq-ranker`](https://pypi.org/project/chronoq-ranker/) — the ranker scores tasks based on job telemetry; this package wires that scoring into Celery's task lifecycle via signals.

## Install

```bash
pip install chronoq-celery
```

## 30-second try

```python
from chronoq_celery import LearnedScheduler, attach_signals
from celery import Celery

app = Celery("myapp", broker="redis://localhost:6379/0")
scheduler = LearnedScheduler(mode="active")  # or "shadow" / "fifo"
attach_signals(app, scheduler)
```

That is the entire integration. `attach_signals` wires `task_prerun`, `task_success`, `task_failure`, and `task_revoked` so the ranker records telemetry and triggers dispatch automatically.

## Three modes, one flag

| Mode     | What it does |
|---|---|
| `fifo`   | No-op. Tasks dispatch in arrival order. Ranker is never instantiated. Use as a kill-switch or A/B baseline. |
| `shadow` | Ranker scores every task and logs the score; dispatch order is unchanged vs FIFO. Zero behavioral difference in production — safe to deploy immediately and measure the potential win before switching. |
| `active` | Tasks are held in an in-process min-heap scored by predicted duration and dispatched in score order via `dispatch_next()` on task completion. |

## Shadow → active rollout pattern

Start with `shadow` mode to validate the ranker's scores against your workload before committing to reordering:

```python
# Week 1: deploy with shadow mode — zero dispatch change, score logging only
scheduler = LearnedScheduler(mode="shadow")
attach_signals(app, scheduler)

# From your logs, compare predicted score distribution against actual durations.
# When the ranker's rank correlation looks solid, flip the flag:

# Week 2+: flip to active — same code, one string change
scheduler = LearnedScheduler(mode="active")
attach_signals(app, scheduler)
```

The ranker accumulates telemetry in both modes, so by the time you flip to `active` it has already trained on real traffic.

## How it works

Celery's broker uses Redis LISTS (`LPUSH`/`BLPOP`) with no broker-level "select next task" hook. `LearnedScheduler` acts as a pre-broker gate: in `active` mode, callers pass an `apply_fn` (the closure that calls `task.apply_async(...)`) alongside the task metadata. Tasks are held in an in-process `heapq` and dispatched in score order when a worker slot opens, signaled by `task_success`.

The scoring path computes a `QueueContext` with live per-type rolling statistics (`TypeStatsTracker`) and passes it to the `FeatureExtractor`. The dominant feature — `recent_mean_ms_this_type` — carries approximately 80% of the ranking signal on typical workloads (from ablation experiments on the synthetic Pareto and BurstGPT traces).

## API surface

```python
LearnedScheduler(
    mode="fifo" | "shadow" | "active",
    ranker=None,           # pre-initialised TaskRanker; created internally if None
    ranker_config=None,    # RankerConfig passed to TaskRanker() when ranker is None
    stats_tracker=None,    # TypeStatsTracker; created internally if None
    window=100,            # ring-buffer size for internal TypeStatsTracker
)

attach_signals(app, scheduler)
# wires: task_prerun → record_start
#        task_success → record_completion + dispatch_next
#        task_failure → cleanup_registry
#        task_revoked → cleanup_registry

TypeStatsTracker(window=100)
# .record(task_type, actual_ms)
# .snapshot(task_type) → (mean, p95, count)
# .seed(means_dict)     # cold-start pre-warm from historical data
```

## Seeding TypeStatsTracker from historical data

On first deploy, the ranker has no telemetry. Seed `TypeStatsTracker` with historical per-type means to avoid cold-start degradation:

```python
from chronoq_celery import LearnedScheduler, TypeStatsTracker, attach_signals

stats = TypeStatsTracker()
stats.seed({
    "resize":    312.0,   # historical mean ms per type
    "transcode": 1780.0,
    "analyze":   95.0,
})

scheduler = LearnedScheduler(mode="active", stats_tracker=stats)
attach_signals(app, scheduler)
```

## Examples in the repo

- `integrations/celery/examples/toggle_demo.py` — eager-mode FIFO vs active comparison using `task_always_eager=True`; runs the real Celery API with no Docker or Redis required
- `integrations/celery/examples/celery-docker/` — Docker Compose A/B stack with real Redis, worker, producer, and wall-clock JCT measurement

## Evidence

On the synthetic Pareto benchmark: **+55% mean JCT improvement** in `active` mode vs `fifo` on a 200-task workload (full `demo.py` run, `n_train=800`). The ranker pre-trains on synthetic oracle records before the eval batch, matching the conditions of the benchmark harness. Full methodology in the monorepo's [BENCHMARKS.md](https://github.com/Ahnaf19/chronoq/blob/main/docs/v2/BENCHMARKS.md).

## Honest limitations

- **p99 starvation at ρ ≥ 0.8**: SJF-family tradeoff — short-first bias indefinitely delays long jobs at the tail. Pair with Celery's existing rate-limiting or priority-decay knobs at the task level. An aging-aware scheduler option is planned for v0.3.0.
- **`mode="active"` requires Celery 5.4+**.
- **Pre-1.0 API**: breaking changes are allowed in minor-version bumps with a deprecation shim and a CHANGELOG "Breaking" entry.
- **In-process heap**: the `active` mode heap lives in a single Celery worker process. In multi-process Celery deployments each worker has its own heap; cross-worker coordination is out of scope for this package.

## Links

- Monorepo: https://github.com/Ahnaf19/chronoq
- Ranker library: https://pypi.org/project/chronoq-ranker/
- Full benchmarks: https://github.com/Ahnaf19/chronoq/blob/main/docs/v2/BENCHMARKS.md
- MIT license
