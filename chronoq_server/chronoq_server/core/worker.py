"""Async worker pool that drains the SJF queue."""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

from loguru import logger

from chronoq_server.task_registry import simulate_task

if TYPE_CHECKING:
    from chronoq_server.api.metrics import PredictionTracker
    from chronoq_server.core.queue import TaskQueue
    from chronoq_server.core.scheduler import Scheduler


class WorkerPool:
    """Spawns N async workers to process tasks from the queue."""

    def __init__(
        self,
        queue: TaskQueue,
        scheduler: Scheduler,
        worker_count: int = 4,
        poll_interval: float = 0.1,
        prediction_tracker: PredictionTracker | None = None,
    ) -> None:
        self._queue = queue
        self._scheduler = scheduler
        self._worker_count = worker_count
        self._poll_interval = poll_interval
        self._prediction_tracker = prediction_tracker
        self._tasks: list[asyncio.Task] = []
        self._stats: dict[int, dict] = {}
        self._running = False

    async def start(self) -> None:
        """Start all worker coroutines."""
        self._running = True
        for i in range(self._worker_count):
            self._stats[i] = {
                "tasks_completed": 0,
                "total_busy_ms": 0.0,
                "total_idle_ms": 0.0,
                "status": "idle",
            }
            task = asyncio.create_task(self._worker_loop(i))
            self._tasks.append(task)
        logger.info("Started {} workers", self._worker_count)

    async def stop(self) -> None:
        """Gracefully stop all workers."""
        self._running = False
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        logger.info("All workers stopped")

    def get_stats(self) -> dict[int, dict]:
        """Per-worker statistics."""
        return dict(self._stats)

    async def _worker_loop(self, worker_id: int) -> None:
        """Main loop for a single worker."""
        while self._running:
            try:
                task_data = await self._queue.dequeue()
                if task_data is None:
                    idle_start = time.monotonic()
                    await asyncio.sleep(self._poll_interval)
                    self._stats[worker_id]["total_idle_ms"] += (
                        time.monotonic() - idle_start
                    ) * 1000
                    continue

                self._stats[worker_id]["status"] = "busy"
                task_id = task_data["task_id"]
                task_type = task_data["task_type"]
                payload_size = int(task_data["payload_size"])

                await self._queue.update_status(task_id, "running", worker_id=str(worker_id))

                busy_start = time.monotonic()
                actual_ms = await simulate_task(task_type, payload_size)
                busy_elapsed = (time.monotonic() - busy_start) * 1000

                predicted_ms = float(task_data.get("predicted_ms", 0))
                await self._queue.update_status(
                    task_id,
                    "completed",
                    actual_ms=str(actual_ms),
                )

                self._scheduler.report_completion(task_type, payload_size, actual_ms)

                if self._prediction_tracker is not None:
                    self._prediction_tracker.record(task_type, predicted_ms, actual_ms)

                self._stats[worker_id]["tasks_completed"] += 1
                self._stats[worker_id]["total_busy_ms"] += busy_elapsed
                self._stats[worker_id]["status"] = "idle"

                logger.debug(
                    "Worker {} completed task {} ({}) in {:.0f}ms",
                    worker_id,
                    task_id,
                    task_type,
                    actual_ms,
                )
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Worker {} error", worker_id)
                self._stats[worker_id]["status"] = "idle"
