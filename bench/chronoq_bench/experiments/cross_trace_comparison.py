"""Cross-trace comparison experiment — publication-quality bar chart.

Reads existing ``bench/artifacts/results_*.json`` files (no simulation re-run)
and emits a two-panel grouped bar chart comparing LambdaRank vs FCFS across
all 6 benchmarked workloads at ρ=0.7 and ρ=0.8.

Left panel : mean JCT improvement (%) — the "does it help?" story.
Right panel: p99 JCT improvement (%) — the SJF-family tail tradeoff.

Both panels share the same trace ordering on the x-axis. Positive bars are
green (LambdaRank faster), negative bars are red (LambdaRank slower).
Lighter bars = ρ=0.7; solid bars = ρ=0.8.

Outputs
-------
bench/artifacts/cross_trace_comparison.png   — local regeneration artifact
docs/assets/cross_trace_comparison.png       — committed artifact for README/docs

Usage
-----
    uv run python -m chronoq_bench.experiments.cross_trace_comparison
"""

from __future__ import annotations

import json
import statistics
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import matplotlib.axes

_BENCH_ROOT = Path(__file__).parent.parent.parent
_ARTIFACTS_DIR = _BENCH_ROOT / "artifacts"
_DOCS_ASSETS_DIR = _BENCH_ROOT.parent / "docs" / "assets"

_TRACE_FILES: dict[str, str] = {
    "Synthetic": "results.json",
    "BurstGPT": "results_burstgpt.json",
    "Borg": "results_borg.json",
    "Azure": "results_azure.json",
    "Helios": "results_helios.json",
    "Philly": "results_philly.json",
}

_RHO_07_IDX = 4  # load_points[4] == 0.7
_RHO_08_IDX = 5  # load_points[5] == 0.8

_GREEN = "#2ca02c"
_RED = "#d62728"
_ALPHA_07 = 0.55
_ALPHA_08 = 1.0


def _load_improvement(path: Path, load_idx: int) -> tuple[float, float]:
    """Return (mean_jct_imp_pct, p99_jct_imp_pct) vs FCFS at *load_idx*."""
    with open(path) as fh:
        d = json.load(fh)

    def _median(sched: str, metric: str) -> float:
        vals = d["schedulers"][sched][metric]
        row = vals[load_idx]
        if isinstance(row, list):
            return statistics.median(row)
        return float(row)

    def _get(sched: str, metric: str) -> float:
        med_key = f"{metric}_median"
        sched_data = d["schedulers"][sched]
        if med_key in sched_data:
            v = sched_data[med_key][load_idx]
            return float(v) if not isinstance(v, list) else statistics.median(v)
        return _median(sched, metric)

    fcfs_mean = _get("fcfs", "mean_jct")
    lr_mean = _get("lambdarank", "mean_jct")
    fcfs_p99 = _get("fcfs", "p99_jct")
    lr_p99 = _get("lambdarank", "p99_jct")

    mean_imp = (fcfs_mean - lr_mean) / fcfs_mean * 100
    p99_imp = (fcfs_p99 - lr_p99) / fcfs_p99 * 100
    return round(mean_imp, 1), round(p99_imp, 1)


def _bar_color(value: float, alpha: float) -> tuple[float, float, float, float]:
    """Return RGBA color: green for positive, red for negative."""
    import matplotlib.colors as mcolors

    hex_color = _GREEN if value >= 0 else _RED
    r, g, b = mcolors.to_rgb(hex_color)
    return (r, g, b, alpha)


