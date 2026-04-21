"""Tests for OracleRanker — perfect-knowledge SJF baseline."""

from chronoq_ranker.models.oracle import OracleRanker
from chronoq_ranker.schemas import TaskRecord


def _record(actual_ms: float, task_type: str = "t") -> TaskRecord:
    return TaskRecord(task_type=task_type, payload_size=100, actual_ms=actual_ms)


def test_oracle_model_type_sjf() -> None:
    assert OracleRanker(mode="sjf").model_type() == "oracle_sjf"


def test_oracle_model_type_srpt() -> None:
    assert OracleRanker(mode="srpt").model_type() == "oracle_srpt"


def test_oracle_version_non_empty() -> None:
    assert OracleRanker().version()


def test_oracle_fit_returns_metrics() -> None:
    records = [_record(100.0), _record(200.0)]
    metrics = OracleRanker().fit(records)
    assert metrics["mae"] == 0.0
    assert metrics["samples_used"] == 2


def test_oracle_predict_uses_actual_ms_key() -> None:
    oracle = OracleRanker()
    score, conf = oracle.predict({"_actual_ms": 500.0})
    assert score == 500.0
    assert conf == 1.0


def test_oracle_predict_missing_key_returns_zero() -> None:
    oracle = OracleRanker()
    score, _ = oracle.predict({})
    assert score == 0.0


def test_oracle_predict_batch_preserves_order() -> None:
    oracle = OracleRanker()
    feature_dicts = [{"_actual_ms": 300.0}, {"_actual_ms": 100.0}, {"_actual_ms": 200.0}]
    results = oracle.predict_batch(feature_dicts)
    assert len(results) == 3
    assert results[0][0] == 300.0
    assert results[1][0] == 100.0
    assert results[2][0] == 200.0


def test_oracle_scores_sorted_ascending_equals_sjf() -> None:
    """Ascending sort of oracle scores = SJF order (shortest first)."""
    oracle = OracleRanker()
    feature_dicts = [{"_actual_ms": 500.0}, {"_actual_ms": 100.0}, {"_actual_ms": 300.0}]
    results = oracle.predict_batch(feature_dicts)
    scores = [r[0] for r in results]
    # Sorted ascending → shortest-first ordering
    ordered = sorted(zip(scores, [500, 100, 300], strict=False), key=lambda x: x[0])
    actual_ms_in_order = [ms for _, ms in ordered]
    assert actual_ms_in_order == [100, 300, 500]
