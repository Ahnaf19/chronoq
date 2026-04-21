"""Metrics and observability API endpoints."""

from collections import deque
from dataclasses import dataclass, field

from fastapi import APIRouter, Request

router = APIRouter(prefix="/metrics", tags=["metrics"])


@dataclass
class PredictionTracker:
    """Ring buffer tracking recent prediction vs actual comparisons."""

    max_size: int = 200
    _entries: deque = field(default_factory=lambda: deque(maxlen=200))

    def record(self, task_type: str, predicted_ms: float, actual_ms: float) -> None:
        """Record a prediction-vs-actual pair."""
        self._entries.append(
            {
                "task_type": task_type,
                "predicted_ms": predicted_ms,
                "actual_ms": actual_ms,
                "error_ms": abs(predicted_ms - actual_ms),
            }
        )

    def recent(self, n: int = 50) -> list[dict]:
        """Get the N most recent entries."""
        entries = list(self._entries)
        return entries[-n:]


@router.get("")
async def get_metrics(request: Request) -> dict:
    """System-wide metrics including queue, predictor, and worker stats."""
    queue = request.app.state.queue
    scheduler = request.app.state.scheduler
    worker_pool = request.app.state.worker_pool

    queue_depth = await queue.length()
    predictor_info = scheduler.get_predictor_info()
    worker_stats = worker_pool.get_stats()

    workers = []
    for wid, stats in worker_stats.items():
        total_time = stats["total_busy_ms"] + stats["total_idle_ms"]
        utilization = (stats["total_busy_ms"] / total_time * 100) if total_time > 0 else 0.0
        workers.append(
            {
                "id": f"w-{wid}",
                "status": stats["status"],
                "utilization_percent": round(utilization, 1),
                "tasks_completed": stats["tasks_completed"],
            }
        )

    return {
        "queue_depth": queue_depth,
        "prediction": predictor_info,
        "workers": workers,
    }


@router.post("/retrain")
async def trigger_retrain(request: Request) -> dict:
    """Manually trigger predictor retrain."""
    scheduler = request.app.state.scheduler
    result = await scheduler.trigger_retrain()
    return result


@router.get("/predictions")
async def get_predictions(request: Request, n: int = 50) -> list[dict]:
    """Recent prediction-vs-actual history."""
    tracker: PredictionTracker = request.app.state.prediction_tracker
    return tracker.recent(n=n)
