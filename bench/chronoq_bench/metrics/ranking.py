"""Ranking quality metrics for bench experiments.

Thin wrappers that import from chronoq_ranker's internal helpers so we don't
duplicate the numpy argsort-based implementations.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from collections.abc import Sequence
from chronoq_ranker.models.lambdarank import (
    _kendall_tau_grouped,
    _pairwise_accuracy_grouped,
    _spearman_rho,
    _spearman_rho_grouped,
)


def spearman_rho(scores: Sequence[float], labels: Sequence[float]) -> float:
    """Spearman ρ between predicted scores and true labels (flat, no groups)."""
    return _spearman_rho(np.array(scores, dtype=np.float64), np.array(labels, dtype=np.float64))


def spearman_rho_grouped(
    scores: Sequence[float], labels: Sequence[float], group_sizes: Sequence[int]
) -> float:
    """Per-group Spearman ρ averaged across groups."""
    return _spearman_rho_grouped(
        np.array(scores, dtype=np.float64),
        np.array(labels, dtype=np.float64),
        np.array(group_sizes, dtype=np.int32),
    )


def kendall_tau_grouped(
    scores: Sequence[float], labels: Sequence[float], group_sizes: Sequence[int]
) -> float:
    """Per-group Kendall τ averaged across groups."""
    return _kendall_tau_grouped(
        np.array(scores, dtype=np.float64),
        np.array(labels, dtype=np.float64),
        np.array(group_sizes, dtype=np.int32),
    )


def pairwise_accuracy_grouped(
    scores: Sequence[float], labels: Sequence[float], group_sizes: Sequence[int]
) -> float:
    """Fraction of within-group pairs correctly ordered."""
    return _pairwise_accuracy_grouped(
        np.array(scores, dtype=np.float64),
        np.array(labels, dtype=np.int32),
        np.array(group_sizes, dtype=np.int32),
    )
