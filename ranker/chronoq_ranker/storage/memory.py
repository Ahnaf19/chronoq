"""In-memory telemetry storage for testing and ephemeral use."""

from chronoq_ranker.schemas import TaskRecord
from chronoq_ranker.storage.base import TelemetryStore


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

    def count_since(self, model_version: str) -> int:
        return sum(1 for r in self._records if r.model_version_at_record == model_version)
