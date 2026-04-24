"""JCT vs load experiment — the money plot.

Sweeps queue load 0.3 → 0.9 across 6 schedulers (FCFS, SJF-oracle, SRPT-approx,
random, priority+FCFS, LambdaRank) using a pluggable ``TraceLoader`` (default:
synthetic Pareto). Runs each load point across multiple seeds so the reader can
see ±1σ error bands on the hero plot.

Outputs:
  bench/artifacts/jct_vs_load.png  — median lines + ±1σ shaded bands
  bench/artifacts/results.json     — per-seed arrays + median back-compat arrays

Usage:
    uv run python -m chronoq_bench.experiments.jct_vs_load        # full (~15 min, 10 seeds)
    CHRONOQ_BENCH_SMOKE=1 uv run python ...                        # CI smoke (<30s, 1 seed)
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

    from chronoq_bench.traces.base import TraceJob, TraceLoader

_SEED = 42
_N_TRAIN = 800
_N_EVAL = 300
_LOAD_POINTS = [0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]
_GROUP_SIZE = 25
_DEFAULT_SEEDS = [42, 43, 44, 45, 46, 47, 48, 49, 50, 51]
_METRIC_KEYS = ("mean_jct", "p99_jct", "hol_count")
# Schedulers that deserve error bands on the money plot. Other schedulers
# render as plain lines to keep the legend readable.
_BAND_SCHEDULERS = {"fcfs", "lambdarank"}

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


def _run_one_seed(
    loader: TraceLoader,
    n_train: int,
    n_eval: int,
    load_points: list[float],
    seed: int,
) -> dict[str, dict[str, list[float]]]:
    """Execute a single-seed sweep and return per-scheduler metric lists.

    Shape of return: ``{sched_name: {metric: [one_value_per_load_point]}}``.
    """
    all_trace = loader.load(n=n_train + n_eval)
    if len(all_trace) < n_train + n_eval:
        raise ValueError(
            f"Loader {type(loader).__name__} returned {len(all_trace)} jobs; "
            f"need at least {n_train + n_eval} (n_train={n_train} + n_eval={n_eval})"
        )

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

    metrics: dict[str, dict[str, list[float]]] = {
        sched.name: {metric: [] for metric in _METRIC_KEYS} for sched in schedulers
    }

    for load in load_points:
        for sched in schedulers:
            jobs = _make_jobs(eval_trace, mean_true, load)
            result = Simulator(sched, seed=seed).run(jobs)
            jcts = result.jct_ms
            metrics[sched.name]["mean_jct"].append(round(mean_jct(jcts), 2))
            metrics[sched.name]["p99_jct"].append(round(p99_jct(jcts), 2))
            metrics[sched.name]["hol_count"].append(hol_blocking_count(jcts))

    return metrics


def _make_default_loader(seed: int, n_total: int) -> TraceLoader:
    """Build the fall-back synthetic loader when caller doesn't supply one."""
    return SyntheticTraceLoader(n_jobs=n_total, seed=seed)


def _stack_seeds(
    per_seed_metrics: list[dict[str, dict[str, list[float]]]],
    scheduler_names: list[str],
    load_points: list[float],
) -> dict[str, dict[str, list[list[float]]]]:
    """Re-shape per-seed metric dicts into ``[load_idx][seed_idx]`` arrays.

    Given a list of seeds where each entry is
    ``{sched: {metric: [per_load_value, ...]}}``, produce
    ``{sched: {metric: [[per_seed_value, ...], ...]}}`` whose outer dim is the
    load point and inner dim is the seed — the shape expected by
    ``plot_with_band`` and the schema agreed for ``results.json``.
    """
    stacked: dict[str, dict[str, list[list[float]]]] = {
        name: {metric: [[] for _ in load_points] for metric in _METRIC_KEYS}
        for name in scheduler_names
    }
    for sm in per_seed_metrics:
        for sched in scheduler_names:
            for metric in _METRIC_KEYS:
                values = sm[sched][metric]
                for load_idx, v in enumerate(values):
                    stacked[sched][metric][load_idx].append(float(v))
    return stacked


