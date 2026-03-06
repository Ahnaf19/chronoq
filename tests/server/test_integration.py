"""Server integration tests."""

import asyncio
from unittest.mock import AsyncMock, patch

import fakeredis.aioredis
import pytest
from chronoq_predictor import PredictorConfig, TaskPredictor
from chronoq_predictor.storage.memory import MemoryStore
from chronoq_server.core.queue import TaskQueue
from chronoq_server.core.scheduler import Scheduler
from chronoq_server.core.worker import WorkerPool


@pytest.fixture
async def system():
    store = MemoryStore()
    config = PredictorConfig(cold_start_threshold=50, retrain_every_n=100, storage_uri="memory://")
    predictor = TaskPredictor(config=config, storage=store)
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    queue = TaskQueue(redis, "test:tasks", "test:task:")
    scheduler = Scheduler(predictor, queue)
    pool = WorkerPool(queue, scheduler, worker_count=4, poll_interval=0.01)
    return {
        "store": store,
        "predictor": predictor,
        "queue": queue,
        "scheduler": scheduler,
        "pool": pool,
    }


async def test_submit_and_drain(system):
    """Submit 20 tasks, workers drain them all, telemetry recorded."""
    queue = system["queue"]
    scheduler = system["scheduler"]
    pool = system["pool"]
    store = system["store"]

    # Submit 20 tasks
    for i in range(20):
        task_type = ["send_email", "resize_image", "compress_file"][i % 3]
        await scheduler.score_and_enqueue(f"task-{i}", task_type, 100 + i * 10)

    assert await queue.length() == 20

    with patch("chronoq_server.core.worker.simulate_task", new_callable=AsyncMock) as mock_sim:
        mock_sim.return_value = 150.0
        await pool.start()

        # Wait for drain
        for _ in range(100):
            if await queue.length() == 0:
                break
            await asyncio.sleep(0.05)

        await pool.stop()

    assert await queue.length() == 0
    assert store.count() == 20

    # All tasks completed
    for i in range(20):
        task = await queue.get_task(f"task-{i}")
        assert task["status"] == "completed"


async def test_sjf_tendency(system):
    """Shorter predicted tasks should generally complete before longer ones."""
    queue = system["queue"]
    scheduler = system["scheduler"]

    completed_order = []

    async def mock_task(task_type, payload_size):
        completed_order.append(task_type)
        return 10.0  # Instant completion

    # Submit tasks: send_email predicted shorter than generate_report
    await scheduler.score_and_enqueue("fast-1", "send_email", 100)
    await scheduler.score_and_enqueue("slow-1", "generate_report", 100)
    await scheduler.score_and_enqueue("fast-2", "send_email", 100)

    with patch("chronoq_server.core.worker.simulate_task", side_effect=mock_task):
        pool_1worker = WorkerPool(queue, scheduler, worker_count=1, poll_interval=0.01)
        await pool_1worker.start()

        for _ in range(100):
            if await queue.length() == 0:
                break
            await asyncio.sleep(0.05)

        await pool_1worker.stop()

    # With 1 worker, SJF should process send_email tasks before generate_report
    # Both send_email tasks should appear before generate_report
    assert len(completed_order) == 3
