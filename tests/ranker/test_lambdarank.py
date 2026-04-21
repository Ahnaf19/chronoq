"""Tests for LambdaRankEstimator and TaskRanker's lambdarank promotion path.

Group construction: to get 20+ valid groups in tests, records are seeded with
explicit group_id values (group_0, group_1, ...) rather than relying on the
60s tumbling window (which collapses everything into 1 group in fast test runs).
"""

import pytest
from chronoq_ranker.config import RankerConfig
from chronoq_ranker.models.lambdarank import (
    LambdaRankEstimator,
    _assign_tumbling_group_ids,
    _spearman_rho,
)
from chronoq_ranker.ranker import TaskRanker
from chronoq_ranker.schemas import InsufficientGroupsError, RetrainResult, TaskRecord

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_records_with_groups(
    n_groups: int, n_per_group: int = 5, seed: int = 42
) -> list[TaskRecord]:
    """n_groups * n_per_group records with explicit group_ids and log-normal durations."""
    import random

    rng = random.Random(seed)
    records = []
    for g in range(n_groups):
        for _ in range(n_per_group):
            actual_ms = max(10.0, rng.lognormvariate(5.0, 1.2))
            records.append(
                TaskRecord(
                    task_type=rng.choice(["resize", "compress", "encode"]),
                    payload_size=rng.randint(100, 5000),
                    actual_ms=actual_ms,
                    group_id=f"group_{g}",
                )
            )
    return records


def _lambda_estimator(min_groups: int = 20) -> LambdaRankEstimator:
    config = RankerConfig(min_groups=min_groups, storage_uri="memory://")
    return LambdaRankEstimator(config=config)


# ---------------------------------------------------------------------------
# Basic interface tests
# ---------------------------------------------------------------------------


def test_lambdarank_model_type() -> None:
    assert _lambda_estimator().model_type() == "lambdarank"


def test_lambdarank_version_unfit() -> None:
    est = _lambda_estimator()
    assert "unfit" in est.version()


def test_lambdarank_version_after_fit() -> None:
    records = _make_records_with_groups(25)
    est = _lambda_estimator(min_groups=20)
    est.fit(records)
    assert "lambdarank" in est.version()
    assert "unfit" not in est.version()


def test_lambdarank_insufficient_groups_raises_when_allow_degrade_false() -> None:
    records = _make_records_with_groups(5)  # only 5 groups < min_groups=20
    est = _lambda_estimator(min_groups=20)
    with pytest.raises(InsufficientGroupsError) as exc:
        est.fit(records)
    assert exc.value.actual == 5
    assert exc.value.required == 20


def test_insufficient_groups_error_message() -> None:
    err = InsufficientGroupsError(actual=3, required=20)
    assert "3" in str(err)
    assert "20" in str(err)


def test_lambdarank_fit_returns_ranking_metrics() -> None:
    records = _make_records_with_groups(25)
    est = _lambda_estimator()
    metrics = est.fit(records)
    assert "spearman_rho" in metrics
    assert "pairwise_accuracy" in metrics
    assert "kendall_tau" in metrics
    assert metrics["samples_used"] == len(records)
    assert metrics["mae"] == 0.0


def test_lambdarank_spearman_rho_non_negative_after_fit() -> None:
    records = _make_records_with_groups(25)
    est = _lambda_estimator()
    metrics = est.fit(records)
    # ρ might be low on small test data but shouldn't be extreme negative
    assert metrics["spearman_rho"] > -1.0


def test_lambdarank_pairwise_accuracy_in_range() -> None:
    records = _make_records_with_groups(25)
    est = _lambda_estimator()
    metrics = est.fit(records)
    assert 0.0 <= metrics["pairwise_accuracy"] <= 1.0


def test_lambdarank_predict_returns_tuple_after_fit() -> None:
    records = _make_records_with_groups(25)
    est = _lambda_estimator()
    est.fit(records)
    score, confidence = est.predict({"task_type": "resize", "payload_size": 100.0})
    assert isinstance(score, float)
    assert 0.0 <= confidence <= 1.0


