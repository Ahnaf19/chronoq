# chronoq-celery examples

## toggle_demo.py — FIFO vs active scheduling on real Celery tasks

`toggle_demo.py` demonstrates chronoq's before/after scheduling improvement using
the **real Celery API** (`attach_signals`-equivalent wiring, `LearnedScheduler.submit`,
`dispatch_next`), all running in-process with no broker or Docker required.

### What this demo shows

- **FIFO mode**: tasks execute in arrival order. Short tasks can get stuck behind long ones.
- **Active mode**: tasks are held in a priority heap, scored by the pre-trained LambdaRank
  ranker, and dispatched shortest-first. Short tasks complete early; mean JCT drops.

Both modes use the same 50 eval tasks and the same pre-trained ranker. The ranker is
warm-started on 500 synthetic records (5 task types: resize, analyze, compress, encode,
transcode) so there is no cold-start penalty in the comparison.

The JCT metric is **cumulative sequential JCT**: time from batch-start to each task's
completion. In a single-worker sequential system, SJF ordering (active mode) minimises
mean JCT because short tasks finish early, reducing average wait.

### How to run

```bash
# Default: runs both fifo and active side-by-side
uv run python integrations/celery/examples/toggle_demo.py

# Single mode
CHRONOQ_MODE=fifo   uv run python integrations/celery/examples/toggle_demo.py
CHRONOQ_MODE=active uv run python integrations/celery/examples/toggle_demo.py
```

### Expected output

```
chronoq-celery eager demo — fifo vs active on real Celery API

Pre-training ranker on 500 synthetic records...
  Training complete.

Running mode='fifo' on 50 eval tasks...
  Completed 50/50 tasks captured.
Running mode='active' on 50 eval tasks...
  Completed 50/50 tasks captured.

Mode        tasks    mean_jct_ms     p99_jct_ms
------------------------------------------------
fifo           50       3241.8ms       6733.8ms
active         50       1424.4ms       5937.2ms

Mean JCT improvement (active vs fifo): +56.1%  (target: ≥20%)
EXIT CRITERION: ≥20% mean JCT improvement — PASS
```

Numbers vary slightly run-to-run (jitter in `time.sleep`), but mean JCT improvement
is consistently ≥20% on the 50-task workload.

Total runtime: ~15 seconds on a laptop.

### Caveats

**Eager mode validates API flow and ranking decisions, not wall-clock throughput.**

`task_always_eager=True` executes tasks synchronously in the caller's process — there
is no real broker, no worker pool, and no concurrency. What the demo proves:

1. `LearnedScheduler.submit()` and `dispatch_next()` wire correctly to Celery signals.
2. `task_prerun` → `record_start`, `task_success` → `record_completion` → `dispatch_next`
   produce a correct scheduling chain.
3. The pre-trained ranker produces a score order that matches SJF, yielding measurable
   mean JCT improvement even in a single-threaded context.

For wall-clock evidence with a real broker and multi-worker concurrency, see
`examples/celery-docker/` (Track A2).

### Signal wiring note

In a production Celery app, `attach_signals(app, scheduler)` is called once at
module-import time. The local handler closures then live for the process lifetime and
Celery's default weak-reference signal registration works fine.

In this demo script the handlers are registered inside a function scope. To prevent
the closures from being garbage-collected before the signals fire, the demo uses
`weak=False` and stores the handlers in a `_SignalHandlers` instance. This is a
demo/testing pattern — production code uses `attach_signals` directly.
