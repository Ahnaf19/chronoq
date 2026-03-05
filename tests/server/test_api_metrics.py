"""Tests for metrics API endpoints."""

import fakeredis.aioredis
import pytest
from chronoq_predictor.storage.memory import MemoryStore
from chronoq_server.api.metrics import PredictionTracker
from chronoq_server.core.queue import TaskQueue
from chronoq_server.core.scheduler import Scheduler
from chronoq_server.core.worker import WorkerPool
from httpx import ASGITransport, AsyncClient

from chronoq_predictor import PredictorConfig, TaskPredictor


def _create_test_app():
    from chronoq_server.api.metrics import router as metrics_router
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(metrics_router)

    store = MemoryStore()
    config = PredictorConfig(cold_start_threshold=50, retrain_every_n=100, storage_uri="memory://")
    predictor = TaskPredictor(config=config, storage=store)
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    queue = TaskQueue(redis, "test:tasks", "test:task:")
    scheduler = Scheduler(predictor, queue)
    worker_pool = WorkerPool(queue, scheduler, worker_count=2, poll_interval=0.01)

    app.state.queue = queue
    app.state.scheduler = scheduler
    app.state.worker_pool = worker_pool
    app.state.prediction_tracker = PredictionTracker()

    return app


@pytest.fixture
async def client():
    app = _create_test_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


async def test_get_metrics(client: AsyncClient):
    resp = await client.get("/metrics")
    assert resp.status_code == 200
    data = resp.json()
    assert "queue_depth" in data
    assert "prediction" in data
    assert "workers" in data
    assert data["queue_depth"] == 0


async def test_retrain(client: AsyncClient):
    resp = await client.post("/metrics/retrain")
    assert resp.status_code == 200
    data = resp.json()
    assert "mae" in data
    assert "model_version" in data


async def test_predictions_empty(client: AsyncClient):
    resp = await client.get("/metrics/predictions")
    assert resp.status_code == 200
    assert resp.json() == []
