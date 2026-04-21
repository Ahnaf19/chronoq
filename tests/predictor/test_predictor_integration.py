"""Integration tests for the full predictor lifecycle."""

import random

from chronoq_ranker.config import PredictorConfig
from chronoq_ranker.predictor import TaskPredictor
from chronoq_ranker.storage.memory import MemoryStore


def test_full_lifecycle_heuristic_to_gradient():
    """100+ records across 3 types triggers heuristic->gradient promotion."""
    random.seed(42)
    store = MemoryStore()
    config = PredictorConfig(
        cold_start_threshold=50,
        retrain_every_n=50,
        storage_uri="memory://",
    )
    predictor = TaskPredictor(config=config, storage=store)

    task_profiles = {
        "fast": (100, 20),
        "medium": (500, 80),
        "slow": (2000, 300),
    }

    for _i in range(120):
        task_type = random.choice(list(task_profiles.keys()))
        base, var = task_profiles[task_type]
        payload = random.randint(100, 2000)
        actual = base + payload * 0.05 + random.gauss(0, var)
        predictor.record(task_type, payload, max(1.0, actual))

    # Should have auto-promoted to gradient
    result = predictor.predict("fast", 500)
    assert result.model_type == "gradient_boosting"

    # Gradient predictions should differentiate task types
    fast = predictor.predict("fast", 500)
    slow = predictor.predict("slow", 500)
    assert fast.estimated_ms < slow.estimated_ms


def test_sqlite_persistence_lifecycle(tmp_path):
    """New predictor on same DB should warm-start correctly."""
    db_uri = f"sqlite:///{tmp_path}/lifecycle.db"
    config = PredictorConfig(
        cold_start_threshold=10,
        retrain_every_n=100,
        storage_uri=db_uri,
    )

    # First predictor: record data
    p1 = TaskPredictor(config=config, storage=db_uri)
    random.seed(42)
    for _ in range(20):
        p1.record("task_a", random.randint(100, 500), 200.0 + random.gauss(0, 30))

    # Second predictor on same DB: should warm-start
    p2 = TaskPredictor(config=config, storage=db_uri)
    result = p2.predict("task_a", 300)
    assert result.model_type == "gradient_boosting"  # 20 > cold_start_threshold of 10

    # Retrain should work
    retrain_result = p2.retrain()
    assert retrain_result.samples_used == 20
    assert retrain_result.mae >= 0
