"""Chronoq ranker — learning-to-rank scheduling library for Python job queues."""

from typing import TYPE_CHECKING

from chronoq_ranker.config import RankerConfig
from chronoq_ranker.features import DEFAULT_SCHEMA_V1, DefaultExtractor, FeatureExtractor
from chronoq_ranker.ranker import TaskRanker
from chronoq_ranker.schemas import (
    FeatureSchema,
    PredictionResult,
    QueueContext,
    RetrainResult,
    ScoredTask,
    TaskCandidate,
    TaskRecord,
)

__all__ = [
    "TaskRanker",
    "RankerConfig",
    "PredictionResult",
    "RetrainResult",
    "TaskRecord",
    "TaskCandidate",
    "ScoredTask",
    "QueueContext",
    "FeatureSchema",
    "FeatureExtractor",
    "DefaultExtractor",
    "DEFAULT_SCHEMA_V1",
    # Deprecated v1 aliases (remove in next major version):
    "TaskPredictor",
    "PredictorConfig",
]

if TYPE_CHECKING:
    # Names surfaced via ``__getattr__`` below; re-declare for static checkers.
    TaskPredictor = TaskRanker
    PredictorConfig = RankerConfig


def __getattr__(name: str):
    """Deprecation shim for v1 top-level names.

    ``from chronoq_ranker import TaskPredictor`` and
    ``from chronoq_ranker import PredictorConfig`` keep working but emit
    ``DeprecationWarning`` pointing at the v2 replacement.
    """
    import warnings

    aliases = {
        "TaskPredictor": ("TaskRanker", TaskRanker),
        "PredictorConfig": ("RankerConfig", RankerConfig),
    }
    if name in aliases:
        new_name, target = aliases[name]
        warnings.warn(
            f"chronoq_ranker.{name} is deprecated; use chronoq_ranker.{new_name}.",
            DeprecationWarning,
            stacklevel=2,
        )
        return target
    raise AttributeError(f"module 'chronoq_ranker' has no attribute {name!r}")
