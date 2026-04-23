"""JCT vs worker concurrency experiment.

Fixes the queue load at rho=0.7 and sweeps the number of parallel workers
``concurrency`` in {1, 2, 4, 8, 16}. Shows how FCFS and LambdaRank compare as
Celery-style worker concurrency grows — the canonical "but my setup isn't
single-server" objection.

Outputs:
  bench/artifacts/jct_vs_concurrency.png      — 2-panel line plot (mean + p99)
  bench/artifacts/results_concurrency.json    — machine-readable metrics

Usage:
    uv run python -m chronoq_bench.experiments.jct_vs_concurrency       # ~3 min
    CHRONOQ_BENCH_SMOKE=1 uv run python -m ...jct_vs_concurrency       # smoke (<60s)
"""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING, Any

import numpy as np
from chronoq_ranker.features import DEFAULT_SCHEMA_V1

from chronoq_bench.baselines.fcfs import FCFSScheduler
from chronoq_bench.experiments.jct_vs_load import (
    LambdaRankScheduler,
    _compute_type_stats,
    _make_jobs,
    _train_ranker,
)
from chronoq_bench.metrics.jct import hol_blocking_count, mean_jct, p99_jct
from chronoq_bench.simulator import BaseScheduler, Job, Simulator
from chronoq_bench.traces.cache import ensure_artifacts_dir
from chronoq_bench.traces.synthetic import SyntheticTraceLoader

if TYPE_CHECKING:
    from pathlib import Path

_SEED = 42
_N_TRAIN = 800
_N_EVAL = 300
_LOAD = 0.7
_CONCURRENCY_POINTS = [1, 2, 4, 8, 16]
_SMOKE_CONCURRENCY_POINTS = [1, 4, 16]

_SCHED_COLORS = {
    "fcfs": "#888888",
    "lambdarank": "#F44336",
}
_SCHED_LABELS = {
    "fcfs": "FCFS",
    "lambdarank": "LambdaRank (ours)",
}


def run_experiment(
    n_train: int = _N_TRAIN,
    n_eval: int = _N_EVAL,
    load: float = _LOAD,
    concurrency_points: list[int] | None = None,
    seed: int = _SEED,
) -> dict[str, Any]:
    """Run the JCT vs concurrency sweep and return a results dict.

    Args:
        n_train: Size of the training slice of the synthetic trace.
        n_eval: Size of the evaluation slice replayed through the simulator.
        load: Fixed queue load rho used when spacing eval arrivals.
        concurrency_points: List of worker counts to sweep. Defaults to
            {1, 2, 4, 8, 16}.
        seed: Reproducibility seed; passed to trace loader, simulator, and
            scheduler(s).
    """
    if concurrency_points is None:
        concurrency_points = list(_CONCURRENCY_POINTS)

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

    def _build_schedulers() -> list[BaseScheduler]:
        return [
            FCFSScheduler(),
            LambdaRankScheduler(
                ranker,
                type_means=type_means,
                type_p95s=type_p95s,
                type_counts=type_counts,
            ),
        ]

    metrics: dict[str, dict[str, list]] = {
        sched.name: {"mean_jct": [], "p99_jct": [], "hol_count": []}
        for sched in _build_schedulers()
    }

    for n_workers in concurrency_points:
        # Scale offered load with worker count so per-worker utilisation
        # stays at ``load``.  Otherwise the effective load collapses to
        # ``load / n_workers`` and every scheduler converges as the queue
        # empties — the experiment becomes uninteresting past concurrency=1.
        effective_load = load * n_workers
        for sched in _build_schedulers():
            jobs = _make_jobs(eval_trace, mean_true, effective_load)
            result = Simulator(sched, seed=seed, n_workers=n_workers).run(jobs)
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
        "load_per_worker": load,
        "concurrency_points": concurrency_points,
        "schedulers": metrics,
    }


def _plot(data: dict[str, Any], out_path: Path) -> None:
    import matplotlib.pyplot as plt

    from chronoq_bench.plots.base import save_figure

    cs = data["concurrency_points"]
    schedulers = data["schedulers"]

    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    for name, m in schedulers.items():
        color = _SCHED_COLORS.get(name, "black")
        lw = 2.5 if name == "lambdarank" else 1.5
        axes[0].plot(
            cs,
            m["mean_jct"],
            label=_SCHED_LABELS.get(name, name),
            color=color,
            linewidth=lw,
            marker="o",
            markersize=5,
        )
        axes[1].plot(
            cs,
            m["p99_jct"],
            label=_SCHED_LABELS.get(name, name),
            color=color,
            linewidth=lw,
            marker="o",
            markersize=5,
        )

    for ax, ylabel in zip(axes, ["Mean JCT (ms)", "p99 JCT (ms)"], strict=True):
        ax.set_xlabel("Worker concurrency (N parallel workers)")
        ax.set_ylabel(ylabel)
        ax.set_xscale("log", base=2)
        ax.set_xticks(cs)
        ax.set_xticklabels([str(c) for c in cs])
        ax.legend(fontsize=9)
        ax.grid(alpha=0.3)

    axes[0].set_title("Mean JCT vs Concurrency")
    axes[1].set_title("p99 JCT vs Concurrency")
    fig.suptitle(
        f"chronoq-ranker: LambdaRank vs FCFS across Celery-style worker "
        f"concurrency (per-worker rho={data['load_per_worker']})",
        fontsize=12,
        fontweight="bold",
    )
    fig.tight_layout()
    save_figure(fig, out_path)
    print(f"Saved {out_path}")


def _print_criteria(data: dict[str, Any]) -> None:
    cs = data["concurrency_points"]
    s = data["schedulers"]

    def _imp(base: float, cand: float) -> float:
        return (base - cand) / base * 100 if base > 0 else float("nan")

    print(f"\n=== Concurrency Sweep (per-worker rho={data['load_per_worker']}) ===")
    print(
        f"  {'workers':>8}  {'FCFS mean':>10}  {'LR mean':>10}  "
        f"{'d% mean':>8}  {'FCFS p99':>10}  {'LR p99':>10}  {'d% p99':>8}"
    )
    for i, n in enumerate(cs):
        fm = s["fcfs"]["mean_jct"][i]
        lm = s["lambdarank"]["mean_jct"][i]
        fp = s["fcfs"]["p99_jct"][i]
        lp = s["lambdarank"]["p99_jct"][i]
        print(
            f"  {n:>8d}  {fm:>10.1f}  {lm:>10.1f}  {_imp(fm, lm):>+7.1f}%  "
            f"{fp:>10.1f}  {lp:>10.1f}  {_imp(fp, lp):>+7.1f}%"
        )


def main() -> None:
    smoke = os.getenv("CHRONOQ_BENCH_SMOKE") == "1"
    n_train = 200 if smoke else _N_TRAIN
    n_eval = 100 if smoke else _N_EVAL
    concurrency_points = _SMOKE_CONCURRENCY_POINTS if smoke else list(_CONCURRENCY_POINTS)

    print(
        f"jct_vs_concurrency: n_train={n_train}, n_eval={n_eval}, "
        f"load={_LOAD}, concurrency={concurrency_points}"
    )
    data = run_experiment(
        n_train=n_train,
        n_eval=n_eval,
        load=_LOAD,
        concurrency_points=concurrency_points,
    )

    artifacts = ensure_artifacts_dir()
    results_path = artifacts / "results_concurrency.json"
    results_path.write_text(json.dumps(data, indent=2))
    print(f"Wrote {results_path}")

    _plot(data, artifacts / "jct_vs_concurrency.png")
    _print_criteria(data)


if __name__ == "__main__":
    main()
