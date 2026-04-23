"""chronoq-celery eager-mode demo — real Celery API, no Docker required.

Demonstrates FIFO vs active scheduling on a 50-task workload using the real
``LearnedScheduler.submit`` / ``dispatch_next`` / ``record_start`` /
``record_completion`` flow with ``task_always_eager=True`` (tasks execute
synchronously, in-process).

Signal wiring note: this demo wires Celery signals with ``weak=False`` (strong
references) so the local handler closures are not garbage collected inside a
short-lived function scope. In a production Celery app the same signals would
be wired at module-import time (not inside a function) and weak refs work fine.
See ``attach_signals()`` in ``chronoq_celery.signals`` for the production
pattern — this demo shows equivalent wiring that is safe in a script context.

Usage::

    # Run both modes side-by-side (default)
    uv run python integrations/celery/examples/toggle_demo.py

    # Single-mode via env var
    CHRONOQ_MODE=fifo   uv run python integrations/celery/examples/toggle_demo.py
    CHRONOQ_MODE=active uv run python integrations/celery/examples/toggle_demo.py

No chronoq_bench import — inline generation keeps the PyPI dep graph clean.
"""

from __future__ import annotations

import os
import random
import statistics
import time
import uuid
from collections import defaultdict
from typing import Any

import celery
from celery import signals as celery_signals
from chronoq_celery import LearnedScheduler, TypeStatsTracker
from chronoq_ranker import TaskRanker
from chronoq_ranker.config import RankerConfig
from chronoq_ranker.schemas import TaskRecord

# ---------------------------------------------------------------------------
# Workload profile — mirrors bench synthetic trace (5 task types)
# ---------------------------------------------------------------------------

_TASK_PROFILES: dict[str, dict[str, Any]] = {
    "resize": {"base_ms": 5.0, "jitter": (0.8, 1.2)},
    "analyze": {"base_ms": 20.0, "jitter": (0.8, 1.2)},
    "compress": {"base_ms": 35.0, "jitter": (0.8, 1.2)},
    "encode": {"base_ms": 90.0, "jitter": (0.8, 1.2)},
    "transcode": {"base_ms": 400.0, "jitter": (0.8, 1.2)},
}

_N_TRAIN = 500
_N_EVAL = 50
_GROUP_SIZE = 20
_SEED = 42

# Payload-size scaling factor (larger payload → slightly longer task)
_PAYLOAD_SCALE = 0.0002


# ---------------------------------------------------------------------------
# Celery app — eager mode (no broker required)
# ---------------------------------------------------------------------------


def _make_celery_app() -> celery.Celery:
    """Create a Celery app configured for in-process eager execution."""
    app = celery.Celery("chronoq_demo")
    app.conf.task_always_eager = True
    app.conf.task_store_eager_result = True
    app.conf.task_eager_propagates = True

    @app.task(name="resize")
    def resize(task_type: str = "resize", payload_size: int = 1000) -> str:
        profile = _TASK_PROFILES[task_type]
        lo, hi = profile["jitter"]
        real_ms = profile["base_ms"] * random.uniform(lo, hi) + payload_size * _PAYLOAD_SCALE
        time.sleep(real_ms / 1000.0)
        return task_type

    @app.task(name="analyze")
    def analyze(task_type: str = "analyze", payload_size: int = 1000) -> str:
        profile = _TASK_PROFILES[task_type]
        lo, hi = profile["jitter"]
        real_ms = profile["base_ms"] * random.uniform(lo, hi) + payload_size * _PAYLOAD_SCALE
        time.sleep(real_ms / 1000.0)
        return task_type

    @app.task(name="compress")
    def compress(task_type: str = "compress", payload_size: int = 1000) -> str:
        profile = _TASK_PROFILES[task_type]
        lo, hi = profile["jitter"]
        real_ms = profile["base_ms"] * random.uniform(lo, hi) + payload_size * _PAYLOAD_SCALE
        time.sleep(real_ms / 1000.0)
        return task_type

    @app.task(name="encode")
    def encode(task_type: str = "encode", payload_size: int = 1000) -> str:
        profile = _TASK_PROFILES[task_type]
        lo, hi = profile["jitter"]
        real_ms = profile["base_ms"] * random.uniform(lo, hi) + payload_size * _PAYLOAD_SCALE
        time.sleep(real_ms / 1000.0)
        return task_type

    @app.task(name="transcode")
    def transcode(task_type: str = "transcode", payload_size: int = 1000) -> str:
        profile = _TASK_PROFILES[task_type]
        lo, hi = profile["jitter"]
        real_ms = profile["base_ms"] * random.uniform(lo, hi) + payload_size * _PAYLOAD_SCALE
        time.sleep(real_ms / 1000.0)
        return task_type

    app._task_map = {  # type: ignore[attr-defined]
        "resize": resize,
        "analyze": analyze,
        "compress": compress,
        "encode": encode,
        "transcode": transcode,
    }
    return app


