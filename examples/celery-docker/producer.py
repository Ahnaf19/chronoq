"""Producer for the chronoq Docker demo stack.

Generates 500 jobs with varied (task_type, payload_size), enqueues them through
a ``LearnedScheduler`` instance (which calls ``apply_async`` as its ``apply_fn``),
waits for all results, then writes a CSV to ``./artifacts/run_{mode}.csv``.

The scheduler in the producer acts as a *pre-broker gate*: in active mode it
holds tasks in a local priority heap and dispatches them in ranked order via
``apply_async``; in fifo mode it calls ``apply_async`` immediately in arrival
order. Either way the Celery worker receives tasks via the Redis broker and
executes them. The worker's own scheduler records per-type stats via
``task_success`` signals on the worker side.

CSV schema:
    task_id, task_type, payload_size, submit_ts_ms, complete_ts_ms, jct_ms

Environment variables
---------------------
CHRONOQ_MODE          : "fifo" | "shadow" | "active"  (default: "fifo")
CELERY_BROKER_URL     : broker URL  (default: redis://localhost:6379/0)
CELERY_RESULT_BACKEND : result URL  (default: same as broker)
"""

from __future__ import annotations

import csv
import os
import sys
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
from celery import Celery
from chronoq_celery import LearnedScheduler, TypeStatsTracker
from chronoq_ranker import TaskRanker
from chronoq_ranker.config import RankerConfig
from chronoq_ranker.schemas import TaskRecord

if TYPE_CHECKING:
    from collections.abc import Callable

    from celery.result import AsyncResult

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

BROKER_URL = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0")
BACKEND_URL = os.environ.get("CELERY_RESULT_BACKEND", BROKER_URL)
CHRONOQ_MODE = os.environ.get("CHRONOQ_MODE", "fifo")

N_JOBS = 500
SEED = 42
GROUP_SIZE = 20
N_PRETRAIN = 500
PRETRAIN_SEED = 99
POLL_TIMEOUT_S = 600  # 10 min safety net

ARTIFACTS_DIR = Path(__file__).parent / "artifacts"

_TASK_TYPES: list[str] = ["resize", "analyze", "compress", "encode", "transcode"]
_TASK_PROFILES: dict[str, tuple[float, float]] = {
    "resize": (20.0, 0.4),
    "analyze": (90.0, 0.4),
    "compress": (150.0, 0.4),
    "encode": (400.0, 0.4),
    "transcode": (1800.0, 0.4),
}

# ---------------------------------------------------------------------------
# Celery app (same config as worker — must share broker/backend)
# ---------------------------------------------------------------------------

app = Celery("worker", broker=BROKER_URL, backend=BACKEND_URL)
app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    result_expires=300,
)


# ---------------------------------------------------------------------------
# Redis connectivity check
# ---------------------------------------------------------------------------


def _wait_for_redis(max_attempts: int = 60, delay_s: float = 1.0) -> None:
    """Block until the Redis broker responds to a PING, or raise on timeout."""
    import redis

    client = redis.from_url(BROKER_URL)
    for attempt in range(1, max_attempts + 1):
        try:
            client.ping()
            print(f"[producer] Redis ready after {attempt} attempt(s).", flush=True)
            return
        except Exception as exc:  # noqa: BLE001
            print(f"[producer] waiting for Redis ({attempt}/{max_attempts}): {exc}", flush=True)
            time.sleep(delay_s)
    raise RuntimeError(f"Redis at {BROKER_URL!r} not reachable after {max_attempts} attempts.")


# ---------------------------------------------------------------------------
# Duration sampling (mirrors worker.py)
# ---------------------------------------------------------------------------


def _duration_ms(task_type: str, payload_size: int, rng: np.random.Generator) -> float:
    mean_ms, sigma = _TASK_PROFILES[task_type]
    base = float(np.exp(rng.normal(np.log(mean_ms), sigma)))
    payload_bonus = payload_size / 10_000.0
    return base + payload_bonus


