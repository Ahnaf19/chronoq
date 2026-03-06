"""Tests for Scheduler."""

import fakeredis.aioredis
import pytest
from chronoq_predictor import PredictorConfig, TaskPredictor
from chronoq_predictor.storage.memory import MemoryStore
from chronoq_server.core.queue import TaskQueue
from chronoq_server.core.scheduler import Scheduler


@pytest.fixture
async def scheduler():
    store = MemoryStore()
    config = PredictorConfig(cold_start_threshold=50, retrain_every_n=100, storage_uri="memory://")
    predictor = TaskPredictor(config=config, storage=store)
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    queue = TaskQueue(redis, "test:tasks", "test:task:")
    return Scheduler(predictor, queue)


async def test_score_and_enqueue(scheduler: Scheduler):
    prediction = await scheduler.score_and_enqueue("t1", "resize_image", 1024)
    assert prediction.estimated_ms > 0
    assert prediction.model_type == "heuristic"


async def test_report_completion(scheduler: Scheduler):
    scheduler.report_completion("test", 100, 250.0)
    info = scheduler.get_predictor_info()
    assert info["total_records"] == 1


async def test_trigger_retrain(scheduler: Scheduler):
    for _ in range(5):
        scheduler.report_completion("test", 100, 200.0)
    result = await scheduler.trigger_retrain()
    assert "mae" in result
    assert "model_version" in result


async def test_get_predictor_info(scheduler: Scheduler):
    info = scheduler.get_predictor_info()
    assert "model_version" in info
    assert "model_type" in info
    assert info["total_records"] == 0
