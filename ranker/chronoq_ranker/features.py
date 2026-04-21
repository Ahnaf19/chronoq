"""Feature extraction for the ranker.

v2 introduces a versioned ``FeatureSchema`` plus a ``FeatureExtractor`` ABC
so users can declare which fields their workload carries. ``DefaultExtractor``
ships the 15-feature default specified in the plan §3.3.

The free-function API (``extract_features``, ``extract_training_features``)
is retained as a deprecated shim for v1 callers.
"""

import warnings
from abc import ABC, abstractmethod
from datetime import UTC, datetime

from chronoq_ranker.schemas import FeatureSchema, QueueContext, TaskCandidate, TaskRecord

_UNKNOWN_CATEGORICAL = "__unknown__"

DEFAULT_SCHEMA_V1 = FeatureSchema(
    version="default-v1-2026-04",
    numeric=[
        "payload_size",
        "hour_of_day",
        "day_of_week",
        "queue_depth",
        "queue_depth_same_type",
        "recent_mean_ms_this_type",
        "recent_p95_ms_this_type",
        "recent_count_this_type",
        "time_since_last_retrain_s",
        "worker_count_busy",
        "worker_count_idle",
        "prompt_length",
        "retry_count",
    ],
    categorical=["task_type", "user_tier"],
    required=["task_type", "payload_size"],
)
"""Default 15-feature contract. Bump ``version`` when the set or encoding changes."""


class FeatureExtractor(ABC):
    """Strategy ABC for extracting a numeric/categorical feature dict from a candidate."""

    schema: FeatureSchema

    @abstractmethod
    def extract(self, candidate: TaskCandidate, context: QueueContext | None = None) -> dict:
        """Extract the feature dict at scoring time (before the task runs)."""

    @abstractmethod
    def extract_from_record(self, record: TaskRecord) -> dict:
        """Reconstruct the feature dict from a historical ``TaskRecord`` at training time."""


class DefaultExtractor(FeatureExtractor):
    """Default 15-feature extractor.

    Null-safe by construction: missing numeric fields default to ``0.0``,
    missing categorical fields default to ``"__unknown__"``. ``hour_of_day``
    and ``day_of_week`` come from wall clock at scoring time, and from
    ``record.recorded_at`` at training time — keeping the same temporal
    features usable in both paths.
    """

    schema: FeatureSchema = DEFAULT_SCHEMA_V1

    def extract(self, candidate: TaskCandidate, context: QueueContext | None = None) -> dict:
        ctx = context or QueueContext()
        now = datetime.now(UTC)
        feat = candidate.features or {}
        return {
            # Categorical
            "task_type": candidate.task_type or _UNKNOWN_CATEGORICAL,
            "user_tier": feat.get("user_tier") or _UNKNOWN_CATEGORICAL,
            # From candidate.features
            "payload_size": _as_float(feat.get("payload_size")),
            "prompt_length": _as_float(feat.get("prompt_length")),
            "retry_count": _as_float(feat.get("retry_count")),
            # Wall-clock
            "hour_of_day": float(now.hour),
            "day_of_week": float(now.weekday()),
            # Queue context
            "queue_depth": float(ctx.queue_depth),
            "queue_depth_same_type": float(ctx.queue_depth_same_type),
            "worker_count_busy": float(ctx.worker_count_busy),
            "worker_count_idle": float(ctx.worker_count_idle),
            "recent_mean_ms_this_type": ctx.recent_mean_ms_this_type,
            "recent_p95_ms_this_type": ctx.recent_p95_ms_this_type,
            "recent_count_this_type": float(ctx.recent_count_this_type),
            "time_since_last_retrain_s": ctx.time_since_last_retrain_s,
        }

    def extract_from_record(self, record: TaskRecord) -> dict:
        meta = record.metadata or {}
        return {
            # Categorical
            "task_type": record.task_type or _UNKNOWN_CATEGORICAL,
            "user_tier": meta.get("user_tier") or _UNKNOWN_CATEGORICAL,
            # From record + metadata (mirror of scoring-time extract)
            "payload_size": float(record.payload_size),
            "prompt_length": _as_float(meta.get("prompt_length")),
            "retry_count": _as_float(meta.get("retry_count")),
            # Wall-clock from the recorded timestamp
            "hour_of_day": float(record.recorded_at.hour),
            "day_of_week": float(record.recorded_at.weekday()),
            # Queue context as captured in metadata (v1 recorded only queue_depth)
            "queue_depth": _as_float(meta.get("queue_depth")),
            "queue_depth_same_type": _as_float(meta.get("queue_depth_same_type")),
            "worker_count_busy": _as_float(meta.get("worker_count_busy")),
            "worker_count_idle": _as_float(meta.get("worker_count_idle")),
            "recent_mean_ms_this_type": _as_float(meta.get("recent_mean_ms_this_type")),
            "recent_p95_ms_this_type": _as_float(meta.get("recent_p95_ms_this_type")),
            "recent_count_this_type": _as_float(meta.get("recent_count_this_type")),
            "time_since_last_retrain_s": _as_float(meta.get("time_since_last_retrain_s")),
        }


def _as_float(value: object) -> float:
    """Null-safe numeric cast; missing / non-numeric → 0.0."""
    if value is None:
        return 0.0
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


# ---------------------------------------------------------------------------
# Deprecated v1 shims — used by demo-server + existing models. Kept through
# Chunk 1; remove once all call sites migrate to DefaultExtractor.
# ---------------------------------------------------------------------------


def _legacy_extract_features(
    task_type: str, payload_size: int, metadata: dict | None = None
) -> dict:
    """Silent v1 4-feature extractor — internal use only (no DeprecationWarning)."""
    meta = metadata or {}
    return {
        "task_type": task_type,
        "payload_size": payload_size,
        "hour_of_day": datetime.now(UTC).hour,
        "queue_depth": meta.get("queue_depth", 0),
    }


def _legacy_extract_training_features(record: TaskRecord) -> dict:
    """Silent v1 training-time extractor — internal use only (no DeprecationWarning)."""
    return {
        "task_type": record.task_type,
        "payload_size": record.payload_size,
        "hour_of_day": record.recorded_at.hour,
        "queue_depth": record.metadata.get("queue_depth", 0),
    }


def extract_features(task_type: str, payload_size: int, metadata: dict | None = None) -> dict:
    """Deprecated v1 free-function extractor. Use ``DefaultExtractor`` instead."""
    warnings.warn(
        "extract_features is deprecated; use DefaultExtractor.extract(TaskCandidate, ...).",
        DeprecationWarning,
        stacklevel=2,
    )
    return _legacy_extract_features(task_type, payload_size, metadata)


def extract_training_features(record: TaskRecord) -> dict:
    """Deprecated v1 training-time extractor. Use ``DefaultExtractor.extract_from_record``."""
    warnings.warn(
        "extract_training_features is deprecated; "
        "use DefaultExtractor.extract_from_record(record).",
        DeprecationWarning,
        stacklevel=2,
    )
    return _legacy_extract_training_features(record)