def _median_flat(
    stacked: dict[str, dict[str, list[list[float]]]],
) -> dict[str, dict[str, list[float]]]:
    """Collapse per-seed arrays to median-across-seeds flat arrays.

    Emitted as ``*_median`` fields so downstream consumers that still assume the
    old flat ``list[float]`` shape (e.g. older CI scrapers, ad-hoc plots) don't
    have to reshape.
    """
    out: dict[str, dict[str, list[float]]] = {}
    for sched, by_metric in stacked.items():
        out[sched] = {}
        for metric, per_load in by_metric.items():
            out[sched][f"{metric}_median"] = [round(float(np.median(col)), 2) for col in per_load]
    return out


def run_experiment(
    n_train: int = _N_TRAIN,
    n_eval: int = _N_EVAL,
    load_points: list[float] | None = None,
    seed: int = _SEED,
    loader: TraceLoader | None = None,
    seeds: list[int] | None = None,
) -> dict[str, Any]:
    """Run the JCT vs load sweep over multiple seeds and return a results dict.

    Args:
        n_train: Number of jobs to carve off the head of the trace for training.
        n_eval: Number of jobs (after ``n_train``) used for the simulation sweep.
        load_points: Queue-load fractions to simulate (default 0.3 → 0.9).
        seed: Legacy single-seed parameter. When ``seeds`` is also ``None`` the
            sweep runs with just this seed; otherwise ``seeds`` wins. Still
            accepted so existing callers that pass ``seed=...`` keep working.
        loader: Any ``TraceLoader``. When omitted, a fresh synthetic loader is
            built per seed so every seed sees independent jobs. Pass a
            pre-built loader to share the same trace across seeds (e.g. a
            BurstGPT parquet cache).
        seeds: Explicit list of seeds. Defaults to 10 consecutive seeds
            ``[42..51]`` which takes ~15 min on an 8-core laptop for the full
            sweep.

    Results shape:
        ``schedulers[name][metric]`` is ``list[list[float]]`` with outer dim =
        load points and inner dim = seeds. A flat ``*_median`` mirror is also
        written for back-compat with legacy flat-array readers.
    """
    if load_points is None:
        load_points = _LOAD_POINTS
    if seeds is None:
        seeds = [seed]

    per_seed_metrics: list[dict[str, dict[str, list[float]]]] = []
    for s in seeds:
        trace_loader = (
            loader if loader is not None else _make_default_loader(seed=s, n_total=n_train + n_eval)
        )
        metrics = _run_one_seed(
            loader=trace_loader,
            n_train=n_train,
            n_eval=n_eval,
            load_points=load_points,
            seed=s,
        )
        per_seed_metrics.append(metrics)

    scheduler_names = list(per_seed_metrics[0].keys())
    stacked = _stack_seeds(per_seed_metrics, scheduler_names, load_points)
    medians = _median_flat(stacked)

    # Merge stacked arrays + median back-compat into a single per-scheduler dict
    merged: dict[str, dict[str, list]] = {
        name: {**stacked[name], **medians[name]} for name in scheduler_names
    }

    schema = DEFAULT_SCHEMA_V1
    # Use first seed's loader-name for reporting. When the caller shares a
    # pre-built loader, that's its name; otherwise the synthetic factory reports
    # "synthetic_pareto" regardless of seed.
    reporting_loader = (
        loader
        if loader is not None
        else _make_default_loader(seed=seeds[0], n_total=n_train + n_eval)
    )
    return {
        "trace": reporting_loader.name,
        "seed": seeds[0],  # back-compat: original "seed" field retained
        "seeds": list(seeds),
        "n_seeds": len(seeds),
        "feature_schema_version": schema.version,
        "n_features": len(schema.numeric) + len(schema.categorical),
        "n_training_jobs": n_train,
        "n_eval_jobs": n_eval,
        "load_points": load_points,
        "schedulers": merged,
    }


