"""Tests for TaskPredictor orchestrator."""

import random
import threading

from chronoq_predictor.config import PredictorConfig
from chronoq_predictor.predictor import TaskPredictor
from chronoq_predictor.storage.memory import MemoryStore


def _make_predictor(
    cold_start: int = 10, retrain_every: int = 20
) -> tuple[TaskPredictor, MemoryStore]:
    store = MemoryStore()
    config = PredictorConfig(
        cold_start_threshold=cold_start,
        retrain_every_n=retrain_every,
        storage_uri="memory://",
    )
    predictor = TaskPredictor(config=config, storage=store)
    return predictor, store


def test_zero_state_prediction():
    predictor, _ = _make_predictor()
    result = predictor.predict("unknown_task", 100)
    assert result.estimated_ms > 0
    assert result.model_type == "heuristic"
    assert 0 <= result.confidence <= 1.0


def test_record_and_predict_updated():
    predictor, _ = _make_predictor()
    for _ in range(5):
        predictor.record("fast", 100, 50.0)
    predictor.retrain()
    result = predictor.predict("fast", 100)
    assert abs(result.estimated_ms - 50.0) < 100


def test_auto_retrain():
    predictor, store = _make_predictor(cold_start=100, retrain_every=5)
    for i in range(5):
        predictor.record("task_a", 100, 200.0 + i)
    # After 5 records (retrain_every=5), retrain should have fired
    assert store.count() == 5


def test_auto_promotion():
    predictor, _ = _make_predictor(cold_start=10, retrain_every=10)
    random.seed(42)
    # Record enough to trigger promotion
    for _ in range(10):
        predictor.record("task_a", random.randint(100, 1000), 200.0 + random.gauss(0, 20))
    # After 10 records with retrain_every=10 and cold_start=10, should promote
    result = predictor.predict("task_a", 500)
    assert result.model_type == "gradient_boosting"


def test_promoted_flag():
    predictor, _ = _make_predictor(cold_start=5, retrain_every=100)
    for _ in range(5):
        predictor.record("task", 100, 200.0)
    result = predictor.retrain()
    assert result.promoted is True

    # Second retrain should not promote again
    result2 = predictor.retrain()
    assert result2.promoted is False


def test_thread_safety():
    predictor, _ = _make_predictor(cold_start=50, retrain_every=100)
    errors = []

    def worker_predict():
        try:
            for _ in range(50):
                predictor.predict("task", 100)
        except Exception as e:
            errors.append(e)

    def worker_record():
        try:
            for i in range(50):
                predictor.record("task", 100, 200.0 + i)
        except Exception as e:
            errors.append(e)

    threads = [
        threading.Thread(target=worker_predict),
        threading.Thread(target=worker_predict),
        threading.Thread(target=worker_record),
        threading.Thread(target=worker_record),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(errors) == 0
