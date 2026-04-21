"""Abstract base class for prediction estimators."""

from abc import ABC, abstractmethod
from typing import Literal

from chronoq_ranker.schemas import TaskRecord

ModelType = Literal["heuristic", "gradient_boosting", "lambdarank", "oracle_sjf", "oracle_srpt"]


class BaseEstimator(ABC):
    """Interface for task duration / ranking estimators."""

    @abstractmethod
    def fit(self, records: list[TaskRecord]) -> dict:
        """Train on historical records. Returns metrics dict."""

    @abstractmethod
    def predict(self, features: dict) -> tuple[float, float]:
        """Predict a score for a single candidate. Returns (score, confidence).

        For heuristic/gradient models, ``score`` is estimated duration in ms
        (lower = scheduled sooner). For LambdaRank, ``score`` is a negated
        pairwise rank score (lower = scheduled sooner). For oracle, ``score``
        is the true ``actual_ms`` from the features dict.
        """

    def predict_batch(self, feature_dicts: list[dict]) -> list[tuple[float, float]]:
        """Predict scores for a batch. Default: call predict() per item.

        Subclasses may override for efficiency (e.g. LambdaRankEstimator calls
        the underlying LGBM model once for the whole matrix).
        """
        return [self.predict(f) for f in feature_dicts]

    @abstractmethod
    def version(self) -> str:
        """Current model version string."""

    @abstractmethod
    def model_type(self) -> ModelType:
        """Model type identifier."""
