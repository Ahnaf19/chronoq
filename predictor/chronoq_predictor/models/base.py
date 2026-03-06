"""Abstract base class for prediction estimators."""

from abc import ABC, abstractmethod

from chronoq_predictor.schemas import TaskRecord


class BaseEstimator(ABC):
    """Interface for task duration estimators."""

    @abstractmethod
    def fit(self, records: list[TaskRecord]) -> dict:
        """Train on historical records. Returns metrics dict."""

    @abstractmethod
    def predict(self, features: dict) -> tuple[float, float]:
        """Predict duration. Returns (estimated_ms, confidence)."""

    @abstractmethod
    def version(self) -> str:
        """Current model version string."""

    @abstractmethod
    def model_type(self) -> str:
        """Model type identifier."""
