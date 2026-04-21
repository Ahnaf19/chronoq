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
