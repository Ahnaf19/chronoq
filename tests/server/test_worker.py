"""Tests for WorkerPool."""

import asyncio
from unittest.mock import AsyncMock, patch

import fakeredis.aioredis
import pytest
from chronoq_demo_server.core.queue import TaskQueue
from chronoq_demo_server.core.scheduler import Scheduler
from chronoq_demo_server.core.worker import WorkerPool
from chronoq_ranker import RankerConfig, TaskRanker
from chronoq_ranker.storage.memory import MemoryStore


@pytest.fixture
async def worker_setup():
    store = MemoryStore()
    config = RankerConfig(cold_start_threshold=50, retrain_every_n=100, storage_uri="memory://")
    predictor = TaskRanker(config=config, storage=store)
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    queue = TaskQueue(redis, "test:tasks", "test:task:")
    scheduler = Scheduler(predictor, queue)
    pool = WorkerPool(queue, scheduler, worker_count=2, poll_interval=0.01)
    return pool, queue, scheduler, store


async def test_worker_processes_task(worker_setup):
    pool, queue, scheduler, store = worker_setup

    await queue.enqueue("t1", "send_email", 100, 150.0)

    with patch("chronoq_demo_server.core.worker.simulate_task", new_callable=AsyncMock) as mock_sim:
        mock_sim.return_value = 120.0
        await pool.start()
        await asyncio.sleep(0.2)
        await pool.stop()

    task = await queue.get_task("t1")
    assert task["status"] == "completed"
    assert store.count() >= 1


async def test_worker_handles_empty_queue(worker_setup):
    pool, queue, scheduler, store = worker_setup

    with patch("chronoq_demo_server.core.worker.simulate_task", new_callable=AsyncMock) as mock_sim:
        mock_sim.return_value = 100.0
        await pool.start()
        await asyncio.sleep(0.1)
        await pool.stop()

    # No errors, workers just idle
    stats = pool.get_stats()
    for wid in stats:
        assert stats[wid]["tasks_completed"] == 0


async def test_worker_feeds_telemetry(worker_setup):
    pool, queue, scheduler, store = worker_setup

    for i in range(3):
        await queue.enqueue(f"t{i}", "resize_image", 200, 300.0)

    with patch("chronoq_demo_server.core.worker.simulate_task", new_callable=AsyncMock) as mock_sim:
        mock_sim.return_value = 280.0
        await pool.start()
        await asyncio.sleep(0.5)
        await pool.stop()

    assert store.count() == 3


async def test_worker_stop_is_clean(worker_setup):
    pool, queue, scheduler, store = worker_setup

    with patch("chronoq_demo_server.core.worker.simulate_task", new_callable=AsyncMock) as mock_sim:
        mock_sim.return_value = 100.0
        await pool.start()
        await asyncio.sleep(0.05)
        await pool.stop()

    # No hanging tasks
    assert len(pool._tasks) == 0
