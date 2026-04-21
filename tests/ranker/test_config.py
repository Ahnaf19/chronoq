"""Tests for RankerConfig."""

from chronoq_ranker.config import RankerConfig


def test_defaults():
    cfg = RankerConfig()
    assert cfg.cold_start_threshold == 50
    assert cfg.retrain_every_n == 100
    assert cfg.drift_threshold_mae_ms == 500.0
    assert "task_type" in cfg.feature_columns
    assert cfg.storage_uri == "sqlite:///chronoq_telemetry.db"


def test_overrides():
    cfg = RankerConfig(cold_start_threshold=20, retrain_every_n=50)
    assert cfg.cold_start_threshold == 20
    assert cfg.retrain_every_n == 50


def test_mutable_default_safety():
    """Ensure feature_columns default is not shared between instances."""
    a = RankerConfig()
    b = RankerConfig()
    a.feature_columns.append("extra")
    assert "extra" not in b.feature_columns
