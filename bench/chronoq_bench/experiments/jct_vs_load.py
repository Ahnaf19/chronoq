"""JCT vs load experiment — the money plot.

Sweeps queue load 0.3 → 0.9 across 6 schedulers (FCFS, SJF-oracle, SRPT-approx,
random, priority+FCFS, LambdaRank) using a synthetic Pareto trace.

Outputs:
  bench/artifacts/jct_vs_load.png  — line plot, 6 schedulers × 9 load points
  bench/artifacts/results.json     — machine-readable metrics + CV-bullet metadata

Usage:
    uv run python -m chronoq_bench.experiments.jct_vs_load        # full (~5 min)
    CHRONOQ_BENCH_SMOKE=1 uv run python ...                        # CI smoke (<30s)
"""

from __future__ import annotations

import json
import os
from collections import Counter, defaultdict
from typing import TYPE_CHECKING, Any

import numpy as np
from chronoq_ranker.config import RankerConfig
from chronoq_ranker.features import DEFAULT_SCHEMA_V1
from chronoq_ranker.ranker import TaskRanker
from chronoq_ranker.schemas import QueueContext, TaskCandidate, TaskRecord

from chronoq_bench.baselines.fcfs import FCFSScheduler
from chronoq_bench.baselines.priority_fcfs import PriorityFCFSScheduler
from chronoq_bench.baselines.random_sched import RandomScheduler
from chronoq_bench.baselines.sjf_oracle import SJFOracleScheduler
from chronoq_bench.baselines.srpt_oracle import SRPTOracleScheduler
from chronoq_bench.metrics.jct import hol_blocking_count, mean_jct, p99_jct
from chronoq_bench.simulator import BaseScheduler, Job, Simulator
from chronoq_bench.traces.cache import ensure_artifacts_dir
from chronoq_bench.traces.synthetic import SyntheticTraceLoader

if TYPE_CHECKING:
    from pathlib import Path

    from chronoq_bench.traces.base import TraceJob

_SEED = 42
_N_TRAIN = 800
_N_EVAL = 300
_LOAD_POINTS = [0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]
_GROUP_SIZE = 25

_SCHED_COLORS = {
    "fcfs": "#888888",
    "sjf_oracle": "#2196F3",
    "srpt_oracle": "#00BCD4",
    "random": "#FF9800",
    "priority_fcfs": "#9C27B0",
    "lambdarank": "#F44336",
}
_SCHED_LABELS = {
    "fcfs": "FCFS",
    "sjf_oracle": "SJF-oracle",
    "srpt_oracle": "SRPT-approx",
    "random": "Random",
    "priority_fcfs": "Priority+FCFS",
    "lambdarank": "LambdaRank (ours)",
}


class LambdaRankScheduler(BaseScheduler):
    """BaseScheduler wrapper around a trained TaskRanker.

    Uses the extractor directly (not predict_scores) so each candidate gets its
    own QueueContext with recent_mean_ms_this_type populated — the strongest
    discriminator between fast and slow task types (e.g. resize 57ms vs transcode 3220ms).
    type_means/p95s/counts are pre-computed from training data and frozen at run time.
    """

    def __init__(
        self,
        ranker: TaskRanker,
        type_means: dict[str, float] | None = None,
        type_p95s: dict[str, float] | None = None,
        type_counts: dict[str, int] | None = None,
    ) -> None:
        self._ranker = ranker
        self._type_means = type_means or {}
        self._type_p95s = type_p95s or {}
        self._type_counts = type_counts or {}

    @property
    def name(self) -> str:
        return "lambdarank"

    def select(self, waiting: list[Job]) -> Job:
        if len(waiting) == 1:
            return waiting[0]

        type_queue_counts = Counter(j.task_type for j in waiting)
        estimator = self._ranker._estimator  # type: ignore[attr-defined]
        extractor = self._ranker._extractor  # type: ignore[attr-defined]

        all_features = []
        for job in waiting:
            cand = TaskCandidate(
                task_id=job.job_id,
                task_type=job.task_type,
                features={"payload_size": float(job.payload_size)},
            )
            ctx = QueueContext(
                queue_depth=len(waiting),
                queue_depth_same_type=type_queue_counts[job.task_type],
                recent_mean_ms_this_type=self._type_means.get(job.task_type, 0.0),
                recent_p95_ms_this_type=self._type_p95s.get(job.task_type, 0.0),
                recent_count_this_type=self._type_counts.get(job.task_type, 0),
            )
            all_features.append(extractor.extract(cand, context=ctx))

        batch_results = estimator.predict_batch(all_features)
        # Lowest score = highest priority = runs first
        best_idx = min(range(len(waiting)), key=lambda i: batch_results[i][0])
        return waiting[best_idx]


