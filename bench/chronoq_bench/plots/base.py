"""Matplotlib output helpers shared across experiments."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    import matplotlib.axes
    import matplotlib.figure


def save_figure(fig: matplotlib.figure.Figure, path: Path, dpi: int = 150) -> None:
    """Save figure and close it; create parent dirs if needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=dpi, bbox_inches="tight")
    import matplotlib.pyplot as plt

    plt.close(fig)


def plot_with_band(
    ax: matplotlib.axes.Axes,
    xs: Sequence[float],
    ys_per_seed: Sequence[Sequence[float]],
    *,
    label: str,
    color: str,
    linewidth: float = 1.5,
) -> None:
    """Plot the median across seeds as a line and shade a ±1σ band around it.

    Args:
        ax: Matplotlib axes to draw on.
        xs: X-axis values (one per load point), length ``n_load_points``.
        ys_per_seed: Nested sequence shaped ``[n_load_points][n_seeds]``. The
            outer dim matches ``xs``; the inner dim is the per-seed samples.
        label: Legend label for the median line.
        color: Matplotlib color for both line and band.
        linewidth: Line width for the median curve (default 1.5).

    Notes:
        - The band uses sample standard deviation (``np.std`` with ddof=0) —
          fine for visual error bars; not a confidence interval.
        - When ``n_seeds == 1`` the band collapses to zero width; the line is
          still drawn so a single-seed smoke run renders without crashing.
        - Band alpha is fixed at 0.2 so overlapping bands remain readable.
    """
    arr = np.asarray(ys_per_seed, dtype=float)
    if arr.ndim != 2:
        raise ValueError(f"ys_per_seed must be 2D [n_load_points][n_seeds]; got shape {arr.shape}")
    if arr.shape[0] != len(xs):
        raise ValueError(f"ys_per_seed outer dim ({arr.shape[0]}) must match len(xs) ({len(xs)})")

    medians = np.median(arr, axis=1)
    stds = np.std(arr, axis=1)

    ax.plot(
        xs,
        medians,
        label=label,
        color=color,
        linewidth=linewidth,
        marker="o",
        markersize=4,
    )
    ax.fill_between(
        xs,
        medians - stds,
        medians + stds,
        color=color,
        alpha=0.2,
        linewidth=0,
    )