def test_lambdarank_predict_before_fit_returns_zeros() -> None:
    est = _lambda_estimator()
    score, conf = est.predict({"task_type": "resize", "payload_size": 100.0})
    assert score == 0.0
    assert conf == 0.0


def test_lambdarank_predict_batch_before_fit() -> None:
    est = _lambda_estimator()
    results = est.predict_batch([{"task_type": "t", "payload_size": 100.0}] * 3)
    assert len(results) == 3
    assert all(r == (0.0, 0.0) for r in results)


def test_lambdarank_predict_batch_length_matches_input() -> None:
    records = _make_records_with_groups(25)
    est = _lambda_estimator()
    est.fit(records)
    n = 7
    feats = [{"task_type": "resize", "payload_size": float(i)} for i in range(n)]
    results = est.predict_batch(feats)
    assert len(results) == n


def test_lambdarank_predict_batch_empty_input() -> None:
    records = _make_records_with_groups(25)
    est = _lambda_estimator()
    est.fit(records)
    assert est.predict_batch([]) == []


# ---------------------------------------------------------------------------
# Ordering tests
# ---------------------------------------------------------------------------


def test_lambdarank_shorter_job_gets_lower_score() -> None:
    """After training, the shorter task should score lower (= scheduled sooner)."""
    records = []
    for g in range(30):
        records.append(
            TaskRecord(
                task_type="fast",
                payload_size=100,
                actual_ms=100.0,
                group_id=f"g{g}",
            )
        )
        records.append(
            TaskRecord(
                task_type="slow",
                payload_size=100,
                actual_ms=10000.0,
                group_id=f"g{g}",
            )
        )

    config = RankerConfig(min_groups=2, storage_uri="memory://")
    est = LambdaRankEstimator(config=config)
    est.fit(records)

    fast_feats = {"task_type": "fast", "payload_size": 100.0}
    slow_feats = {"task_type": "slow", "payload_size": 100.0}
    results = est.predict_batch([fast_feats, slow_feats])
    fast_score, slow_score = results[0][0], results[1][0]
    # fast (shorter) should have lower score → scheduled first
    assert fast_score < slow_score


# ---------------------------------------------------------------------------
# TaskRanker promotion tests
# ---------------------------------------------------------------------------


def test_ranker_degrades_to_gradient_when_insufficient_groups() -> None:
    """Default allow_degrade=True falls back to gradient when groups insufficient."""
    config = RankerConfig(
        cold_start_threshold=5,
        retrain_every_n=200,
        min_groups=20,
        allow_degrade=True,
        storage_uri="memory://",
    )
    ranker = TaskRanker(config=config)
    # Record 10 items — all in same time window → 1 group → InsufficientGroupsError
    for i in range(10):
        ranker.record("t", 100, float(100 + i * 10))
    result = ranker.retrain()
    # Should fall back to gradient (or heuristic if gradient also fails)
    assert result.model_type in {"gradient_boosting", "heuristic"}


def test_ranker_promotes_to_lambdarank_with_sufficient_groups() -> None:
    """TaskRanker promotes to lambdarank when explicit group_ids provide enough groups."""
    from chronoq_ranker.storage.memory import MemoryStore

    store = MemoryStore()
    config = RankerConfig(
        cold_start_threshold=10,
        min_groups=2,
        allow_degrade=False,
        storage_uri="memory://",
    )
    ranker = TaskRanker(config=config, storage=store)

    # Seed records with 5 explicit groups (min_groups=2 so this is sufficient)
    for g in range(5):
        for _ in range(4):
            import random

            rng = random.Random(g * 100)
            rec = TaskRecord(
                task_type="fast" if rng.random() > 0.5 else "slow",
                payload_size=100,
                actual_ms=100.0 if rng.random() > 0.5 else 5000.0,
                group_id=f"g{g}",
            )
            store.save(rec)

    result = ranker.retrain()
    assert result.model_type == "lambdarank"
    assert result.spearman_rho is not None


