"""Tests for feature extraction."""

from chronoq_predictor.features import extract_features, extract_training_features
from chronoq_predictor.schemas import TaskRecord


def test_extract_features_keys():
    feat = extract_features("resize", 1024)
    assert set(feat.keys()) == {"task_type", "payload_size", "hour_of_day", "queue_depth"}


def test_extract_features_values():
    feat = extract_features("resize", 1024, {"queue_depth": 5})
    assert feat["task_type"] == "resize"
    assert feat["payload_size"] == 1024
    assert feat["queue_depth"] == 5
    assert 0 <= feat["hour_of_day"] <= 23


def test_queue_depth_default():
    feat = extract_features("test", 100)
    assert feat["queue_depth"] == 0


def test_extract_training_features():
    r = TaskRecord(task_type="email", payload_size=50, actual_ms=200.0, metadata={"queue_depth": 3})
    feat = extract_training_features(r)
    assert feat["task_type"] == "email"
    assert feat["payload_size"] == 50
    assert feat["queue_depth"] == 3
    assert 0 <= feat["hour_of_day"] <= 23