def _compute_type_stats(
    jobs: list,
) -> tuple[dict[str, float], dict[str, float], dict[str, int]]:
    """Return (means, p95s, counts) per task_type from any list of Job/TraceJob."""
    type_durations: dict[str, list[float]] = defaultdict(list)
    for job in jobs:
        type_durations[job.task_type].append(job.true_ms)
    means = {t: float(np.mean(durs)) for t, durs in type_durations.items()}
    p95s = {t: float(np.percentile(durs, 95)) for t, durs in type_durations.items()}
    counts = {t: len(durs) for t, durs in type_durations.items()}
    return means, p95s, counts


def _train_ranker(training_jobs: list[Job], min_groups: int = 5) -> TaskRanker:
    """Train LambdaRank on oracle labels (actual_ms == true_ms).

    Records are batched into explicit groups so pairwise training works even
    when all records arrive within the same 60s tumbling window.
    Per-type duration stats are embedded in record metadata so the model learns
    to use recent_mean_ms_this_type as the primary type-level ranking signal.
    """
    type_means, type_p95s, type_counts = _compute_type_stats(training_jobs)

    config = RankerConfig(
        cold_start_threshold=50,  # promote to LambdaRank at 50 records
        retrain_every_n=len(training_jobs) + 1,  # disable auto-retrain during saves
        min_groups=min_groups,
        storage_uri="memory://",
    )
    ranker = TaskRanker(config=config)

    for batch_start in range(0, len(training_jobs), _GROUP_SIZE):
        batch = training_jobs[batch_start : batch_start + _GROUP_SIZE]
        group_id = f"train_{batch_start // _GROUP_SIZE}"
        for job in batch:
            ranker._store.save(  # type: ignore[attr-defined]
                TaskRecord(
                    task_type=job.task_type,
                    payload_size=job.payload_size,
                    actual_ms=job.true_ms,
                    group_id=group_id,
                    metadata={
                        "recent_mean_ms_this_type": type_means.get(job.task_type, 0.0),
                        "recent_p95_ms_this_type": type_p95s.get(job.task_type, 0.0),
                        "recent_count_this_type": float(type_counts.get(job.task_type, 0)),
                    },
                )
            )

    ranker.retrain()
    return ranker


def _make_jobs(trace_jobs: list[TraceJob], mean_true_ms: float, load: float) -> list[Job]:
    """Create fresh Job instances with arrivals scaled to target load ρ.

    Simulator modifies jobs in-place, so a fresh list is required per run.
    """
    gap = mean_true_ms / load
    return [
        Job(
            job_id=tj.job_id,
            task_type=tj.task_type,
            payload_size=tj.payload_size,
            true_ms=tj.true_ms,
            arrival_ms=i * gap,
            priority=tj.priority,
        )
        for i, tj in enumerate(trace_jobs)
    ]


def run_experiment(
    n_train: int = _N_TRAIN,
    n_eval: int = _N_EVAL,
    load_points: list[float] | None = None,
    seed: int = _SEED,
) -> dict[str, Any]:
    """Run the full JCT vs load sweep and return a results dict."""
    if load_points is None:
        load_points = _LOAD_POINTS

    loader = SyntheticTraceLoader(n_jobs=n_train + n_eval, seed=seed)
    all_trace = loader.load()

    training_trace = all_trace[:n_train]
    eval_trace = all_trace[n_train : n_train + n_eval]

    training_jobs = [
        Job(
            job_id=tj.job_id,
            task_type=tj.task_type,
            payload_size=tj.payload_size,
            true_ms=tj.true_ms,
            arrival_ms=tj.arrival_ms,
        )
        for tj in training_trace
    ]
    mean_true = float(np.mean([tj.true_ms for tj in eval_trace]))

    type_means, type_p95s, type_counts = _compute_type_stats(training_jobs)
    ranker = _train_ranker(training_jobs)

    schedulers: list[BaseScheduler] = [
        FCFSScheduler(),
        SJFOracleScheduler(),
        SRPTOracleScheduler(),
        RandomScheduler(seed=seed),
        PriorityFCFSScheduler(),
        LambdaRankScheduler(
            ranker, type_means=type_means, type_p95s=type_p95s, type_counts=type_counts
        ),
    ]

    metrics: dict[str, dict[str, list]] = {
        sched.name: {"mean_jct": [], "p99_jct": [], "hol_count": []} for sched in schedulers
    }

    for load in load_points:
        for sched in schedulers:
            jobs = _make_jobs(eval_trace, mean_true, load)
            result = Simulator(sched, seed=seed).run(jobs)
            jcts = result.jct_ms
            metrics[sched.name]["mean_jct"].append(round(mean_jct(jcts), 2))
            metrics[sched.name]["p99_jct"].append(round(p99_jct(jcts), 2))
            metrics[sched.name]["hol_count"].append(hol_blocking_count(jcts))

    schema = DEFAULT_SCHEMA_V1
    return {
        "trace": "synthetic",
        "seed": seed,
        "feature_schema_version": schema.version,
        "n_features": len(schema.numeric) + len(schema.categorical),
        "n_training_jobs": n_train,
        "n_eval_jobs": n_eval,
        "load_points": load_points,
        "schedulers": metrics,
    }