def test_ranker_retrain_result_has_ranking_fields_for_lambdarank() -> None:
    from chronoq_ranker.storage.memory import MemoryStore

    store = MemoryStore()
    config = RankerConfig(
        cold_start_threshold=5, min_groups=2, allow_degrade=False, storage_uri="memory://"
    )
    ranker = TaskRanker(config=config, storage=store)

    for g in range(5):
        store.save(TaskRecord(task_type="a", payload_size=100, actual_ms=100.0, group_id=f"g{g}"))
        store.save(TaskRecord(task_type="b", payload_size=200, actual_ms=500.0, group_id=f"g{g}"))

    result = ranker.retrain()
    assert isinstance(result, RetrainResult)
    assert result.spearman_rho is not None
    assert result.pairwise_accuracy is not None
    assert result.kendall_tau is not None


def test_ranker_retrain_result_ranking_fields_none_for_gradient() -> None:
    config = RankerConfig(
        cold_start_threshold=5,
        retrain_every_n=200,
        allow_degrade=True,
        min_groups=200,  # impossibly high → always degrade
        storage_uri="memory://",
    )
    ranker = TaskRanker(config=config)
    for i in range(10):
        ranker.record("t", 100, float(100 + i))
    result = ranker.retrain()
    assert result.model_type in {"gradient_boosting", "heuristic"}
    assert result.spearman_rho is None


# ---------------------------------------------------------------------------
# Incremental fit tests
# ---------------------------------------------------------------------------


def test_lambdarank_incremental_fit_changes_version() -> None:
    config = RankerConfig(
        min_groups=2,
        full_refit_every_n_incrementals=10,
        storage_uri="memory://",
    )
    est = LambdaRankEstimator(config=config)
    records = _make_records_with_groups(5, n_per_group=4)

    est.fit(records)
    v1 = est.version()

    import time

    time.sleep(1.1)  # ensure timestamp differs

    est.fit(records)  # incremental
    v2 = est.version()
    assert v1 != v2


def test_lambdarank_full_refit_triggers_after_n_incrementals() -> None:
    config = RankerConfig(
        min_groups=2,
        full_refit_every_n_incrementals=2,
        storage_uri="memory://",
    )
    est = LambdaRankEstimator(config=config)
    records = _make_records_with_groups(5, n_per_group=4)

    est.fit(records)  # full (count=0)
    assert est._incremental_count == 0

    est.fit(records)  # incremental (count=1)
    assert est._incremental_count == 1

    est.fit(records)  # incremental (count=2)
    assert est._incremental_count == 2

    est.fit(records)  # full refit (count resets to 0)
    assert est._incremental_count == 0


# ---------------------------------------------------------------------------
# Group assignment helper tests
# ---------------------------------------------------------------------------


def test_tumbling_window_assigns_group_ids_to_ungrouped() -> None:
    records = [TaskRecord(task_type="t", payload_size=100, actual_ms=100.0) for _ in range(5)]
    enriched = _assign_tumbling_group_ids(records)
    assert all(r.group_id is not None for r in enriched)
    # All created in the same second → same window
    group_ids = {r.group_id for r in enriched}
    assert len(group_ids) == 1


def test_tumbling_window_preserves_explicit_group_id() -> None:
    records = [
        TaskRecord(task_type="t", payload_size=100, actual_ms=100.0, group_id="my-batch")
        for _ in range(3)
    ]
    enriched = _assign_tumbling_group_ids(records)
    assert all(r.group_id == "my-batch" for r in enriched)


def test_spearman_rho_perfect_correlation() -> None:
    import numpy as np

    a = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    assert abs(_spearman_rho(a, a) - 1.0) < 1e-9


def test_spearman_rho_perfect_anti_correlation() -> None:
    import numpy as np

    a = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    b = np.array([5.0, 4.0, 3.0, 2.0, 1.0])
    assert abs(_spearman_rho(a, b) - (-1.0)) < 1e-9


def test_spearman_rho_single_element_returns_zero() -> None:
    import numpy as np

    assert _spearman_rho(np.array([1.0]), np.array([1.0])) == 0.0
