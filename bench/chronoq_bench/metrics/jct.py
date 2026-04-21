"""Job Completion Time (JCT) metrics.

All functions operate on plain lists/arrays — no simulator or trace dependency.
"""

from __future__ import annotations

import math


def mean_jct(completion_times_ms: list[float]) -> float:
    """Arithmetic mean JCT in ms."""
    if not completion_times_ms:
        return 0.0
    return sum(completion_times_ms) / len(completion_times_ms)


def percentile_jct(completion_times_ms: list[float], p: float) -> float:
    """p-th percentile JCT (0 ≤ p ≤ 100). Uses nearest-rank method."""
    if not completion_times_ms:
        return 0.0
    sorted_ms = sorted(completion_times_ms)
    n = len(sorted_ms)
    idx = max(0, math.ceil(p / 100.0 * n) - 1)
    return sorted_ms[idx]


def p50_jct(completion_times_ms: list[float]) -> float:
    return percentile_jct(completion_times_ms, 50)


def p95_jct(completion_times_ms: list[float]) -> float:
    return percentile_jct(completion_times_ms, 95)


def p99_jct(completion_times_ms: list[float]) -> float:
    return percentile_jct(completion_times_ms, 99)


def hol_blocking_count(
    completion_times_ms: list[float],
    threshold_multiplier: float = 3.0,
) -> int:
    """Number of jobs whose JCT exceeds threshold_multiplier × mean JCT.

    A job is "head-of-line blocked" if it waited far longer than average —
    a proxy for being stuck behind a large job.
    """
    if not completion_times_ms:
        return 0
    mean = mean_jct(completion_times_ms)
    if mean == 0.0:
        return 0
    threshold = mean * threshold_multiplier
    return sum(1 for jct in completion_times_ms if jct > threshold)


def jains_fairness_index(completion_times_ms: list[float]) -> float:
    """Jain's fairness index ∈ (0, 1]. 1.0 = perfectly fair (all JCTs equal).

    J = (Σxᵢ)² / (n · Σxᵢ²)
    """
    if not completion_times_ms:
        return 1.0
    n = len(completion_times_ms)
    s1 = sum(completion_times_ms)
    s2 = sum(x * x for x in completion_times_ms)
    if s2 == 0.0:
        return 1.0
    return (s1 * s1) / (n * s2)


def summarise(completion_times_ms: list[float]) -> dict[str, float]:
    """Return all JCT metrics as a dict."""
    return {
        "mean_jct": mean_jct(completion_times_ms),
        "p50_jct": p50_jct(completion_times_ms),
        "p95_jct": p95_jct(completion_times_ms),
        "p99_jct": p99_jct(completion_times_ms),
        "hol_blocking_count": float(hol_blocking_count(completion_times_ms)),
        "jains_fairness": jains_fairness_index(completion_times_ms),
        "n_jobs": float(len(completion_times_ms)),
    }
