"""Celery worker for the chronoq Docker demo stack.

Five task types with ``time.sleep``-based durations mirror the synthetic
trace profile used in the bench package:

    resize     ~20 ms   (small image resize proxy)
    analyze    ~90 ms   (feature extraction proxy)
    compress   ~150 ms  (file compression proxy)
    encode     ~400 ms  (audio/video encode proxy)
    transcode  ~1800 ms (heavy transcode proxy)

Environment variables
---------------------
CHRONOQ_MODE          : "fifo" | "shadow" | "active"  (default: "fifo")
CELERY_BROKER_URL     : broker URL  (default: redis://localhost:6379/0)
CELERY_RESULT_BACKEND : result URL  (default: same as broker)

At startup the worker pre-trains a LambdaRank ranker on 500 seeded synthetic
records so the active-mode scheduler has a usable model from the first job.
"""

from __future__ import annotations

import os
import time

import numpy as np
from celery import Celery
from chronoq_celery import LearnedScheduler, TypeStatsTracker, attach_signals
from chronoq_ranker import TaskRanker
from chronoq_ranker.config import RankerConfig
from chronoq_ranker.schemas import TaskRecord

# ---------------------------------------------------------------------------
# Celery app
# ---------------------------------------------------------------------------

BROKER_URL = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0")
BACKEND_URL = os.environ.get("CELERY_RESULT_BACKEND", BROKER_URL)
CHRONOQ_MODE = os.environ.get("CHRONOQ_MODE", "fifo")

app = Celery("worker", broker=BROKER_URL, backend=BACKEND_URL)
app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    result_expires=300,
    worker_prefetch_multiplier=1,  # one at a time → dispatcher controls ordering
)

# ---------------------------------------------------------------------------
# Task-type parameters
# ---------------------------------------------------------------------------

# (mean_ms, std_factor) — durations are lognormal(log(mean), 0.4)
_TASK_PROFILES: dict[str, tuple[float, float]] = {
    "resize": (20.0, 0.4),
    "analyze": (90.0, 0.4),
    "compress": (150.0, 0.4),
    "encode": (400.0, 0.4),
    "transcode": (1800.0, 0.4),
}

_TASK_TYPES: list[str] = list(_TASK_PROFILES.keys())
_N_PRETRAIN = 500
_PRETRAIN_SEED = 99
_GROUP_SIZE = 20


def _duration_ms(task_type: str, payload_size: int, rng: np.random.Generator) -> float:
    """Sample a realistic duration from the task type's lognormal profile.

    Payload size adds a small linear factor (1 ms per 10 000 bytes) to give the
    ranker a payload-size signal to learn from.
    """
    mean_ms, sigma = _TASK_PROFILES[task_type]
    base = float(np.exp(rng.normal(np.log(mean_ms), sigma)))
    payload_bonus = payload_size / 10_000.0
    return base + payload_bonus


# ---------------------------------------------------------------------------
# Pre-training helpers
# ---------------------------------------------------------------------------


def _generate_pretrain_jobs(n: int, seed: int) -> list[dict]:
    """Generate synthetic training records with payload-size variation."""
    rng = np.random.default_rng(seed)
    type_arr = rng.choice(_TASK_TYPES, size=n)
    jobs: list[dict] = []
    for task_type in type_arr:
        payload_size = int(rng.lognormal(7.0, 1.5))
        rng2 = np.random.default_rng(seed + len(jobs))
        true_ms = _duration_ms(task_type, payload_size, rng2)
        jobs.append(
            {
                "task_type": task_type,
                "payload_size": payload_size,
                "true_ms": true_ms,
            }
        )
    return jobs


def _compute_type_stats(
    jobs: list[dict],
) -> tuple[dict[str, float], dict[str, float], dict[str, int]]:
    """Compute per-type mean, p95, and count from a list of job dicts."""
    from collections import defaultdict

    buckets: dict[str, list[float]] = defaultdict(list)
    for j in jobs:
        buckets[j["task_type"]].append(j["true_ms"])
    means = {t: float(np.mean(v)) for t, v in buckets.items()}
    p95s = {t: float(np.percentile(v, 95)) for t, v in buckets.items()}
    counts = {t: int(len(v)) for t, v in buckets.items()}
    return means, p95s, counts


def _pretrain_ranker(
    jobs: list[dict],
) -> tuple[TaskRanker, dict[str, float], dict[str, float], dict[str, int]]:
    """Pre-train a LambdaRank ranker on synthetic records.

    Returns (ranker, type_means, type_p95s, type_counts).
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
        group_id = f"pretrain_{batch_start // _GROUP_SIZE}"
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
# Module-level scheduler (initialized before accepting tasks)
# ---------------------------------------------------------------------------

print(f"[worker] CHRONOQ_MODE={CHRONOQ_MODE}", flush=True)

if CHRONOQ_MODE == "fifo":
    _scheduler = LearnedScheduler(mode="fifo")
    print("[worker] scheduler: FIFO passthrough — ranker not instantiated", flush=True)
else:
    print(f"[worker] pre-training ranker on {_N_PRETRAIN} synthetic records...", flush=True)
    _pretrain_jobs = _generate_pretrain_jobs(_N_PRETRAIN, _PRETRAIN_SEED)
    _ranker, _type_means, _type_p95s, _type_counts = _pretrain_ranker(_pretrain_jobs)

    _stats = TypeStatsTracker()
    _stats.seed(_type_means)

    _scheduler = LearnedScheduler(
        mode=CHRONOQ_MODE,  # type: ignore[arg-type]
        ranker=_ranker,
        stats_tracker=_stats,
    )
    print(f"[worker] scheduler: {CHRONOQ_MODE} mode, ranker ready", flush=True)

attach_signals(app, _scheduler)

# ---------------------------------------------------------------------------
# Task definitions
# ---------------------------------------------------------------------------


def _make_task(task_type: str):
    """Factory that creates a Celery task for the given task_type."""

    @app.task(name=task_type, bind=True)
    def _task(self, task_type: str = task_type, payload_size: int = 1000, seed: int = 0):
        """Execute a synthetic task by sleeping for a duration sampled from the type profile."""
        rng = np.random.default_rng(seed)
        duration_s = _duration_ms(task_type, payload_size, rng) / 1000.0
        time.sleep(duration_s)
        return {"task_type": task_type, "payload_size": payload_size, "duration_s": duration_s}

    return _task


resize = _make_task("resize")
analyze = _make_task("analyze")
compress = _make_task("compress")
encode = _make_task("encode")
transcode = _make_task("transcode")

# Map task_type string → Celery task object for the producer
TASK_MAP: dict[str, object] = {
    "resize": resize,
    "analyze": analyze,
    "compress": compress,
    "encode": encode,
    "transcode": transcode,
}
