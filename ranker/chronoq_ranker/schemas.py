"""Pydantic models for task records, predictions, and retrain results."""

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field


class TaskRecord(BaseModel):
    """A recorded task execution with timing telemetry."""

    task_type: str
    payload_size: int
    actual_ms: float
    metadata: dict = Field(default_factory=dict)
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    model_version_at_record: str = ""


class PredictionResult(BaseModel):
    """Result of a task duration prediction."""

    estimated_ms: float
    confidence: float = Field(ge=0.0, le=1.0)
    model_version: str
    model_type: Literal["heuristic", "gradient_boosting"]


class RetrainResult(BaseModel):
    """Result of a model retrain cycle."""

    mae: float
    mape: float
    samples_used: int
    model_version: str
    promoted: bool
