# Configuration Reference

## Server Environment Variables

All server configuration is read from environment variables with sensible defaults.

| Variable | Default | Description |
|----------|---------|-------------|
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection URL |
| `CHRONOQ_WORKER_COUNT` | `4` | Number of async worker coroutines |
| `CHRONOQ_QUEUE_KEY` | `chronoq:tasks` | Redis sorted set key for the task queue |
| `CHRONOQ_TASK_PREFIX` | `chronoq:task:` | Prefix for task detail hash keys in Redis |
| `CHRONOQ_PREDICTOR_STORAGE` | `sqlite:///chronoq_telemetry.db` | Predictor telemetry storage URI |
| `CHRONOQ_COLD_START` | `50` | Records before auto-promoting to GradientBoosting |
| `CHRONOQ_RETRAIN_EVERY` | `100` | Auto-retrain after this many new records |

### Example .env file

```bash
REDIS_URL=redis://localhost:6379/0
CHRONOQ_WORKER_COUNT=8
CHRONOQ_PREDICTOR_STORAGE=sqlite:///production_telemetry.db
CHRONOQ_COLD_START=100
CHRONOQ_RETRAIN_EVERY=200
```

---

## Predictor Library Configuration

When using `chronoq-predictor` standalone, configure via `PredictorConfig`:

```python
from chronoq_predictor import PredictorConfig, TaskPredictor

config = PredictorConfig(
    cold_start_threshold=50,     # Min records for ML model promotion
    retrain_every_n=100,         # Auto-retrain interval
    drift_threshold_mae_ms=500,  # MAE threshold for drift detection
    feature_columns=[            # Features used by the model
        "task_type",
        "payload_size",
        "hour_of_day",
        "queue_depth",
    ],
    storage_uri="sqlite:///telemetry.db",
)

predictor = TaskPredictor(config=config)
```

### PredictorConfig Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `cold_start_threshold` | int | 50 | Minimum records before promoting from heuristic to GradientBoosting |
| `retrain_every_n` | int | 100 | Number of new records that triggers auto-retrain |
| `drift_threshold_mae_ms` | float | 500.0 | MAE threshold for prediction drift detection |
| `feature_columns` | list[str] | see above | Feature names used by the ML model |
| `storage_uri` | str | `sqlite:///chronoq_telemetry.db` | Storage backend URI |

### Storage URIs

| URI Pattern | Backend | Use Case |
|-------------|---------|----------|
| `memory://` | In-memory list | Testing, ephemeral workflows |
| `sqlite:///path/to/db` | SQLite file | Production, single-node persistence |

---

## Docker Compose Configuration

The `docker-compose.yml` configures two services:

```yaml
services:
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
  chronoq:
    build: .
    ports:
      - "8000:8000"
    depends_on:
      - redis
    environment:
      - REDIS_URL=redis://redis:6379/0
```

Override any server variable in the `environment` section:

```yaml
    environment:
      - REDIS_URL=redis://redis:6379/0
      - CHRONOQ_WORKER_COUNT=8
      - CHRONOQ_COLD_START=100
```

---

## Redis Key Layout

| Key Pattern | Type | Purpose |
|-------------|------|---------|
| `chronoq:tasks` | Sorted Set | SJF queue (score = predicted_ms) |
| `chronoq:task:{uuid}` | Hash | Task details (type, payload, status, times) |

### Task Hash Fields

| Field | Description |
|-------|-------------|
| `task_id` | UUID |
| `task_type` | Task category string |
| `payload_size` | Integer payload size |
| `predicted_ms` | Predicted execution time |
| `metadata` | JSON-encoded metadata dict |
| `status` | `pending` / `running` / `completed` |
| `submitted_at` | ISO 8601 timestamp |
| `worker_id` | Worker that processed the task (set on running) |
| `actual_ms` | Actual execution time (set on completed) |
