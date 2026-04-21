"""Drift recovery experiment.

Trains LambdaRank on a "pre-shift" trace, then measures p99 JCT degradation when the
workload shifts (long jobs 3× more frequent). Retrains incrementally for 3 cycles and
tracks p99 recovery toward the pre-shift baseline.

Output: bench/artifacts/drift_recovery.png

Usage:
    uv run python -m chronoq_bench.experiments.drift_recovery
    CHRONOQ_BENCH_SMOKE=1 uv run python ...
"""

from __future__ import annotations

import contextlib
import os
from typing import TYPE_CHECKING

import numpy as np
from chronoq_ranker.schemas import TaskRecord

if TYPE_CHECKING:
    from pathlib import Path

from chronoq_bench.baselines.fcfs import FCFSScheduler
from chronoq_bench.experiments.jct_vs_load import (
    LambdaRankScheduler,
    _compute_type_stats,
    _make_jobs,
    _train_ranker,
)
from chronoq_bench.metrics.jct import p99_jct
from chronoq_bench.simulator import Job, Simulator
from chronoq_bench.traces.cache import ensure_artifacts_dir
from chronoq_bench.traces.synthetic import SyntheticTraceLoader

_SEED = 42
_LOAD = 0.7
_N_PRETRAIN = 300
_N_EVAL = 200
_N_RETRAIN_CYCLE = 100
_N_RETRAIN_CYCLES = 3


def _shifted_trace(n: int, seed: int) -> list:
    """Synthetic trace with 3× more 'transcode' (longest) jobs — simulates drift."""
    rng = np.random.default_rng(seed)
    import random as _random

    _rng = _random.Random(seed + 1)

    task_types_weighted = (
        ["resize"] * 1
        + ["analyze"] * 1
        + ["compress"] * 1
        + ["encode"] * 1
        + ["transcode"] * 3  # 3× heavier weight for drift
    )
    _type_params = {
        "resize": (3.0, 0.4),
        "analyze": (4.5, 0.4),
        "compress": (5.0, 0.4),
        "encode": (6.0, 0.4),
        "transcode": (7.5, 0.4),
    }
    jobs = []
    t = 0.0
    for i in range(n):
        task_type = _rng.choice(task_types_weighted)
        mu, sigma = _type_params[task_type]
        payload = int(rng.integers(100, 5000))
        mu_adj = mu + np.log1p(payload / 1000) * 0.3
        true_ms = float(max(1.0, rng.lognormal(mu_adj, sigma)))
        gap = float(rng.exponential(20.0))
        t += gap

        from chronoq_bench.traces.base import TraceJob

        jobs.append(
            TraceJob(
                job_id=f"shifted_{i}",
                task_type=task_type,
                payload_size=payload,
                true_ms=true_ms,
                arrival_ms=t,
            )
        )
    return jobs


