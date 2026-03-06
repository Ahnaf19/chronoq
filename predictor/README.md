# chronoq-predictor

Standalone ML library for predicting task execution time. Auto-promotes from heuristic (per-type mean) to GradientBoosting after collecting enough telemetry.

## Install

```bash
pip install chronoq-predictor
```

## Quick Start

```python
from chronoq_predictor import TaskPredictor

predictor = TaskPredictor(storage="sqlite:///telemetry.db")

# Predict execution time
estimate = predictor.predict("resize_image", payload_size=2048)
print(f"{estimate.estimated_ms:.0f}ms (confidence: {estimate.confidence:.2f})")

# Record actual execution
predictor.record("resize_image", payload_size=2048, actual_ms=312)

# Retrain (also auto-triggered every N records)
metrics = predictor.retrain()
print(f"MAE: {metrics.mae:.1f}ms, promoted: {metrics.promoted}")
```

## Configuration

```python
from chronoq_predictor import PredictorConfig, TaskPredictor

config = PredictorConfig(
    cold_start_threshold=50,     # Records before promoting to GradientBoosting
    retrain_every_n=100,         # Auto-retrain interval
    drift_threshold_mae_ms=500,  # MAE threshold for drift detection
    storage_uri="sqlite:///telemetry.db",
)
predictor = TaskPredictor(config=config)
```

## Storage Backends

- `"memory://"` — In-memory (testing/ephemeral)
- `"sqlite:///path/to/db"` — SQLite (persistent)

## Integration Patterns

Works with any task system — Celery, Kafka, FastAPI background tasks, custom workers:

```python
# Before task execution
estimate = predictor.predict(task_type, payload_size, metadata={"queue_depth": 14})

# After task execution
predictor.record(task_type, payload_size, actual_ms=elapsed)
```
