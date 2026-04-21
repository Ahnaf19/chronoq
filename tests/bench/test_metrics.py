"""Tests for JCT and ranking metrics."""

import pytest
from chronoq_bench.metrics.jct import (
    hol_blocking_count,
    jains_fairness_index,
    mean_jct,
    p99_jct,
    percentile_jct,
    summarise,
)
from chronoq_bench.metrics.ranking import pairwise_accuracy_grouped, spearman_rho


# ---------------------------------------------------------------------------
# JCT metrics
# ---------------------------------------------------------------------------


def test_mean_jct_basic() -> None:
    assert mean_jct([100.0, 200.0, 300.0]) == pytest.approx(200.0)


def test_mean_jct_empty() -> None:
    assert mean_jct([]) == 0.0


def test_percentile_jct_median() -> None:
    data = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert percentile_jct(data, 50) == 3.0


def test_p99_jct_returns_near_max() -> None:
    data = [float(i) for i in range(1, 101)]
    assert p99_jct(data) == 99.0


def test_percentile_jct_empty() -> None:
    assert percentile_jct([], 99) == 0.0


def test_hol_blocking_count_none_blocked() -> None:
    # All equal durations — none exceeds 3× mean
    assert hol_blocking_count([100.0, 100.0, 100.0]) == 0


def test_hol_blocking_count_one_blocked() -> None:
    # mean=325, threshold=975; 1000 > 975 → 1 blocked
    data = [100.0, 100.0, 100.0, 1000.0]
    assert hol_blocking_count(data) == 1


def test_hol_blocking_count_empty() -> None:
    assert hol_blocking_count([]) == 0


def test_jains_fairness_perfect() -> None:
    # All equal → Jain = 1.0
    assert jains_fairness_index([100.0, 100.0, 100.0]) == pytest.approx(1.0)


def test_jains_fairness_two_extremes() -> None:
    # One job 100ms, one job 10000ms → very unfair
    j = jains_fairness_index([100.0, 10000.0])
    assert j < 0.6


def test_jains_fairness_empty() -> None:
    assert jains_fairness_index([]) == 1.0


def test_summarise_keys() -> None:
    result = summarise([100.0, 200.0, 300.0])
    assert set(result.keys()) == {
        "mean_jct", "p50_jct", "p95_jct", "p99_jct",
        "hol_blocking_count", "jains_fairness", "n_jobs",
    }
    assert result["n_jobs"] == 3.0


def test_summarise_values_consistent() -> None:
    data = [float(i) for i in range(1, 101)]
    s = summarise(data)
    assert s["mean_jct"] == pytest.approx(50.5)
    assert s["p50_jct"] <= s["p95_jct"] <= s["p99_jct"]


# ---------------------------------------------------------------------------
# Ranking metrics
# ---------------------------------------------------------------------------


def test_spearman_rho_perfect() -> None:
    a = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert spearman_rho(a, a) == pytest.approx(1.0, abs=1e-9)


def test_spearman_rho_reversed() -> None:
    a = [1.0, 2.0, 3.0, 4.0, 5.0]
    b = list(reversed(a))
    assert spearman_rho(a, b) == pytest.approx(-1.0, abs=1e-9)


def test_pairwise_accuracy_perfect() -> None:
    labels = [0.0, 1.0, 2.0]
    scores = [0.0, 1.0, 2.0]
    acc = pairwise_accuracy_grouped(scores, labels, [3])
    assert acc == pytest.approx(1.0, abs=1e-9)


def test_pairwise_accuracy_worst() -> None:
    labels = [0.0, 1.0, 2.0]
    scores = [2.0, 1.0, 0.0]  # inverted
    acc = pairwise_accuracy_grouped(scores, labels, [3])
    assert acc == pytest.approx(0.0, abs=1e-9)