def _plot(data: dict[str, Any], out_path: Path) -> None:
    import matplotlib.pyplot as plt

    from chronoq_bench.plots.base import plot_with_band, save_figure

    load_pts = data["load_points"]
    schedulers = data["schedulers"]
    n_seeds = data.get("n_seeds", 1)

    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    for name, m in schedulers.items():
        color = _SCHED_COLORS.get(name, "black")
        lw = 2.5 if name == "lambdarank" else 1.5
        label = _SCHED_LABELS.get(name, name)

        if name in _BAND_SCHEDULERS and n_seeds > 1:
            plot_with_band(axes[0], load_pts, m["mean_jct"], label=label, color=color, linewidth=lw)
            plot_with_band(axes[1], load_pts, m["p99_jct"], label=label, color=color, linewidth=lw)
        else:
            # Non-band schedulers — use medians to render a single line.
            mean_line = m.get("mean_jct_median", [np.median(col) for col in m["mean_jct"]])
            p99_line = m.get("p99_jct_median", [np.median(col) for col in m["p99_jct"]])
            axes[0].plot(
                load_pts,
                mean_line,
                label=label,
                color=color,
                linewidth=lw,
                marker="o",
                markersize=4,
            )
            axes[1].plot(
                load_pts,
                p99_line,
                label=label,
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

    band_note = f"n={n_seeds} seeds, ±1σ band" if n_seeds > 1 else f"n={n_seeds} seed"
    axes[0].set_title(f"Mean JCT vs Load ({band_note})")
    axes[1].set_title(f"p99 JCT vs Load ({band_note})")
    trace_label = data.get("trace", "synthetic").replace("_", " ").title()
    fig.suptitle(
        f"chronoq-ranker: LambdaRank vs Baselines ({trace_label} Trace)",
        fontsize=12,
        fontweight="bold",
    )
    fig.tight_layout()
    save_figure(fig, out_path)
    print(f"Saved {out_path}")


def _print_criteria(data: dict[str, Any]) -> None:
    """Report median-across-seeds gates and fail loud on any per-seed violation.

    The median number is the headline for the README. The per-seed check is a
    reproducibility guardrail: a single seed that violates the gate is a red
    flag worth investigating (usually high-variance at that load).
    """
    load_pts = data["load_points"]
    s = data["schedulers"]
    seeds = data.get("seeds", [data.get("seed")])

    def _median(sched: str, metric: str, load: float) -> float:
        if load not in load_pts:
            return float("nan")
        key = f"{metric}_median"
        if key in s[sched]:
            return float(s[sched][key][load_pts.index(load)])
        # Fallback: compute on the fly (useful in unit tests)
        col = s[sched][metric][load_pts.index(load)]
        return float(np.median(col))

    def _per_seed(sched: str, metric: str, load: float) -> list[float]:
        if load not in load_pts:
            return []
        col = s[sched][metric][load_pts.index(load)]
        return list(col) if isinstance(col, list) else [float(col)]

    def _imp(base: float, cand: float) -> float:
        return (base - cand) / base * 100 if base > 0 else float("nan")

    def _check(
        label: str,
        base_sched: str,
        cand_sched: str,
        metric: str,
        load: float,
        *,
        target_pct: float,
        direction: str = "ge",
    ) -> None:
        base_med = _median(base_sched, metric, load)
        cand_med = _median(cand_sched, metric, load)
        median_pct = _imp(base_med, cand_med)
        print(
            f"  {label}: median {median_pct:+.1f}%  (target "
            f"{'≥' if direction == 'ge' else '≤'}{'+' if target_pct > 0 else ''}{target_pct:.0f}%)"
        )

        # Per-seed: compute improvement seed-by-seed
        bases = _per_seed(base_sched, metric, load)
        cands = _per_seed(cand_sched, metric, load)
        violations: list[str] = []
        for seed_idx, (b, c) in enumerate(zip(bases, cands, strict=True)):
            pct = _imp(b, c)
            ok = pct >= target_pct if direction == "ge" else pct <= target_pct
            if not ok:
                seed_val = seeds[seed_idx] if seed_idx < len(seeds) else seed_idx
                violations.append(f"seed={seed_val} ({pct:+.1f}%)")
        if violations:
            print(f"    ! per-seed gate violations: {', '.join(violations)}")

    def _check_ratio(
        label: str, num_sched: str, denom_sched: str, metric: str, load: float, *, target_pct: float
    ) -> None:
        num = _median(num_sched, metric, load)
        den = _median(denom_sched, metric, load)
        gap = abs(num - den) / den * 100 if den > 0 else float("nan")
        print(f"  {label}: median {gap:.1f}%  (target ≤{target_pct:.0f}%)")
        nums = _per_seed(num_sched, metric, load)
        dens = _per_seed(denom_sched, metric, load)
        violations: list[str] = []
        for seed_idx, (n, d) in enumerate(zip(nums, dens, strict=True)):
            g = abs(n - d) / d * 100 if d > 0 else float("nan")
            if g > target_pct:
                seed_val = seeds[seed_idx] if seed_idx < len(seeds) else seed_idx
                violations.append(f"seed={seed_val} ({g:.1f}%)")
        if violations:
            print(f"    ! per-seed gate violations: {', '.join(violations)}")

    print("\n=== Exit Criteria ===")
    _check(
        "mean JCT vs FCFS @ 0.7",
        "fcfs",
        "lambdarank",
        "mean_jct",
        0.7,
        target_pct=10.0,
    )
    _check(
        "p99  JCT vs FCFS @ 0.7",
        "fcfs",
        "lambdarank",
        "p99_jct",
        0.7,
        target_pct=15.0,
    )
    _check_ratio(
        "p99 gap vs SJF-oracle @ 0.7",
        "lambdarank",
        "sjf_oracle",
        "p99_jct",
        0.7,
        target_pct=20.0,
    )
    if 0.5 in load_pts:
        _check(
            "p99  JCT vs FCFS @ 0.5",
            "fcfs",
            "lambdarank",
            "p99_jct",
            0.5,
            target_pct=15.0,
        )


def _build_loader(trace_name: str) -> TraceLoader | None:
    """Resolve a trace name to a TraceLoader instance.

    Returns None for "synthetic" (caller uses per-seed fresh loaders).
    """
    if trace_name == "synthetic":
        return None
    if trace_name == "burstgpt":
        from chronoq_bench.traces.burstgpt import BurstGPTLoader

        return BurstGPTLoader()
    if trace_name == "borg":
        from chronoq_bench.traces.borg import BorgLoader

        return BorgLoader()
    if trace_name == "azure":
        from chronoq_bench.traces.azure import AzureLoader

        return AzureLoader()
    raise ValueError(
        f"Unknown trace '{trace_name}'. Choices: synthetic, burstgpt, borg, azure"
    )


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="JCT vs load benchmark sweep.")
    parser.add_argument(
        "--trace",
        choices=["synthetic", "burstgpt", "borg", "azure"],
        default="synthetic",
        help="Trace loader to use (default: synthetic Pareto).",
    )
    args = parser.parse_args()

    smoke = os.getenv("CHRONOQ_BENCH_SMOKE") == "1"
    n_train = 200 if smoke else _N_TRAIN
    n_eval = 100 if smoke else _N_EVAL
    load_pts = [0.5, 0.7] if smoke else _LOAD_POINTS
    seeds = [_SEED] if smoke else _DEFAULT_SEEDS

    loader = _build_loader(args.trace)

    print(
        f"jct_vs_load: trace={args.trace}, n_train={n_train}, n_eval={n_eval}, "
        f"load_points={load_pts}, n_seeds={len(seeds)}"
    )
    data = run_experiment(
        n_train=n_train,
        n_eval=n_eval,
        load_points=load_pts,
        seeds=seeds,
        loader=loader,
    )

    trace_suffix = "" if args.trace == "synthetic" else f"_{args.trace}"
    artifacts = ensure_artifacts_dir()
    results_path = artifacts / f"results{trace_suffix}.json"
    results_path.write_text(json.dumps(data, indent=2))
    print(f"Wrote {results_path}")

    _plot(data, artifacts / f"jct_vs_load{trace_suffix}.png")
    _print_criteria(data)


if __name__ == "__main__":
    main()
