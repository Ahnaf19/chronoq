"""Tests for Pydantic schemas."""

from datetime import UTC

import pytest
from chronoq_predictor.schemas import PredictionResult, RetrainResult, TaskRecord
from pydantic import ValidationError


class TestTaskRecord:
    def test_defaults(self):
        r = TaskRecord(task_type="resize", payload_size=100, actual_ms=250.0)
        assert r.task_type == "resize"
        assert r.metadata == {}
        assert r.model_version_at_record == ""
        assert r.recorded_at.tzinfo == UTC

    def test_with_metadata(self):
        r = TaskRecord(
            task_type="email",
            payload_size=50,
            actual_ms=100.0,
            metadata={"worker": "w-1"},
        )
        assert r.metadata["worker"] == "w-1"

    def test_round_trip(self):
        r = TaskRecord(task_type="test", payload_size=10, actual_ms=99.9)
        data = r.model_dump()
        restored = TaskRecord(**data)
        assert restored == r


class TestPredictionResult:
    def test_valid(self):
        p = PredictionResult(
            estimated_ms=300.0,
            confidence=0.8,
            model_version="v1",
            model_type="heuristic",
        )
        assert p.confidence == 0.8

    def test_confidence_lower_bound(self):
        with pytest.raises(ValidationError):
            PredictionResult(
                estimated_ms=100.0,
                confidence=-0.1,
                model_version="v1",
                model_type="heuristic",
            )

    def test_confidence_upper_bound(self):
        with pytest.raises(ValidationError):
            PredictionResult(
                estimated_ms=100.0,
                confidence=1.1,
                model_version="v1",
                model_type="heuristic",
            )

    def test_model_type_literal(self):
        with pytest.raises(ValidationError):
            PredictionResult(
                estimated_ms=100.0,
                confidence=0.5,
                model_version="v1",
                model_type="random_forest",
            )


class TestRetrainResult:
    def test_valid(self):
        r = RetrainResult(mae=42.0, mape=8.0, samples_used=100, model_version="v2", promoted=True)
        assert r.promoted is True
        assert r.samples_used == 100

    def test_round_trip(self):
        r = RetrainResult(mae=10.0, mape=5.0, samples_used=50, model_version="v1", promoted=False)
        assert RetrainResult(**r.model_dump()) == r