# ---------------------------------------------------------------------------
# Pre-training (producer builds its own scheduler for active/shadow modes)
# ---------------------------------------------------------------------------


def _generate_pretrain_jobs(n: int, seed: int) -> list[dict]:
    rng = np.random.default_rng(seed)
    type_arr = rng.choice(_TASK_TYPES, size=n)
    jobs: list[dict] = []
    for task_type in type_arr:
        payload_size = int(rng.lognormal(7.0, 1.5))
        rng2 = np.random.default_rng(seed + len(jobs))
        true_ms = _duration_ms(task_type, payload_size, rng2)
        jobs.append({"task_type": task_type, "payload_size": payload_size, "true_ms": true_ms})
    return jobs


def _compute_type_stats(
    jobs: list[dict],
) -> tuple[dict[str, float], dict[str, float], dict[str, int]]:
    from collections import defaultdict

    buckets: dict[str, list[float]] = defaultdict(list)
    for j in jobs:
        buckets[j["task_type"]].append(j["true_ms"])
    means = {t: float(np.mean(v)) for t, v in buckets.items()}
    p95s = {t: float(np.percentile(v, 95)) for t, v in buckets.items()}
    counts = {t: int(len(v)) for t, v in buckets.items()}
    return means, p95s, counts


def _build_scheduler(mode: str) -> LearnedScheduler:
    """Build and return a LearnedScheduler for the given mode.

    For active/shadow modes, pre-trains on synthetic records so the ranker
    is warm from the first submission.
    """
    if mode == "fifo":
        return LearnedScheduler(mode="fifo")

    print(f"[producer] pre-training ranker on {N_PRETRAIN} synthetic records...", flush=True)
    jobs = _generate_pretrain_jobs(N_PRETRAIN, PRETRAIN_SEED)
    means, p95s, counts = _compute_type_stats(jobs)

    config = RankerConfig(
        cold_start_threshold=50,
        retrain_every_n=len(jobs) + 1,
        min_groups=5,
        storage_uri="memory://",
    )
    ranker = TaskRanker(config=config)

    for batch_start in range(0, len(jobs), GROUP_SIZE):
        batch = jobs[batch_start : batch_start + GROUP_SIZE]
        group_id = f"pretrain_{batch_start // GROUP_SIZE}"
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

    stats = TypeStatsTracker()
    stats.seed(means)

    return LearnedScheduler(
        mode=mode,  # type: ignore[arg-type]
        ranker=ranker,
        stats_tracker=stats,
    )


# ---------------------------------------------------------------------------
# Job generation
# ---------------------------------------------------------------------------


def _generate_jobs(n: int, seed: int) -> list[dict]:
    """Generate n jobs with varied task_type and payload_size."""
    rng = np.random.default_rng(seed)
    type_arr = rng.choice(_TASK_TYPES, size=n)
    jobs: list[dict] = []
    for task_type in type_arr:
        payload_size = int(rng.lognormal(7.0, 1.5))
        task_id = str(uuid.uuid4())
        seed_val = int(rng.integers(0, 2**31))
        jobs.append(
            {
                "task_id": task_id,
                "task_type": task_type,
                "payload_size": payload_size,
                "seed": seed_val,
            }
        )
    return jobs


# ---------------------------------------------------------------------------
# apply_fn factory (avoids B023 loop-variable closure)
# ---------------------------------------------------------------------------