def _plot(data: dict[str, Any], out_path: Path) -> None:
    import matplotlib.pyplot as plt

    from chronoq_bench.plots.base import save_figure

    load_pts = data["load_points"]
    schedulers = data["schedulers"]

    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    for name, m in schedulers.items():
        color = _SCHED_COLORS.get(name, "black")
        lw = 2.5 if name == "lambdarank" else 1.5
        axes[0].plot(
            load_pts,
            m["mean_jct"],
            label=_SCHED_LABELS.get(name, name),
            color=color,
            linewidth=lw,
            marker="o",
            markersize=4,
        )
        axes[1].plot(
            load_pts,
            m["p99_jct"],
            label=_SCHED_LABELS.get(name, name),
            color=color,
            linewidth=lw,
            marker="o",
            markersize=4,
        )

    for ax, ylabel in zip(axes, ["Mean JCT (ms)", "p99 JCT (ms)"], strict=True):
        ax.set_xlabel("Queue Load (ρ)")
        ax.set_ylabel(ylabel)
        ax.legend(fontsize=8)
        ax.grid(alpha=0.3)

    axes[0].set_title("Mean JCT vs Load")
    axes[1].set_title("p99 JCT vs Load")
    fig.suptitle(
        "chronoq-ranker: LambdaRank vs Baselines (Synthetic Trace)",
        fontsize=12,
        fontweight="bold",
    )
    fig.tight_layout()
    save_figure(fig, out_path)
    print(f"Saved {out_path}")


def _print_criteria(data: dict[str, Any]) -> None:
    load_pts = data["load_points"]
    s = data["schedulers"]

    def _val(sched: str, metric: str, load: float) -> float:
        if load not in load_pts:
            return float("nan")
        return s[sched][metric][load_pts.index(load)]

    def _imp(base: float, cand: float) -> float:
        return (base - cand) / base * 100 if base > 0 else float("nan")

    print("\n=== Exit Criteria ===")
    m07 = _imp(_val("fcfs", "mean_jct", 0.7), _val("lambdarank", "mean_jct", 0.7))
    p99_07 = _imp(_val("fcfs", "p99_jct", 0.7), _val("lambdarank", "p99_jct", 0.7))
    sjf_p99 = _val("sjf_oracle", "p99_jct", 0.7)
    vs_sjf = abs(_val("lambdarank", "p99_jct", 0.7) - sjf_p99)
    vs_sjf_pct = vs_sjf / sjf_p99 * 100 if sjf_p99 > 0 else float("nan")
    print(f"  mean JCT vs FCFS @ 0.7: {m07:+.1f}%  (target ≥+10%)")
    print(f"  p99  JCT vs FCFS @ 0.7: {p99_07:+.1f}%  (target ≥+15%)")
    print(f"  p99 gap vs SJF-oracle @ 0.7: {vs_sjf_pct:.1f}%  (target ≤20%)")
    if 0.5 in load_pts:
        p99_05 = _imp(_val("fcfs", "p99_jct", 0.5), _val("lambdarank", "p99_jct", 0.5))
        print(f"  p99  JCT vs FCFS @ 0.5: {p99_05:+.1f}%  (target ≥+15%)")


def main() -> None:
    smoke = os.getenv("CHRONOQ_BENCH_SMOKE") == "1"
    n_train = 200 if smoke else _N_TRAIN
    n_eval = 100 if smoke else _N_EVAL
    load_pts = [0.5, 0.7] if smoke else _LOAD_POINTS

    print(f"jct_vs_load: n_train={n_train}, n_eval={n_eval}, load_points={load_pts}")
    data = run_experiment(n_train=n_train, n_eval=n_eval, load_points=load_pts)

    artifacts = ensure_artifacts_dir()
    results_path = artifacts / "results.json"
    results_path.write_text(json.dumps(data, indent=2))
    print(f"Wrote {results_path}")

    _plot(data, artifacts / "jct_vs_load.png")
    _print_criteria(data)


if __name__ == "__main__":
    main()
