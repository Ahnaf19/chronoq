"""Pydantic models for task records, predictions, and retrain results."""

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field


class TaskRecord(BaseModel):
    """A recorded task execution with timing telemetry.

    The ``group_id``, ``rank_label``, and ``feature_schema_version`` fields
    were added in v2 to support pairwise learning-to-rank training:

    - ``group_id`` groups co-submitted tasks into a "query" for LambdaRank
      (default 60s tumbling window of completion timestamps, or an explicit
      ``batch_id`` from the caller). ``None`` means ungrouped (legacy v1).
    - ``rank_label`` is the pairwise relevance label inside the group
      (``max_rank - rank_ascending_by_actual_ms``); shortest task in a group
      gets the highest label. Computed at retrain time; ``None`` on write.
    - ``feature_schema_version`` pins which ``FeatureSchema`` version the
      record's features match. Retrain validates version equality per window.
      ``"v0-legacy"`` marks records written before the v2 schema existed.
    """

    task_type: str
    payload_size: int
    actual_ms: float
    metadata: dict = Field(default_factory=dict)
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    model_version_at_record: str = ""

    # v2 additions — all defaulted so existing v1 records deserialize unchanged.
    group_id: str | None = None
    rank_label: int | None = None
    feature_schema_version: str = "v0-legacy"


class PredictionResult(BaseModel):
    """Result of a task duration prediction."""

    estimated_ms: float
    confidence: float = Field(ge=0.0, le=1.0)
    model_version: str
    model_type: Literal["heuristic", "gradient_boosting", "lambdarank"]


class RetrainResult(BaseModel):
    """Result of a model retrain cycle."""

    mae: float
    mape: float
    samples_used: int
    model_version: str
    promoted: bool


class FeatureSchema(BaseModel):
    """Versioned feature contract declaring which names/types the extractor emits.

    Attached to every ``TaskRecord`` at write time via ``feature_schema_version``
    so that retrain can validate schema equality across the training window.
    Evolving the schema requires bumping ``version`` and writing an adapter
    (or forcing a full refit on an all-fresh window).
    """

    version: str
    numeric: list[str] = Field(default_factory=list)
    categorical: list[str] = Field(default_factory=list)
    required: list[str] = Field(default_factory=list)


class TaskCandidate(BaseModel):
    """A task waiting to be scored/ranked. Input to ``TaskRanker.predict_scores``.

    ``features`` holds user-supplied pre-execution values (e.g. ``payload_size``,
    ``prompt_length``, ``retry_count``, ``user_tier``). The extractor merges
    these with wall-clock and queue-state context to produce the final feature
    vector. Keep ``features`` small; don't stash anything derived post-execution.
    """

    task_id: str
    task_type: str
    features: dict = Field(default_factory=dict)


class QueueContext(BaseModel):
    """Queue-state snapshot passed to ``FeatureExtractor.extract``.

    Zero-valued defaults let callers pass only the fields they have without
    constructing a full context; the extractor treats missing values as the
    no-information baseline.
    """

    queue_depth: int = 0
    queue_depth_same_type: int = 0
    worker_count_busy: int = 0
    worker_count_idle: int = 0
    recent_mean_ms_this_type: float = 0.0
    recent_p95_ms_this_type: float = 0.0
    recent_count_this_type: int = 0
    time_since_last_retrain_s: float = 0.0