def _make_apply_fn(
    app_: Celery,
    task_type: str,
    payload_size: int,
    seed_val: int,
    task_id: str,
    result_holder: dict[str, object],
    submit_ts: dict[str, float],
) -> Callable[[], None]:
    """Return a zero-arg callable that enqueues a task and records its submit timestamp."""

    def apply_fn() -> None:
        async_result = app_.send_task(
            task_type,
            kwargs={"task_type": task_type, "payload_size": payload_size, "seed": seed_val},
            task_id=task_id,
        )
        result_holder["result"] = async_result
        submit_ts[task_id] = time.monotonic() * 1000

    return apply_fn


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    """Run the producer: enqueue 500 jobs, wait for completion, write CSV."""
    print(f"[producer] CHRONOQ_MODE={CHRONOQ_MODE}", flush=True)
    _wait_for_redis()

    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

    scheduler = _build_scheduler(CHRONOQ_MODE)
    print(f"[producer] scheduler mode={scheduler.mode}", flush=True)

    jobs = _generate_jobs(N_JOBS, SEED)
    print(f"[producer] submitting {len(jobs)} jobs...", flush=True)

    # Map task_id → result holder dict so we can poll later
    async_results: dict[str, dict[str, object]] = {}
    submit_ts: dict[str, float] = {}

    for job in jobs:
        task_type = job["task_type"]
        payload_size = job["payload_size"]
        seed_val = job["seed"]
        task_id = job["task_id"]

        result_holder: dict[str, object] = {}

        apply_fn = _make_apply_fn(
            app, task_type, payload_size, seed_val, task_id, result_holder, submit_ts
        )

        scheduler.submit(
            task_type=task_type,
            payload_size=payload_size,
            apply_fn=apply_fn,
            task_id=task_id,
        )

        async_results[task_id] = result_holder

    # In active mode, flush remaining heap entries (all were held until now).
    if CHRONOQ_MODE == "active":
        print("[producer] flushing active-mode heap...", flush=True)
        while scheduler.dispatch_next():
            pass

    print(f"[producer] {len(submit_ts)} tasks enqueued, waiting for results...", flush=True)

    # Poll for all results
    complete_ts: dict[str, float] = {}
    deadline = time.monotonic() + POLL_TIMEOUT_S

    pending = set(async_results.keys())
    while pending and time.monotonic() < deadline:
        done_this_round: set[str] = set()
        for tid in list(pending):
            holder = async_results[tid]
            if "result" not in holder:
                continue  # apply_fn not yet called (shouldn't happen post-flush)
            ar: AsyncResult = holder["result"]  # type: ignore[assignment]
            if ar.ready():
                complete_ts[tid] = time.monotonic() * 1000
                done_this_round.add(tid)
        pending -= done_this_round
        if pending:
            time.sleep(0.1)

    if pending:
        print(
            f"[producer] WARNING: {len(pending)} tasks did not complete within "
            f"{POLL_TIMEOUT_S}s timeout.",
            flush=True,
        )

    # Build and write CSV
    csv_path = ARTIFACTS_DIR / f"run_{CHRONOQ_MODE}.csv"
    rows: list[dict] = []
    for job in jobs:
        tid = job["task_id"]
        s_ts = submit_ts.get(tid)
        c_ts = complete_ts.get(tid)
        if s_ts is not None and c_ts is not None:
            rows.append(
                {
                    "task_id": tid,
                    "task_type": job["task_type"],
                    "payload_size": job["payload_size"],
                    "submit_ts_ms": s_ts,
                    "complete_ts_ms": c_ts,
                    "jct_ms": c_ts - s_ts,
                }
            )

    fieldnames = [
        "task_id",
        "task_type",
        "payload_size",
        "submit_ts_ms",
        "complete_ts_ms",
        "jct_ms",
    ]
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"[producer] wrote {len(rows)} rows to {csv_path}", flush=True)

    if rows:
        jcts = [r["jct_ms"] for r in rows]
        mean_jct = float(np.mean(jcts))
        p99_jct = float(np.percentile(jcts, 99))
        print(
            f"[producer] mode={CHRONOQ_MODE}  mean_jct={mean_jct:.0f}ms  p99_jct={p99_jct:.0f}ms",
            flush=True,
        )

    sys.exit(0)


if __name__ == "__main__":
    main()
