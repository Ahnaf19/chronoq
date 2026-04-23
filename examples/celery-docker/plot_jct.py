"""Plot JCT comparison between FIFO and Chronoq active-mode scheduling.

Reads ``artifacts/run_fifo.csv`` and ``artifacts/run_active.csv`` produced by
the producer, then emits ``artifacts/jct_comparison.png`` with:

  - Panel 1: JCT histogram (fifo vs active, overlaid semi-transparent)
  - Panel 2: Mean + p99 bar chart (2 groups × 2 bars)

Exits with code 1 if the mean JCT improvement is less than 15%.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import numpy as np

ARTIFACTS_DIR = Path(__file__).parent / "artifacts"
FIFO_CSV = ARTIFACTS_DIR / "run_fifo.csv"
ACTIVE_CSV = ARTIFACTS_DIR / "run_active.csv"
OUTPUT_PNG = ARTIFACTS_DIR / "jct_comparison.png"

IMPROVEMENT_GATE = 15.0  # minimum mean JCT improvement (%) to exit 0


def _read_jcts(path: Path) -> np.ndarray:
    """Read the ``jct_ms`` column from a CSV file and return a float array."""
    if not path.exists():
        raise FileNotFoundError(f"CSV not found: {path}")
    jcts: list[float] = []
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            jcts.append(float(row["jct_ms"]))
    if not jcts:
        raise ValueError(f"No rows found in {path}")
    return np.array(jcts, dtype=np.float64)


def _plot(fifo: np.ndarray, active: np.ndarray, out_path: Path) -> None:
    """Produce a two-panel comparison PNG."""
    import matplotlib

    matplotlib.use("Agg")  # headless
    import matplotlib.pyplot as plt

    fifo_mean = float(np.mean(fifo))
    fifo_p99 = float(np.percentile(fifo, 99))
    active_mean = float(np.mean(active))
    active_p99 = float(np.percentile(active, 99))

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))
    fig.suptitle(
        "Celery JCT: FIFO vs Chronoq LambdaRank (500 jobs, wall-clock)",
        fontsize=13,
        fontweight="bold",
    )

    # ---- Panel 1: histogram ------------------------------------------------
    bins = np.linspace(0, max(fifo.max(), active.max()) * 1.05, 60)
    ax1.hist(fifo, bins=bins, alpha=0.55, color="#e07b54", label="FIFO")
    ax1.hist(active, bins=bins, alpha=0.55, color="#5499c7", label="Chronoq active")
    ax1.axvline(
        fifo_mean,
        color="#e07b54",
        linestyle="--",
        linewidth=1.5,
        label=f"FIFO mean {fifo_mean:.0f}ms",
    )
    ax1.axvline(
        active_mean,
        color="#5499c7",
        linestyle="--",
        linewidth=1.5,
        label=f"Active mean {active_mean:.0f}ms",
    )
    ax1.set_xlabel("JCT (ms)")
    ax1.set_ylabel("Count")
    ax1.set_title("JCT distribution")
    ax1.legend(fontsize=9)

    # ---- Panel 2: mean + p99 bar chart -------------------------------------
    x = np.array([0, 1])
    width = 0.35
    bars_mean = ax2.bar(
        x - width / 2,
        [fifo_mean, active_mean],
        width,
        color=["#e07b54", "#5499c7"],
        label="mean JCT",
    )
    bars_p99 = ax2.bar(
        x + width / 2,
        [fifo_p99, active_p99],
        width,
        color=["#e07b54", "#5499c7"],
        alpha=0.55,
        label="p99 JCT",
    )

    ax2.set_xticks(x)
    ax2.set_xticklabels(["FIFO", "Chronoq active"])
    ax2.set_ylabel("JCT (ms)")
    ax2.set_title("Mean and p99 JCT")

    # Annotate bars
    for bar in list(bars_mean) + list(bars_p99):
        h = bar.get_height()
        ax2.annotate(
            f"{h:.0f}",
            xy=(bar.get_x() + bar.get_width() / 2, h),
            xytext=(0, 3),
            textcoords="offset points",
            ha="center",
            va="bottom",
            fontsize=8,
        )

    mean_imp = (fifo_mean - active_mean) / fifo_mean * 100
    p99_imp = (fifo_p99 - active_p99) / fifo_p99 * 100
    ax2.set_title(f"Mean and p99 JCT  (mean imp: {mean_imp:+.1f}%, p99 imp: {p99_imp:+.1f}%)")

    plt.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"[plot] saved {out_path}", flush=True)


def main() -> None:
    fifo = _read_jcts(FIFO_CSV)
    active = _read_jcts(ACTIVE_CSV)

    fifo_mean = float(np.mean(fifo))
    fifo_p99 = float(np.percentile(fifo, 99))
    active_mean = float(np.mean(active))
    active_p99 = float(np.percentile(active, 99))

    mean_imp = (fifo_mean - active_mean) / fifo_mean * 100
    p99_imp = (fifo_p99 - active_p99) / fifo_p99 * 100

    print()
    print("JCT comparison  (wall-clock, 500 jobs, 4 workers)")
    print(f"{'Mode':<12} {'mean_jct':>12} {'p99_jct':>12}")
    print("-" * 38)
    print(f"{'FIFO':<12} {fifo_mean:>10.0f}ms {fifo_p99:>10.0f}ms")
    print(f"{'Active':<12} {active_mean:>10.0f}ms {active_p99:>10.0f}ms")
    print()
    print(f"Mean JCT improvement: {mean_imp:+.1f}%  (gate: ≥{IMPROVEMENT_GATE}%)")
    print(f"P99  JCT improvement: {p99_imp:+.1f}%")
    print()

    _plot(fifo, active, OUTPUT_PNG)

    if mean_imp < IMPROVEMENT_GATE:
        print(
            f"GATE FAIL: mean JCT improvement {mean_imp:.1f}% < {IMPROVEMENT_GATE}% required.",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"GATE PASS: mean JCT improvement {mean_imp:.1f}% >= {IMPROVEMENT_GATE}%.")
    sys.exit(0)


if __name__ == "__main__":
    main()
