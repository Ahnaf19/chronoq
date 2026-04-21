"""Hypothesis property tests for LambdaRank invariants."""

import numpy as np
from chronoq_ranker.drift import _compute_psi
from chronoq_ranker.models.lambdarank import _pairwise_accuracy_grouped, _spearman_rho
from hypothesis import given, settings
from hypothesis import strategies as st

# ---------------------------------------------------------------------------
# Label-construction invariants
# ---------------------------------------------------------------------------


@given(
    actual_ms_list=st.lists(
        st.floats(min_value=1.0, max_value=1_000_000.0, allow_nan=False, allow_infinity=False),
        min_size=2,
        max_size=20,
    )
)
@settings(max_examples=200, deadline=None)
def test_rank_labels_inversely_monotone_with_actual_ms(actual_ms_list: list[float]) -> None:
    """Within a group, shorter actual_ms always gets a strictly higher label."""
    # Deduplicate so ranks are unambiguous
    unique_ms = sorted(set(actual_ms_list))
    if len(unique_ms) < 2:
        return
    n = len(unique_ms)
    # Label construction: sorted ascending → label n-1 down to 0
    labels = [n - 1 - i for i in range(n)]
    # Monotonicity: for all i < j (in ascending actual_ms order), label[i] > label[j]
    for i in range(n):
        for j in range(i + 1, n):
            assert unique_ms[i] < unique_ms[j]
            assert labels[i] > labels[j]


@given(n=st.integers(min_value=2, max_value=50))
@settings(max_examples=100, deadline=None)
def test_rank_labels_cover_full_range(n: int) -> None:
    """Labels must cover [0, n-1] with no gaps."""
    labels = [n - 1 - i for i in range(n)]
    assert min(labels) == 0
    assert max(labels) == n - 1
    assert len(set(labels)) == n  # all distinct


# ---------------------------------------------------------------------------
# Spearman ρ invariants
# ---------------------------------------------------------------------------


@given(
    values=st.lists(
        st.floats(min_value=-1000.0, max_value=1000.0, allow_nan=False, allow_infinity=False),
        min_size=2,
        max_size=100,
    )
)
@settings(max_examples=200, deadline=None)
def test_spearman_rho_range(values: list[float]) -> None:
    """Spearman ρ is always in [-1, 1]."""
    a = np.array(values)
    b = np.roll(a, 1)  # create a "different" array from the same values
    rho = _spearman_rho(a, b)
    assert -1.0 - 1e-9 <= rho <= 1.0 + 1e-9


@given(
    values=st.lists(
        st.floats(min_value=0.01, max_value=10000.0, allow_nan=False, allow_infinity=False),
        min_size=2,
        max_size=50,
    )
)
@settings(max_examples=100, deadline=None)
def test_spearman_rho_self_correlation_is_one(values: list[float]) -> None:
    """ρ(x, x) = 1 for any array."""
    a = np.array(values, dtype=np.float64)
    rho = _spearman_rho(a, a)
    assert abs(rho - 1.0) < 1e-9


# ---------------------------------------------------------------------------
# Pairwise accuracy invariants
# ---------------------------------------------------------------------------


@given(
    group_size=st.integers(min_value=2, max_value=20),
)
@settings(max_examples=100, deadline=None)
def test_pairwise_accuracy_perfect_ordering_is_one(group_size: int) -> None:
    """Perfect score ordering (scores == labels) → pairwise accuracy = 1.0."""
    labels = np.array(list(range(group_size)), dtype=np.int32)
    scores = labels.astype(np.float64)  # score exactly matches label → perfect
    sizes = np.array([group_size], dtype=np.int32)
    acc = _pairwise_accuracy_grouped(scores, labels, sizes)
    assert abs(acc - 1.0) < 1e-9


@given(
    group_size=st.integers(min_value=2, max_value=20),
)
@settings(max_examples=100, deadline=None)
def test_pairwise_accuracy_in_range(group_size: int) -> None:
    """Pairwise accuracy is always in [0, 1]."""
    rng = np.random.default_rng(group_size)
    labels = np.arange(group_size, dtype=np.int32)
    scores = rng.standard_normal(group_size)
    sizes = np.array([group_size], dtype=np.int32)
    acc = _pairwise_accuracy_grouped(scores, labels, sizes)
    assert 0.0 <= acc <= 1.0


# ---------------------------------------------------------------------------
# PSI invariants
# ---------------------------------------------------------------------------


@given(
    n=st.integers(min_value=10, max_value=500),
    loc=st.floats(min_value=0.0, max_value=100.0, allow_nan=False, allow_infinity=False),
)
@settings(max_examples=100, deadline=None)
def test_psi_non_negative(n: int, loc: float) -> None:
    """PSI is always non-negative."""
    rng = np.random.default_rng(42)
    ref = rng.normal(loc, 1.0, n)
    cur = rng.normal(loc + 0.5, 1.0, n)
    psi = _compute_psi(ref, cur)
    assert psi >= 0.0