# ---------------------------------------------------------------------------
# Training helpers (adapted from integrations/celery/demo.py)
# ---------------------------------------------------------------------------


def _generate_training_jobs(n: int, seed: int) -> list[dict[str, Any]]:
    """Generate synthetic training records for pre-warming the ranker.

    Args:
        n:    Number of training jobs to generate.
        seed: Random seed for reproducibility.

    Returns:
        List of job dicts with keys: task_type, payload_size, true_ms.
    """
    rng = random.Random(seed)
    task_types = list(_TASK_PROFILES.keys())
    jobs = []
    for _ in range(n):
        tt = rng.choice(task_types)
        profile = _TASK_PROFILES[tt]
        lo, hi = profile["jitter"]
        payload_size = int(rng.lognormvariate(7.0, 1.5))
        true_ms = profile["base_ms"] * rng.uniform(lo, hi) + payload_size * _PAYLOAD_SCALE
        jobs.append({"task_type": tt, "payload_size": payload_size, "true_ms": true_ms})
    return jobs


def _compute_type_stats(
    jobs: list[dict[str, Any]],
) -> tuple[dict[str, float], dict[str, float], dict[str, int]]:
    """Compute per-type mean, pseudo-p95, and count from a job list.

    Args:
        jobs: List of job dicts with task_type and true_ms keys.

    Returns:
        Tuple of (means, p95s, counts) dicts keyed by task_type.
    """
    buckets: dict[str, list[float]] = defaultdict(list)
    for j in jobs:
        buckets[j["task_type"]].append(j["true_ms"])
    means: dict[str, float] = {}
    p95s: dict[str, float] = {}
    counts: dict[str, int] = {}
    for tt, vals in buckets.items():
        sorted_vals = sorted(vals)
        means[tt] = sum(vals) / len(vals)
        idx = max(0, int(len(sorted_vals) * 0.95) - 1)
        p95s[tt] = sorted_vals[idx]
        counts[tt] = len(vals)
    return means, p95s, counts


def _train_ranker(
    jobs: list[dict[str, Any]],
) -> tuple[TaskRanker, dict[str, float], dict[str, float], dict[str, int]]:
    """Pre-train a LambdaRank ranker on synthetic oracle records.

    Mirrors ``integrations/celery/demo.py:_train_ranker`` adapted for stdlib random.

    Args:
        jobs: Training job list from _generate_training_jobs().

    Returns:
        Tuple of (ranker, type_means, type_p95s, type_counts).
    """
    means, p95s, counts = _compute_type_stats(jobs)

    config = RankerConfig(
        cold_start_threshold=50,
        retrain_every_n=len(jobs) + 1,  # prevent auto-retrain during record saves
        min_groups=5,
        storage_uri="memory://",
    )
    ranker = TaskRanker(config=config)

    for batch_start in range(0, len(jobs), _GROUP_SIZE):
        batch = jobs[batch_start : batch_start + _GROUP_SIZE]
        group_id = f"train_{batch_start // _GROUP_SIZE}"
        for job in batch:
            ranker._store.save(  # type: ignore[attr-defined]
                TaskRecord(
                    task_type=job["task_type"],
                    payload_size=job["payload_size"],
                    actual_ms=job["true_ms"],
                    group_id=group_id,
                    metadata={
                        "recent_mean_ms_this_type": means.get(job["task_type"], 0.0),
                        "recent_p95_ms_this_type": p95s.get(job["task_type"], 0.0),
                        "recent_count_this_type": float(counts.get(job["task_type"], 0)),
                    },
                )
            )

    ranker.retrain()
    return ranker, means, p95s, counts


# ---------------------------------------------------------------------------
# Eval-job generation
# ---------------------------------------------------------------------------


def _generate_eval_jobs(n: int, seed: int) -> list[dict[str, Any]]:
    """Generate evaluation jobs with varied task types and payload sizes.

    Args:
        n:    Number of eval jobs.
        seed: Random seed (use a different seed from training to avoid overlap).

    Returns:
        List of job dicts with task_type and payload_size.
    """
    rng = random.Random(seed + 1)
    task_types = list(_TASK_PROFILES.keys())
    jobs = []
    for _ in range(n):
        tt = rng.choice(task_types)
        payload_size = int(rng.lognormvariate(7.0, 1.5))
        jobs.append({"task_type": tt, "payload_size": payload_size})
    return jobs


# ---------------------------------------------------------------------------
# Single-mode run — real Celery API via task_always_eager
# ---------------------------------------------------------------------------


