"""Ranker configuration."""

from dataclasses import dataclass, field


@dataclass
class RankerConfig:
    """Configuration for TaskRanker behavior and thresholds."""

    cold_start_threshold: int = 50
    retrain_every_n: int = 100
    drift_threshold_mae_ms: float = 500.0
    feature_columns: list[str] = field(
        default_factory=lambda: ["task_type", "payload_size", "hour_of_day", "queue_depth"]
    )
    storage_uri: str = "sqlite:///chronoq_telemetry.db"


# Deprecated alias — use RankerConfig. Kept for v1 backward compatibility.
PredictorConfig = RankerConfig  # noqa: F821  (legacy alias)
