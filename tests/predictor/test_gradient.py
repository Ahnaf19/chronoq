"""Tests for GradientEstimator."""

import random

from chronoq_ranker.models.gradient import GradientEstimator
from chronoq_ranker.schemas import TaskRecord


def _synthetic_records(n: int = 60) -> list[TaskRecord]:
    """Generate synthetic training data with learnable patterns."""
    random.seed(42)
    records = []
    for _ in range(n):
        task_type = random.choice(["fast", "medium", "slow"])
        base = {"fast": 100, "medium": 500, "slow": 2000}[task_type]
        payload = random.randint(100, 5000)
        actual = base + payload * 0.05 + random.gauss(0, 50)
        records.append(
            TaskRecord(
                task_type=task_type,
                payload_size=payload,
                actual_ms=max(1.0, actual),
                metadata={"queue_depth": random.randint(0, 20)},
            )
        )
    return records


def test_fit_and_predict():
    est = GradientEstimator()
    records = _synthetic_records()
    metrics = est.fit(records)

    assert metrics["mae"] >= 0
    assert metrics["mape"] >= 0
    assert metrics["samples_used"] == len(records)

    ms, conf = est.predict({"task_type": "fast", "payload_size": 500, "queue_depth": 5})
    assert ms >= 1.0
    assert 0.1 <= conf <= 1.0


def test_unseen_type_fallback():
    est = GradientEstimator()
    est.fit(_synthetic_records())

    ms, conf = est.predict({"task_type": "never_seen", "payload_size": 100})
    assert ms > 0  # Falls back to heuristic


def test_version_increment():
    est = GradientEstimator()
    assert est.version() == "gradient-v0"
    est.fit(_synthetic_records())
    assert est.version() == "gradient-v1"
    est.fit(_synthetic_records())
    assert est.version() == "gradient-v2"


def test_model_type():
    est = GradientEstimator()
    assert est.model_type() == "gradient_boosting"


def test_prediction_clamped():
    """Predictions should never be below 1.0ms."""
    est = GradientEstimator()
    records = [TaskRecord(task_type="tiny", payload_size=1, actual_ms=1.0) for _ in range(20)]
    est.fit(records)
    ms, _ = est.predict({"task_type": "tiny", "payload_size": 1})
    assert ms >= 1.0
