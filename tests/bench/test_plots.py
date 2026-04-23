"""Tests for plotting helpers."""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")  # headless backend — safe for CI

import matplotlib.pyplot as plt
import pytest
from chronoq_bench.plots.base import plot_with_band


def test_plot_with_band_accepts_expected_shape() -> None:
    """Shape [n_load_points][n_seeds] must plot without error."""
    fig, ax = plt.subplots()
    try:
        xs = [0.3, 0.5, 0.7]
        ys_per_seed = [
            [100.0, 110.0, 95.0],  # load=0.3 across 3 seeds
            [150.0, 160.0, 145.0],  # load=0.5 across 3 seeds
            [200.0, 210.0, 195.0],  # load=0.7 across 3 seeds
        ]
        plot_with_band(ax, xs, ys_per_seed, label="demo", color="#F44336")
        # One line (median) + one PolyCollection (fill_between band)
        assert len(ax.lines) == 1
        assert any("PolyCollection" in type(c).__name__ for c in ax.collections), (
            "fill_between band not drawn"
        )
    finally:
        plt.close(fig)


def test_plot_with_band_single_seed() -> None:
    """Degenerate case — 1 seed per point — should still render (zero-width band)."""
    fig, ax = plt.subplots()
    try:
        xs = [0.3, 0.5]
        ys_per_seed = [[100.0], [150.0]]
        plot_with_band(ax, xs, ys_per_seed, label="smoke", color="#888")
        assert len(ax.lines) == 1
    finally:
        plt.close(fig)


def test_plot_with_band_rejects_1d_input() -> None:
    """Passing a flat list (not [load][seed]) is a caller error."""
    fig, ax = plt.subplots()
    try:
        with pytest.raises(ValueError, match="must be 2D"):
            plot_with_band(ax, [0.3, 0.5], [100.0, 150.0], label="bad", color="#000")
    finally:
        plt.close(fig)


def test_plot_with_band_rejects_shape_mismatch() -> None:
    """xs and outer dim of ys_per_seed must agree."""
    fig, ax = plt.subplots()
    try:
        with pytest.raises(ValueError, match="must match len"):
            plot_with_band(
                ax,
                [0.3, 0.5, 0.7],  # 3 x-values
                [[100.0, 110.0], [150.0, 160.0]],  # only 2 load points
                label="bad",
                color="#000",
            )
    finally:
        plt.close(fig)
