"""Scheduler: bridges the predictor to the Redis queue."""

import asyncio

from chronoq_ranker import PredictionResult, TaskPredictor

from chronoq_demo_server.core.queue import TaskQueue


class Scheduler:
    """Coordinates prediction scoring and telemetry feedback."""

    def __init__(self, predictor: TaskPredictor, queue: TaskQueue) -> None:
        self._predictor = predictor
        self._queue = queue

    async def score_and_enqueue(
        self,
        task_id: str,
        task_type: str,
        payload_size: int,
        metadata: dict | None = None,
    ) -> PredictionResult:
        """Predict duration, enqueue with predicted_ms as SJF score."""
        prediction = self._predictor.predict(task_type, payload_size, metadata)
        await self._queue.enqueue(
            task_id=task_id,
            task_type=task_type,
            payload_size=payload_size,
            predicted_ms=prediction.estimated_ms,
            metadata=metadata,
        )
        return prediction

    def report_completion(
        self,
        task_type: str,
        payload_size: int,
        actual_ms: float,
        metadata: dict | None = None,
    ) -> None:
        """Record actual execution time to feed the predictor."""
        self._predictor.record(task_type, payload_size, actual_ms, metadata)

    async def trigger_retrain(self) -> dict:
        """Non-blocking retrain via thread executor."""
        result = await asyncio.to_thread(self._predictor.retrain)
        return result.model_dump()

    def get_predictor_info(self) -> dict:
        """Current model version, type, and record count."""
        return {
            "model_version": self._predictor._estimator.version(),
            "model_type": self._predictor._estimator.model_type(),
            "total_records": self._predictor._store.count(),
        }