class _SignalHandlers:
    """Holds strong references to Celery signal handlers for a single demo run.

    In a production Celery app, signal handlers are wired at module-import time
    and live for the process lifetime. In a demo script running inside a function
    scope, the handler closures would be garbage-collected if stored only as weak
    references (Celery's default). This class holds the strong refs.

    See ``chronoq_celery.signals.attach_signals`` for the production pattern —
    this class provides equivalent wiring safe for script/test contexts.
    """

    def __init__(self, scheduler: LearnedScheduler) -> None:
        self._scheduler = scheduler
        self._submit_times: dict[str, float] = {}
        self._complete_times: dict[str, float] = {}

        # Named methods prevent GC — assigned before .connect() calls
        self._on_prerun = self._make_prerun_handler()
        self._on_success = self._make_success_handler()
        self._on_failure = self._make_failure_handler()
        self._on_revoked = self._make_revoked_handler()

        celery_signals.task_prerun.connect(self._on_prerun, weak=False)
        celery_signals.task_success.connect(self._on_success, weak=False)
        celery_signals.task_failure.connect(self._on_failure, weak=False)
        celery_signals.task_revoked.connect(self._on_revoked, weak=False)

    def _make_prerun_handler(self):  # type: ignore[return]
        scheduler = self._scheduler

        def on_task_prerun(sender=None, task_id=None, task=None, args=None, kwargs=None, **extra):
            task_type = (kwargs or {}).get("task_type", getattr(sender, "name", "unknown"))
            payload_size = int((kwargs or {}).get("payload_size", 0))
            if task_id:
                scheduler.record_start(task_id, task_type, payload_size)

        return on_task_prerun

    def _make_success_handler(self):  # type: ignore[return]
        scheduler = self._scheduler
        complete_times = self._complete_times

        def on_task_success(sender=None, result=None, **extra):
            task_id = getattr(sender.request, "id", None) if sender else None
            task_type = getattr(sender, "name", "unknown") if sender else "unknown"
            payload_size = int(getattr(sender.request, "kwargs", {}).get("payload_size", 0))
            if task_id:
                complete_times[task_id] = time.monotonic()
                scheduler.record_completion(task_id, task_type, payload_size)
            if scheduler.mode == "active":
                scheduler.dispatch_next()

        return on_task_success

    def _make_failure_handler(self):  # type: ignore[return]
        scheduler = self._scheduler

        def on_task_failure(sender=None, task_id=None, **extra):
            if task_id:
                scheduler.cleanup_registry(task_id)

        return on_task_failure

    def _make_revoked_handler(self):  # type: ignore[return]
        scheduler = self._scheduler

        def on_task_revoked(sender=None, request=None, **extra):
            task_id = getattr(request, "id", None) if request else None
            if task_id:
                scheduler.cleanup_registry(task_id)

        return on_task_revoked

    def disconnect(self) -> None:
        """Unregister all signal handlers for this run."""
        celery_signals.task_prerun.disconnect(self._on_prerun)
        celery_signals.task_success.disconnect(self._on_success)
        celery_signals.task_failure.disconnect(self._on_failure)
        celery_signals.task_revoked.disconnect(self._on_revoked)


