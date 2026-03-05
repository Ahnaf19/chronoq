"""Predictor configuration."""

from dataclasses import dataclass, field


@dataclass
class PredictorConfig:
    """Configuration for TaskPredictor behavior and thresholds."""

    cold_start_threshold: int = 50
    retrain_every_n: int = 100
    drift_threshold_mae_ms: float = 500.0
    feature_columns: list[str] = field(
        default_factory=lambda: ["task_type", "payload_size", "hour_of_day", "queue_depth"]
    )
    storage_uri: str = "sqlite:///chronoq_telemetry.db"
