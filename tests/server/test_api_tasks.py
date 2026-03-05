"""Tests for tasks API endpoints."""

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
    """Create a FastAPI app with test dependencies (no lifespan)."""
    from chronoq_server.api.tasks import router as tasks_router
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(tasks_router)

    store = MemoryStore()
    config = PredictorConfig(cold_start_threshold=50, retrain_every_n=100, storage_uri="memory://")
    predictor = TaskPredictor(config=config, storage=store)
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    queue = TaskQueue(redis, "test:tasks", "test:task:")
    scheduler = Scheduler(predictor, queue)
    worker_pool = WorkerPool(queue, scheduler, worker_count=1, poll_interval=0.01)

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


async def test_submit_task(client: AsyncClient):
    resp = await client.post("/tasks", json={"task_type": "resize_image", "payload_size": 1024})
    assert resp.status_code == 200
    data = resp.json()
    assert "task_id" in data
    assert data["predicted_ms"] > 0
    assert data["model_type"] == "heuristic"


async def test_get_task(client: AsyncClient):
    resp = await client.post("/tasks", json={"task_type": "send_email", "payload_size": 100})
    task_id = resp.json()["task_id"]

    resp2 = await client.get(f"/tasks/{task_id}")
    assert resp2.status_code == 200
    assert resp2.json()["task_type"] == "send_email"


async def test_get_task_404(client: AsyncClient):
    resp = await client.get("/tasks/nonexistent-id")
    assert resp.status_code == 404


async def test_batch_submit(client: AsyncClient):
    resp = await client.post(
        "/tasks/batch",
        json={
            "tasks": [
                {"task_type": "resize_image", "payload_size": 500},
                {"task_type": "send_email", "payload_size": 100},
                {"task_type": "compress_file", "payload_size": 2000},
            ]
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 3
    assert all("task_id" in t for t in data)


async def test_queue_snapshot(client: AsyncClient):
    await client.post("/tasks", json={"task_type": "slow", "payload_size": 5000})
    await client.post("/tasks", json={"task_type": "fast", "payload_size": 100})

    resp = await client.get("/tasks")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