def _run_mode(
    mode: str,
    eval_jobs: list[dict[str, Any]],
    ranker: TaskRanker,
    type_means: dict[str, float],
) -> list[float]:
    """Execute a batch of eval jobs under the given scheduler mode.

    Uses ``task_always_eager=True`` so tasks run synchronously in-process.

    JCT is measured as time-since-batch-start to completion (cumulative sequential
    ordering metric), not per-task submit-to-completion. This mirrors the demo.py
    model: in a single-worker system, earlier tasks in the execution order have lower
    JCT and later tasks carry higher JCT. SJF ordering (active mode) minimises mean
    JCT over all tasks because short jobs complete early, reducing average wait.

    In **active** mode, all tasks are submitted to the heap first, then the first
    task is dispatched manually. Each subsequent task_success signal triggers
    ``dispatch_next()`` — producing a fully scheduler-driven execution order even in
    synchronous eager mode.

    In **fifo** and **shadow** modes, ``submit()`` calls ``apply_fn`` immediately,
    executing tasks in arrival order.

    Args:
        mode:       "fifo", "shadow", or "active".
        eval_jobs:  List of job dicts with task_type and payload_size.
        ranker:     Pre-trained TaskRanker (ignored in fifo mode).
        type_means: Per-type means for TypeStatsTracker cold-start seeding.

    Returns:
        List of per-task JCT values in milliseconds (one per completed task),
        measured from batch start to task completion.
    """
    app = _make_celery_app()
    task_map = app._task_map  # type: ignore[attr-defined]

    stats = TypeStatsTracker()
    stats.seed(type_means)

    scheduler = LearnedScheduler(mode=mode, ranker=ranker, stats_tracker=stats)
    handlers = _SignalHandlers(scheduler)

    # Batch start time: all JCTs are relative to this moment
    t0 = time.monotonic()
    # Submit-order list so we can match IDs to eval_jobs
    ordered_tids: list[str] = []

    try:
        if mode == "active":
            # Submit all tasks to heap first (apply_fn held, not called yet)
            for job in eval_jobs:
                tid = str(uuid.uuid4())
                ordered_tids.append(tid)
                tt = job["task_type"]
                ps = job["payload_size"]
                fn = task_map[tt]
                # Closure: capture each loop variable explicitly with default args
                scheduler.submit(
                    task_type=tt,
                    payload_size=ps,
                    apply_fn=lambda f=fn, t=tt, p=ps, i=tid: f.apply_async(
                        kwargs={"task_type": t, "payload_size": p},
                        task_id=i,
                    ),
                    task_id=tid,
                )

            # Kick off chain: task_success → dispatch_next() → next task → ...
            scheduler.dispatch_next()

        else:
            # fifo / shadow: apply_fn is called immediately inside submit()
            for job in eval_jobs:
                tid = str(uuid.uuid4())
                ordered_tids.append(tid)
                tt = job["task_type"]
                ps = job["payload_size"]
                fn = task_map[tt]
                scheduler.submit(
                    task_type=tt,
                    payload_size=ps,
                    apply_fn=lambda f=fn, t=tt, p=ps, i=tid: f.apply_async(
                        kwargs={"task_type": t, "payload_size": p},
                        task_id=i,
                    ),
                    task_id=tid,
                )

    finally:
        handlers.disconnect()

    complete_times = handlers._complete_times
    # JCT = time from batch start to each task's completion
    jcts_ms = [(complete_times[tid] - t0) * 1000.0 for tid in ordered_tids if tid in complete_times]
    return jcts_ms


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Run FIFO vs active comparison and print a side-by-side JCT table.

    Respects ``CHRONOQ_MODE`` env var:
    - ``fifo`` or ``shadow``: runs that mode only.
    - ``active``: runs active mode only.
    - Unset (default): runs both ``fifo`` and ``active`` for comparison.
    """
    env_mode = os.getenv("CHRONOQ_MODE", "")

    print("chronoq-celery eager demo — fifo vs active on real Celery API")
    print()

    train_jobs = _generate_training_jobs(_N_TRAIN, _SEED)
    eval_jobs = _generate_eval_jobs(_N_EVAL, _SEED)

    print(f"Pre-training ranker on {_N_TRAIN} synthetic records...", flush=True)
    ranker, type_means, _p95s, _counts = _train_ranker(train_jobs)
    print("  Training complete.")
    print()

    modes_to_run = [env_mode] if env_mode in ("fifo", "shadow", "active") else ["fifo", "active"]

    results: dict[str, list[float]] = {}
    for mode in modes_to_run:
        print(f"Running mode={mode!r} on {_N_EVAL} eval tasks...", flush=True)
        jcts = _run_mode(mode, eval_jobs, ranker, type_means)
        results[mode] = jcts
        print(f"  Completed {len(jcts)}/{_N_EVAL} tasks captured.")

    print()
    print(f"{'Mode':<10} {'tasks':>6} {'mean_jct_ms':>14} {'p99_jct_ms':>14}")
    print("-" * 48)
    for mode, jcts in results.items():
        if not jcts:
            print(f"{mode:<10} {'0':>6} {'N/A':>14} {'N/A':>14}")
            continue
        mean_ms = statistics.mean(jcts)
        sorted_jcts = sorted(jcts)
        p99_idx = max(0, int(len(sorted_jcts) * 0.99) - 1)
        p99_ms = sorted_jcts[p99_idx]
        print(f"{mode:<10} {len(jcts):>6} {mean_ms:>12.1f}ms {p99_ms:>12.1f}ms")

    if "fifo" in results and "active" in results and results["fifo"] and results["active"]:
        fifo_mean = statistics.mean(results["fifo"])
        active_mean = statistics.mean(results["active"])
        if fifo_mean > 0:
            improvement = (fifo_mean - active_mean) / fifo_mean * 100.0
            print()
            print(f"Mean JCT improvement (active vs fifo): {improvement:+.1f}%  (target: ≥20%)")
            if improvement >= 20.0:
                print("EXIT CRITERION: ≥20% mean JCT improvement — PASS")
            else:
                print(
                    f"WARNING: improvement {improvement:.1f}% < 20% target. "
                    "Consider increasing _N_TRAIN or checking cold-start seeding."
                )


if __name__ == "__main__":
    main()
