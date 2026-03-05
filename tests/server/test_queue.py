"""Tests for TaskQueue with fakeredis."""

import fakeredis.aioredis
import pytest
from chronoq_server.core.queue import TaskQueue


@pytest.fixture
async def queue():
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    return TaskQueue(redis, "test:tasks", "test:task:")


async def test_sjf_ordering(queue: TaskQueue):
    """Tasks dequeued in shortest-job-first order."""
    await queue.enqueue("t1", "slow", 100, 500.0)
    await queue.enqueue("t2", "fast", 50, 100.0)
    await queue.enqueue("t3", "mid", 75, 300.0)

    first = await queue.dequeue()
    assert first["task_id"] == "t2"  # 100ms

    second = await queue.dequeue()
    assert second["task_id"] == "t3"  # 300ms

    third = await queue.dequeue()
    assert third["task_id"] == "t1"  # 500ms


async def test_empty_dequeue(queue: TaskQueue):
    result = await queue.dequeue()
    assert result is None


async def test_length(queue: TaskQueue):
    assert await queue.length() == 0
    await queue.enqueue("t1", "test", 100, 200.0)
    await queue.enqueue("t2", "test", 100, 300.0)
    assert await queue.length() == 2


async def test_peek(queue: TaskQueue):
    await queue.enqueue("t1", "slow", 100, 500.0)
    await queue.enqueue("t2", "fast", 50, 100.0)

    peeked = await queue.peek(n=2)
    assert len(peeked) == 2
    assert peeked[0]["task_id"] == "t2"  # SJF order
    assert peeked[1]["task_id"] == "t1"

    # Peek should not remove items
    assert await queue.length() == 2


async def test_status_updates(queue: TaskQueue):
    await queue.enqueue("t1", "test", 100, 200.0)
    await queue.update_status("t1", "running", worker_id="0")

    task = await queue.get_task("t1")
    assert task["status"] == "running"
    assert task["worker_id"] == "0"


async def test_get_task_missing(queue: TaskQueue):
    result = await queue.get_task("nonexistent")
    assert result is None
