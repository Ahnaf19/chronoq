"""Abstract base class for telemetry storage backends."""

from abc import ABC, abstractmethod

from chronoq_ranker.schemas import TaskRecord


class TelemetryStore(ABC):
    """Interface for persisting task execution telemetry."""

    @abstractmethod
    def save(self, record: TaskRecord) -> None:
        """Persist a task record."""

    @abstractmethod
    def get_all(self) -> list[TaskRecord]:
        """Retrieve all stored records."""

    @abstractmethod
    def get_by_type(self, task_type: str) -> list[TaskRecord]:
        """Retrieve records filtered by task type."""

    @abstractmethod
    def count(self) -> int:
        """Total number of stored records."""

    @abstractmethod
    def count_since(self, model_version: str) -> int:
        """Count records collected under the given model version."""
