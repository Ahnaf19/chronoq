---
status: current
last-synced-to-plan: 2026-04-22
---

# Chronoq Integrations

How to wire `chronoq-ranker` into your job queue. Currently supported: **Celery**. Planned: Hatchet sidecar (optional, post-v0.2.0), vLLM plugin (deferred until GPU budget).

## Celery — `chronoq-celery`

### Install

```bash
pip install chronoq-celery
```

Or with uv:

```bash
uv add chronoq-celery
```

### 3-step quickstart

**Step 1 — create a scheduler:**

```python
from chronoq_celery import LearnedScheduler, TypeStatsTracker, attach_signals

scheduler = LearnedScheduler(mode="active")   # or "shadow" or "fifo"
```

**Step 2 — attach signals to your Celery app:**

```python
from celery import Celery

app = Celery("myapp", broker="redis://localhost:6379/0")
attach_signals(app, scheduler)
```

**Step 3 — submit tasks through the scheduler:**

```python
def my_task_apply_fn():
    my_task.apply_async(kwargs={"task_type": "resize", "payload_size": 1024})

task_id = scheduler.submit(
    task_type="resize",
    payload_size=1024,
    apply_fn=my_task_apply_fn,
)
```

That's it. In `active` mode, tasks are held in an in-process heap scored by predicted duration and dispatched in score order as workers free up.

---

### Modes

| Mode | What happens | Use case |
|------|-------------|----------|
| `fifo` | `apply_fn()` called immediately; ranker never loaded | Trust escape hatch; zero overhead |
| `shadow` | Task is scored and logged; dispatched in arrival order | Validate predictions before enabling |
| `active` | Tasks held in heap; dispatched in score order | Production use |

Switch modes at runtime by changing `scheduler.mode` — or create separate schedulers per queue.

---

### Architecture

Celery uses Redis LISTS (`LPUSH`/`BLPOP`) — there is no broker-level "select next task" hook. `LearnedScheduler` is a **pre-broker gate**: your code calls `submit()` instead of calling Celery's `apply_async()` directly. In `active` mode:

```
submit(task_type, payload_size, apply_fn, task_id)
    │
    └── score → push heap
                    │
         task_success signal ──► record_completion()
                                 TypeStatsTracker.record()
                                 ranker.record()
                                 dispatch_next() ──► pop heap → apply_fn()
```

`dispatch_next()` is called automatically from the `task_success` signal — no manual bookkeeping needed after `attach_signals()`.

---

### TypeStatsTracker — live rolling statistics

The scheduler uses a `TypeStatsTracker` to compute `recent_mean_ms_this_type` at scoring time. This feature carries ~80% of the LambdaRank model's ranking signal (from the ablation experiment — see `docs/v2/BENCHMARKS.md`). The tracker updates automatically as tasks complete.

**Cold start:** on first deploy, the tracker has no observations. Seed it from historical data to avoid cold-start ranking:

```python
from chronoq_celery import TypeStatsTracker

stats = TypeStatsTracker(window=100)
stats.seed({
    "resize":    57.0,
    "transcode": 3220.0,
    "ocr":       810.0,
})
scheduler = LearnedScheduler(mode="active", stats_tracker=stats)
```

---

### Training the ranker

`LearnedScheduler` ships with a cold-start heuristic that doesn't require training. For full LambdaRank ranking (the model that gives +32% mean JCT over FCFS):

```python
from chronoq_ranker import TaskRanker
from chronoq_ranker.config import RankerConfig

ranker = TaskRanker(
    config=RankerConfig(storage_uri="sqlite:///ranker.db"),
)
# Feed historical completions manually, or let attach_signals() accumulate them live.
# Auto-retrain triggers when store.count_since(version) >= config.retrain_every_n (default 100).
scheduler = LearnedScheduler(mode="active", ranker=ranker)
```

See `ranker/CLAUDE.md` for the full LambdaRank training pipeline.

---

### Demo

Run the 200-task JCT comparison locally (no Docker, no Redis):

```bash
uv run python integrations/celery/demo.py
```

Expected output:

```
chronoq-celery demo — fifo vs active, 200-task Pareto workload

Training ranker on 800 jobs...
  Model:   lambdarank
  Samples: 800

Mode             mean_jct        p99_jct
----------------------------------------
fifo             155819ms       280521ms
active            70046ms       276153ms

Mean JCT improvement: +55.0%  (target: ≥15%)
P99  JCT improvement: +1.6%

EXIT CRITERION: mean JCT improvement ≥15% — PASS
```

The mean JCT improvement is consistently ≥15% on Pareto-distributed workloads (5 task types, 57ms–3220ms mean durations, σ=0.6). P99 improvement is low because p99 corresponds to the longest tasks — in sequential execution, long tasks finish last regardless of ordering.

---

### Limitations and scope

- **Single-process gate only.** Multiple Celery workers calling `submit()` on different
  scheduler instances won't share the heap. For multi-process deployments, you need a shared priority queue (e.g., Redis sorted set) — not yet implemented.
- **No broker-level integration.** Tasks already in Celery's broker queue are not re-ranked.
  `LearnedScheduler` only controls tasks submitted through it.
- **Eager mode (testing).** `task_always_eager=True` runs tasks synchronously. Signals still
  fire, but the signal chain may recurse in active mode. For unit tests, test ordering logic via mocked `_score()` (see `tests/celery/test_scheduler.py`).

---

## Hatchet (planned)

Hatchet uses static priority 1–5. A sidecar pattern can inject Chronoq scores as priority values before task submission. Planned for v0.3.0 if time permits.

## vLLM (deferred)

vLLM v0.11+ has a pluggable scheduler API. A `chronoq-vllm` plugin is planned but deferred until GPU budget is available. See [`hao-ai-lab/vllm-ltr`](https://github.com/hao-ai-lab/vllm-ltr) for the prior art this will build on.
