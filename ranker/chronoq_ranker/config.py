"""Ranker configuration."""

from dataclasses import dataclass, field


@dataclass
class RankerConfig:
    """Configuration for TaskRanker behavior and thresholds."""

    # --- Training / retrain cadence ---
    cold_start_threshold: int = 50
    """Records accumulated before switching from heuristic to the ML estimator."""

    retrain_every_n: int = 100
    """Auto-retrain triggers when this many new records have landed since the last fit."""

    drift_threshold_mae_ms: float = 500.0
    """Rolling MAE over this threshold signals drift (paired with PSI in drift.py)."""

    # --- LambdaRank model hyperparameters ---
    num_leaves: int = 31
    """LightGBM ``num_leaves``. Increase for more expressive trees (watch overfitting)."""

    n_estimators: int = 500
    """Number of boosting rounds for a full refit."""

    learning_rate: float = 0.05
    """LightGBM ``learning_rate`` for both full and incremental fits."""

    min_data_in_leaf: int = 20
    """LightGBM ``min_data_in_leaf`` — minimum samples per leaf node."""

    # --- LambdaRank incremental-fit contract ---
    incremental_rounds: int = 10
    """New boosting rounds added via ``init_model`` warm-start on each incremental fit."""

    min_groups: int = 20
    """Minimum query-groups required for a LambdaRank fit; fewer raises InsufficientGroupsError."""

    full_refit_every_n_incrementals: int = 20
    """Force a full refit every N incremental fits to bound accumulation drift."""

    # --- Drift detection ---
    psi_threshold: float = 0.2
    """PSI per-feature: warn above this, flag as drift above 0.3 (hard-coded ratio)."""

    # --- Fallback behavior ---
    allow_degrade: bool = True
    """Fall back to GradientEstimator when LambdaRank raises InsufficientGroupsError.
    Set to False to fail loud instead (required if you want strict LTR-only behavior)."""

    # --- I/O ---
    feature_columns: list[str] = field(
        default_factory=lambda: ["task_type", "payload_size", "hour_of_day", "queue_depth"]
    )
    """Legacy v1 feature list. Superseded by ``FeatureSchema`` in Chunk 1; kept for compat."""

    storage_uri: str = "sqlite:///chronoq_telemetry.db"


# Deprecated alias — use RankerConfig. Kept for v1 backward compatibility.
PredictorConfig = RankerConfig  # noqa: F821  (legacy alias)
