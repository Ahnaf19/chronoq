"""Tests for DriftDetector and PSI computation."""

import numpy as np
import pytest
from chronoq_ranker.config import RankerConfig
from chronoq_ranker.drift import DriftDetector, _compute_psi
from chronoq_ranker.schemas import DriftReport, TaskRecord


def _records(payload_sizes: list[int], actual_ms: float = 100.0) -> list[TaskRecord]:
    return [TaskRecord(task_type="t", payload_size=p, actual_ms=actual_ms) for p in payload_sizes]


def test_psi_zero_for_identical_distributions() -> None:
    dist = np.array([1.0, 2.0, 3.0, 4.0, 5.0] * 20, dtype=np.float64)
    psi = _compute_psi(dist, dist.copy())
    assert psi < 0.01, f"Expected near-zero PSI for identical dists, got {psi}"


def test_psi_positive_for_shifted_distribution() -> None:
    reference = np.linspace(0, 10, 200)
    current = np.linspace(5, 15, 200)  # shifted right by 5
    psi = _compute_psi(reference, current)
    assert psi > 0.1, f"Expected positive PSI for shifted dist, got {psi}"


def test_psi_large_for_extreme_shift() -> None:
    reference = np.ones(100) * 1.0
    current = np.ones(100) * 1000.0
    psi = _compute_psi(reference, current)
    assert psi > 0.3


def test_psi_degenerate_empty_reference_returns_zero() -> None:
    assert _compute_psi(np.array([]), np.array([1.0, 2.0])) == 0.0


def test_psi_degenerate_constant_reference_does_not_crash() -> None:
    """Constant reference produces degenerate bins — should not raise, result non-negative."""
    ref = np.ones(50)
    cur = np.array([1.0, 2.0, 3.0])
    psi = _compute_psi(ref, cur)
    assert psi >= 0.0


def test_drift_detector_requires_set_reference_before_check() -> None:
    config = RankerConfig(storage_uri="memory://")
    detector = DriftDetector(config)
    records = _records([100, 200, 300])
    with pytest.raises(RuntimeError, match="set_reference"):
        detector.check(records)


def test_drift_detector_stable_for_identical_distributions() -> None:
    config = RankerConfig(storage_uri="memory://")
    detector = DriftDetector(config)
    ref = _records(list(range(100, 200)))
    detector.set_reference(ref)
    report = detector.check(_records(list(range(100, 200))))
    assert isinstance(report, DriftReport)
    assert report.overall_status == "stable"
    assert report.drifted_features == []


def test_drift_detector_warns_on_moderate_shift() -> None:
    config = RankerConfig(psi_threshold=0.1, storage_uri="memory://")
    detector = DriftDetector(config)
    ref = _records(list(range(1, 101)))
    detector.set_reference(ref)
    # Strongly shifted payload distribution
    current = _records(list(range(1000, 1100)))
    report = detector.check(current)
    assert report.overall_status in {"warn", "drift"}
    # payload_size should have high PSI
    assert report.per_feature_psi.get("payload_size", 0.0) > 0.1


def test_drift_detector_flags_drift_above_hard_threshold() -> None:
    config = RankerConfig(psi_threshold=0.2, storage_uri="memory://")
    detector = DriftDetector(config)
    ref = _records([100] * 100)  # constant reference → degenerate, test only PSI flag logic
    detector.set_reference(ref)
    # Create a non-degenerate reference for a meaningful PSI
    config2 = RankerConfig(psi_threshold=0.2, storage_uri="memory://")
    detector2 = DriftDetector(config2)
    ref2 = _records(list(range(1, 201)))  # payload 1..200
    detector2.set_reference(ref2)
    current = _records(list(range(5000, 5200)))  # extreme shift
    report = detector2.check(current)
    assert "payload_size" in report.per_feature_psi
    if report.per_feature_psi["payload_size"] >= 0.3:
        assert "payload_size" in report.drifted_features


def test_drift_report_is_pydantic_serializable() -> None:
    config = RankerConfig(storage_uri="memory://")
    detector = DriftDetector(config)
    ref = _records(list(range(50, 150)))
    detector.set_reference(ref)
    report = detector.check(_records(list(range(50, 150))))
    dumped = report.model_dump()
    assert "per_feature_psi" in dumped
    assert "overall_status" in dumped
    restored = DriftReport(**dumped)
    assert restored.overall_status == report.overall_status


def test_drift_detector_set_reference_empty_is_noop() -> None:
    """set_reference with empty list should not crash."""
    config = RankerConfig(storage_uri="memory://")
    detector = DriftDetector(config)
    detector.set_reference([])  # should not raise


def test_drift_detector_rolling_mae_via_record_mae() -> None:
    config = RankerConfig(storage_uri="memory://")
    detector = DriftDetector(config)
    ref = _records(list(range(100, 200)))
    detector.set_reference(ref)
    detector.record_mae(predicted_ms=100.0, actual_ms=110.0)
    detector.record_mae(predicted_ms=200.0, actual_ms=190.0)
    report = detector.check(_records(list(range(100, 200))))
    # rolling MAE = mean([10.0, 10.0]) = 10.0
    assert abs(report.rolling_mae_delta - 10.0) < 1e-6