def _draw_panel(
    ax: matplotlib.axes.Axes,
    traces: list[str],
    vals_07: list[float],
    vals_08: list[float],
    *,
    title: str,
    ylabel: str,
) -> None:
    """Draw one grouped-bar panel onto *ax*."""
    import numpy as np

    x = np.arange(len(traces))
    width = 0.35
    all_vals = vals_07 + vals_08

    # Add 18% headroom above the max and 22% below the min so labels fit.
    y_min = min(all_vals)
    y_max = max(all_vals)
    span = max(y_max - y_min, 5.0)
    ax.set_ylim(y_min - span * 0.22, y_max + span * 0.18)

    for i, (v07, v08) in enumerate(zip(vals_07, vals_08, strict=True)):
        ax.bar(
            x[i] - width / 2,
            v07,
            width,
            color=_bar_color(v07, _ALPHA_07),
            edgecolor="white",
            linewidth=0.5,
        )
        ax.bar(
            x[i] + width / 2,
            v08,
            width,
            color=_bar_color(v08, _ALPHA_08),
            edgecolor="white",
            linewidth=0.5,
        )
        ylim_lo, ylim_hi = ax.get_ylim()
        label_pad = span * 0.04
        for offset, val in ((-width / 2, v07), (width / 2, v08)):
            sign = "+" if val >= 0 else ""
            label_y = val + label_pad if val >= 0 else val - label_pad
            # Clamp label inside axes so it doesn't vanish off-screen.
            label_y = max(ylim_lo + label_pad, min(ylim_hi - label_pad, label_y))
            ax.text(
                x[i] + offset,
                label_y,
                f"{sign}{val:.1f}%",
                ha="center",
                va="bottom" if val >= 0 else "top",
                fontsize=7.5,
                fontweight="bold",
                color="#333333",
            )

    ax.axhline(0, color="black", linewidth=1.0, zorder=3)
    ax.set_xticks(x)
    ax.set_xticklabels(traces, fontsize=10)
    ax.set_ylabel(ylabel, fontsize=10)
    ax.set_title(title, fontsize=11, fontweight="bold", pad=8)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(axis="y", linestyle="--", alpha=0.4, linewidth=0.7)
    ax.set_axisbelow(True)


def run_experiment() -> None:
    """Generate the cross-trace comparison chart and write both output PNGs."""
    import matplotlib.pyplot as plt

    traces: list[str] = []
    mean_07: list[float] = []
    mean_08: list[float] = []
    p99_07: list[float] = []
    p99_08: list[float] = []

    for label, filename in _TRACE_FILES.items():
        path = _ARTIFACTS_DIR / filename
        if not path.exists():
            print(f"  WARNING: {path} not found — skipping {label}")
            continue
        m07, p07 = _load_improvement(path, _RHO_07_IDX)
        m08, p08 = _load_improvement(path, _RHO_08_IDX)
        traces.append(label)
        mean_07.append(m07)
        mean_08.append(m08)
        p99_07.append(p07)
        p99_08.append(p08)

    fig, (ax_mean, ax_p99) = plt.subplots(1, 2, figsize=(15, 6))
    fig.suptitle(
        "LambdaRank vs FCFS — 6 workloads, 2 load regimes",
        fontsize=13,
        fontweight="bold",
        y=1.01,
    )

    _draw_panel(
        ax_mean,
        traces,
        mean_07,
        mean_08,
        title="Mean JCT improvement vs FCFS",
        ylabel="Improvement vs FCFS (%)",
    )
    _draw_panel(
        ax_p99,
        traces,
        p99_07,
        p99_08,
        title="p99 JCT improvement vs FCFS",
        ylabel="Improvement vs FCFS (%)",
    )

    from matplotlib.colors import to_rgb
    from matplotlib.patches import Patch

    legend_handles = [
        Patch(facecolor=(*to_rgb(_GREEN), _ALPHA_07), label="ρ = 0.7"),
        Patch(facecolor=(*to_rgb(_GREEN), _ALPHA_08), label="ρ = 0.8"),
        Patch(facecolor=_RED, label="LR worse than FCFS"),
    ]
    fig.legend(
        handles=legend_handles,
        loc="lower center",
        ncol=3,
        fontsize=9,
        frameon=False,
        bbox_to_anchor=(0.5, -0.04),
    )

    fig.text(
        0.5,
        -0.09,
        "n_train=800 · n_eval=300 · 10 seeds [42–51] · median across seeds"
        " · positive = LambdaRank faster",
        ha="center",
        fontsize=8.5,
        color="#555555",
    )

    fig.tight_layout()

    from chronoq_bench.plots.base import save_figure

    _ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    artifact_path = _ARTIFACTS_DIR / "cross_trace_comparison.png"
    save_figure(fig, artifact_path, dpi=150)
    print(f"  written: {artifact_path}")

    _DOCS_ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    import shutil

    shutil.copy2(artifact_path, _DOCS_ASSETS_DIR / "cross_trace_comparison.png")
    print(f"  written: {_DOCS_ASSETS_DIR / 'cross_trace_comparison.png'}")

    print(
        f"cross-trace comparison: {len(traces)} traces, ρ ∈ {{0.7, 0.8}}"
        f" — written to docs/assets/cross_trace_comparison.png"
    )


if __name__ == "__main__":
    run_experiment()