def run_experiment(smoke: bool = False) -> dict:
    n_pretrain = 150 if smoke else _N_PRETRAIN
    n_eval = 80 if smoke else _N_EVAL
    n_retrain = 50 if smoke else _N_RETRAIN_CYCLE

    # Pre-shift: normal trace
    loader = SyntheticTraceLoader(n_jobs=n_pretrain, seed=_SEED)
    pretrain_trace = loader.load()
    pretrain_jobs = [
        Job(
            job_id=tj.job_id,
            task_type=tj.task_type,
            payload_size=tj.payload_size,
            true_ms=tj.true_ms,
            arrival_ms=tj.arrival_ms,
        )
        for tj in pretrain_trace
    ]
    pretrain_means, pretrain_p95s, pretrain_counts = _compute_type_stats(pretrain_jobs)
    ranker = _train_ranker(pretrain_jobs, min_groups=3)

    def _lr_sched() -> LambdaRankScheduler:
        return LambdaRankScheduler(
            ranker,
            type_means=pretrain_means,
            type_p95s=pretrain_p95s,
            type_counts=pretrain_counts,
        )

    # Baseline: pre-shift p99 with trained ranker
    eval_normal = SyntheticTraceLoader(n_jobs=n_eval, seed=_SEED + 1).load()
    mean_true = float(np.mean([tj.true_ms for tj in eval_normal]))
    jobs_normal = _make_jobs(eval_normal, mean_true, _LOAD)
    baseline_p99 = p99_jct(Simulator(_lr_sched()).run(jobs_normal).jct_ms)
    fcfs_jobs = _make_jobs(eval_normal, mean_true, _LOAD)
    fcfs_p99 = p99_jct(Simulator(FCFSScheduler()).run(fcfs_jobs).jct_ms)

    # Post-shift: drift scenario
    shifted_trace = _shifted_trace(n_eval, seed=_SEED + 2)
    mean_shifted = float(np.mean([tj.true_ms for tj in shifted_trace]))
    jobs_shifted = _make_jobs(shifted_trace, mean_shifted, _LOAD)
    post_shift_p99 = p99_jct(Simulator(_lr_sched()).run(jobs_shifted).jct_ms)

    # Recovery: retrain incrementally on shifted data
    recovery_p99 = []
    for cycle in range(_N_RETRAIN_CYCLES):
        retrain_trace = _shifted_trace(n_retrain, seed=_SEED + 10 + cycle)
        for i, tj in enumerate(retrain_trace):
            group_id = f"recovery_{cycle}_batch_{i // 20}"
            ranker._store.save(  # type: ignore[attr-defined]
                TaskRecord(
                    task_type=tj.task_type,
                    payload_size=tj.payload_size,
                    actual_ms=tj.true_ms,
                    group_id=group_id,
                )
            )
        with contextlib.suppress(Exception):
            ranker.retrain()
        jobs_eval = _make_jobs(shifted_trace, mean_shifted, _LOAD)
        cycle_p99 = p99_jct(Simulator(_lr_sched()).run(jobs_eval).jct_ms)
        recovery_p99.append(round(cycle_p99, 2))

    return {
        "load": _LOAD,
        "baseline_p99_ms": round(baseline_p99, 2),
        "fcfs_p99_ms": round(fcfs_p99, 2),
        "post_shift_p99_ms": round(post_shift_p99, 2),
        "recovery_p99_ms": recovery_p99,
        "recovery_cycles": _N_RETRAIN_CYCLES,
    }


def _plot(data: dict, out_path: Path) -> None:
    import matplotlib.pyplot as plt

    from chronoq_bench.plots.base import save_figure

    baseline = data["baseline_p99_ms"]
    post_shift = data["post_shift_p99_ms"]
    recovery = data["recovery_p99_ms"]
    fcfs = data["fcfs_p99_ms"]

    x = list(range(len(recovery) + 2))
    y = [baseline, post_shift] + recovery

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(x, y, marker="o", linewidth=2, color="#F44336", label="LambdaRank p99 JCT")
    ax.axhline(baseline, linestyle="--", color="#888888", alpha=0.6, label="Pre-shift baseline")
    ax.axhline(fcfs, linestyle=":", color="#2196F3", alpha=0.6, label="FCFS reference")
    ax.axvline(1, linestyle="--", color="black", alpha=0.4, label="Distribution shift →")

    ax.set_xticks(x)
    retrain_labels = [f"Retrain {i + 1}" for i in range(len(recovery))]
    ax.set_xticklabels(["Pre-shift", "Post-shift"] + retrain_labels)
    ax.set_ylabel("p99 JCT (ms)")
    ax.set_title("Drift Recovery: p99 JCT over Retrain Cycles")
    ax.legend(fontsize=9)
    ax.grid(alpha=0.3)
    fig.tight_layout()

    save_figure(fig, out_path)
    print(f"Saved {out_path}")


def main() -> None:
    smoke = os.getenv("CHRONOQ_BENCH_SMOKE") == "1"
    print(f"drift_recovery: smoke={smoke}")
    data = run_experiment(smoke=smoke)

    artifacts = ensure_artifacts_dir()
    _plot(data, artifacts / "drift_recovery.png")

    final = data["recovery_p99_ms"][-1] if data["recovery_p99_ms"] else float("nan")
    baseline = data["baseline_p99_ms"]
    recovery_pct = abs(final - baseline) / baseline * 100 if baseline > 0 else float("nan")
    print(
        f"Post-retrain p99: {final:.1f}ms  (baseline: {baseline:.1f}ms, gap: {recovery_pct:.1f}%)"
    )


if __name__ == "__main__":
    main()
