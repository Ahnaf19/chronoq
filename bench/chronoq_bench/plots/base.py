"""Matplotlib output helpers shared across experiments."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    import matplotlib.figure


def save_figure(fig: matplotlib.figure.Figure, path: Path, dpi: int = 150) -> None:
    """Save figure and close it; create parent dirs if needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=dpi, bbox_inches="tight")
    import matplotlib.pyplot as plt

    plt.close(fig)
