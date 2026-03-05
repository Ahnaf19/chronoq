"""Tests for HeuristicEstimator."""

from chronoq_predictor.models.heuristic import HeuristicEstimator
from chronoq_predictor.schemas import TaskRecord


def _make_records(task_type: str, values: list[float]) -> list[TaskRecord]:
    return [TaskRecord(task_type=task_type, payload_size=100, actual_ms=v) for v in values]


def test_empty_state():
    est = HeuristicEstimator()
    ms, conf = est.predict({"task_type": "unknown"})
    assert ms == 1000.0
    assert conf == 0.1


def test_single_type():
    est = HeuristicEstimator()
    records = _make_records("resize", [100.0, 200.0, 300.0])
    est.fit(records)
    ms, conf = est.predict({"task_type": "resize"})
    assert abs(ms - 200.0) < 0.1
    assert 0 < conf <= 1.0


def test_multi_type():
    est = HeuristicEstimator()
    records = _make_records("fast", [50.0, 60.0]) + _make_records("slow", [500.0, 600.0])
    est.fit(records)

    fast_ms, _ = est.predict({"task_type": "fast"})
    slow_ms, _ = est.predict({"task_type": "slow"})
    assert fast_ms < slow_ms


def test_unseen_type():
    est = HeuristicEstimator()
    records = _make_records("known", [100.0, 200.0, 300.0])
    est.fit(records)
    ms, conf = est.predict({"task_type": "unknown"})
    assert abs(ms - 200.0) < 0.1  # global mean
    assert conf == 0.3


def test_confidence_bounds():
    est = HeuristicEstimator()
    records = _make_records("test", [100.0, 100.0, 100.0])
    est.fit(records)
    _, conf = est.predict({"task_type": "test"})
    assert 0 < conf <= 1.0


def test_version_increment():
    est = HeuristicEstimator()
    assert est.version() == "heuristic-v0"
    est.fit(_make_records("test", [100.0]))
    assert est.version() == "heuristic-v1"
    est.fit(_make_records("test", [100.0, 200.0]))
    assert est.version() == "heuristic-v2"


def test_model_type():
    est = HeuristicEstimator()
    assert est.model_type() == "heuristic"
