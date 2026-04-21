"""Feature extraction for prediction models."""

from datetime import UTC, datetime

from chronoq_ranker.schemas import TaskRecord


def extract_features(task_type: str, payload_size: int, metadata: dict | None = None) -> dict:
    """Extract feature dict from task parameters for prediction."""
    meta = metadata or {}
    return {
        "task_type": task_type,
        "payload_size": payload_size,
        "hour_of_day": datetime.now(UTC).hour,
        "queue_depth": meta.get("queue_depth", 0),
    }


def extract_training_features(record: TaskRecord) -> dict:
    """Extract feature dict from a historical TaskRecord for training."""
    return {
        "task_type": record.task_type,
        "payload_size": record.payload_size,
        "hour_of_day": record.recorded_at.hour,
        "queue_depth": record.metadata.get("queue_depth", 0),
    }
