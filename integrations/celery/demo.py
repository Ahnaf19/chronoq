"""chronoq-celery demo — fifo vs active JCT comparison on a 200-task Pareto workload.

Runs without Docker: pre-trains a LambdaRank ranker on 800 synthetic jobs, seeds the
TypeStatsTracker, then compares mean/p99 JCT between fifo (arrival order) and active
(score-ranked order) scheduling for 200 eval tasks.

No chronoq_bench import — inline Pareto generation keeps the PyPI dep graph clean.
"""

from __future__ import annotations

from collections import defaultdict

import numpy as np
from chronoq_celery import LearnedScheduler, TypeStatsTracker
from chronoq_ranker import TaskRanker
from chronoq_ranker.config import RankerConfig
from chronoq_ranker.schemas import TaskRecord

# -----------------------------------------------------------------------
# Inline Pareto job generator (mirrors bench/chronoq_bench/traces/synthetic.py params)
# -----------------------------------------------------------------------
_TASK_TYPES = ["resize", "embed", "ocr", "summarize", "transcode"]
_TYPE_MEANS_MS: dict[str, float] = {
    "resize": 57.0,
    "embed": 230.0,
    "ocr": 810.0,
    "summarize": 1650.0,
    "transcode": 3220.0,
}
_TYPE_SIGMA = 0.6
_N_TRAIN = 800
_N_EVAL = 200
_SEED = 42
_GROUP_SIZE = 20


def _generate_jobs(n: int, seed: int) -> list[dict]:
    rng = np.random.default_rng(seed)
    type_arr = rng.choice(_TASK_TYPES, size=n)
    jobs = []
    for i, task_type in enumerate(type_arr):
        true_ms = float(np.exp(rng.normal(np.log(_TYPE_MEANS_MS[task_type]), _TYPE_SIGMA)))
        payload_size = int(rng.lognormal(7.0, 1.5))
        jobs.append(
            {"id": i, "task_type": task_type, "payload_size": payload_size, "true_ms": true_ms}
        )
    return jobs


def _compute_type_stats(jobs: list[dict]) -> tuple[dict, dict, dict]:
    buckets: dict[str, list[float]] = defaultdict(list)
    for j in jobs:
        buckets[j["task_type"]].append(j["true_ms"])
    means = {t: float(np.mean(v)) for t, v in buckets.items()}
    p95s = {t: float(np.percentile(v, 95)) for t, v in buckets.items()}
    counts = {t: len(v) for t, v in buckets.items()}
    return means, p95s, counts


# -----------------------------------------------------------------------
# Training
# -----------------------------------------------------------------------


def _train_ranker(
    jobs: list[dict],
) -> tuple[TaskRanker, object, dict, dict, dict]:
    """Train LambdaRank on oracle labels. Returns (ranker, result, means, p95s, counts)."""
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
                    # Embed type stats so the model learns recent_mean_ms_this_type
                    metadata={
                        "recent_mean_ms_this_type": means.get(job["task_type"], 0.0),
                        "recent_p95_ms_this_type": p95s.get(job["task_type"], 0.0),
                        "recent_count_this_type": float(counts.get(job["task_type"], 0)),
                    },
                )
            )

    result = ranker.retrain()
    return ranker, result, means, p95s, counts


# -----------------------------------------------------------------------
# JCT simulation (no actual sleeping — computes cumulative duration sums)
# -----------------------------------------------------------------------


def _compute_jcts(jobs: list[dict], order: list[int]) -> list[float]:
    """Compute per-task JCT given an execution order (indices into jobs list)."""
    t = 0.0
    jcts = []
    for idx in order:
        t += jobs[idx]["true_ms"]
        jcts.append(t)
    return jcts


def _run_fifo(eval_jobs: list[dict]) -> list[float]:
    order = list(range(len(eval_jobs)))  # arrival order = FIFO
    return _compute_jcts(eval_jobs, order)


def _run_active(
    eval_jobs: list[dict],
    ranker: TaskRanker,
    type_means: dict,
    type_p95s: dict,
    type_counts: dict,
) -> list[float]:
    """Score all candidates using LearnedScheduler._score(), sort, compute JCT."""
    stats = TypeStatsTracker()
    stats.seed(type_means)
    scheduler = LearnedScheduler(mode="active", ranker=ranker, stats_tracker=stats)

    # Score all eval tasks upfront (heap depth = 0 for all, so queue_depth features = 0)
    scores = [
        scheduler._score(str(job["id"]), job["task_type"], job["payload_size"]) for job in eval_jobs
    ]
    # Lower score → higher priority → dispatched first
    order = sorted(range(len(eval_jobs)), key=lambda i: scores[i])
    return _compute_jcts(eval_jobs, order)


# -----------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------


def main() -> None:
    print("chronoq-celery demo — fifo vs active, 200-task Pareto workload")
    print()

    all_jobs = _generate_jobs(_N_TRAIN + _N_EVAL, _SEED)
    train_jobs = all_jobs[:_N_TRAIN]
    eval_jobs = all_jobs[_N_TRAIN:]

    print(f"Training ranker on {_N_TRAIN} jobs...", flush=True)
    ranker, result, type_means, type_p95s, type_counts = _train_ranker(train_jobs)
    print(f"  Model:   {result.model_type}")
    print(f"  Samples: {result.samples_used}")
    print()

    fifo_jcts = _run_fifo(eval_jobs)
    active_jcts = _run_active(eval_jobs, ranker, type_means, type_p95s, type_counts)

    fifo_mean = float(np.mean(fifo_jcts))
    active_mean = float(np.mean(active_jcts))
    fifo_p99 = float(np.percentile(fifo_jcts, 99))
    active_p99 = float(np.percentile(active_jcts, 99))

    mean_imp = (fifo_mean - active_mean) / fifo_mean * 100
    p99_imp = (fifo_p99 - active_p99) / fifo_p99 * 100

    print(f"{'Mode':<10} {'mean_jct':>14} {'p99_jct':>14}")
    print("-" * 40)
    print(f"{'fifo':<10} {fifo_mean:>12.0f}ms {fifo_p99:>12.0f}ms")
    print(f"{'active':<10} {active_mean:>12.0f}ms {active_p99:>12.0f}ms")
    print()
    print(f"Mean JCT improvement: {mean_imp:+.1f}%  (target: ≥15%)")
    print(f"P99  JCT improvement: {p99_imp:+.1f}%")

    assert mean_imp >= 15.0, (
        f"Mean JCT improvement {mean_imp:.1f}% < 15% target. "
        "Verify ranker trained to LambdaRank and recent_mean_ms_this_type is seeded."
    )
    print()
    print("EXIT CRITERION: mean JCT improvement ≥15% — PASS")


if __name__ == "__main__":
    main()
