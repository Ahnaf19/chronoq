"""Shared test fixtures."""

import pytest
from chronoq_ranker.config import PredictorConfig
from chronoq_ranker.storage.memory import MemoryStore


@pytest.fixture
def memory_store() -> MemoryStore:
    """Fresh in-memory store."""
    return MemoryStore()


@pytest.fixture
def predictor_config() -> PredictorConfig:
    """Config with low thresholds for fast testing."""
    return PredictorConfig(
        cold_start_threshold=10,
        retrain_every_n=20,
        storage_uri="memory://",
    )
