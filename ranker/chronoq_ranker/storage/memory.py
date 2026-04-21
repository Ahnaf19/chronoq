"""In-memory telemetry storage for testing and ephemeral use."""

from __future__ import annotations

from typing import TYPE_CHECKING

from chronoq_ranker.storage.base import TelemetryStore

if TYPE_CHECKING:
    from datetime import datetime

    from chronoq_ranker.schemas import TaskRecord


class MemoryStore(TelemetryStore):
    """List-backed in-memory storage."""

    def __init__(self) -> None:
        self._records: list[TaskRecord] = []

    def save(self, record: TaskRecord) -> None:
        self._records.append(record)

    def get_all(self) -> list[TaskRecord]:
        return list(self._records)

    def get_by_type(self, task_type: str) -> list[TaskRecord]:
        return [r for r in self._records if r.task_type == task_type]

    def count(self) -> int:
        return len(self._records)

    def count_since(self, after: datetime) -> int:
        """Count records with recorded_at strictly after the given datetime."""
        return sum(1 for r in self._records if r.recorded_at > after)
