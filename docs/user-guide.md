# User Guide

## Getting Started

### Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) package manager
- Redis 7+ (for the server; not needed for predictor-only usage)
- Docker + Docker Compose (optional, for containerized setup)

### Installation

```bash
# Clone and install
git clone <repo-url> chronoq
cd chronoq
uv sync
```

### Verify Installation

```bash
uv run pytest -v
```

All 71 tests should pass.

---

## Using chronoq-predictor Standalone

The predictor library works independently of the server. Use it in any Python project to predict task execution time.

### Basic Usage

```python
from chronoq_ranker import TaskPredictor

# Create predictor with SQLite persistence
predictor = TaskPredictor(storage="sqlite:///my_telemetry.db")

# Before running a task: predict how long it will take
estimate = predictor.predict("resize_image", payload_size=2048)
print(f"Estimated: {estimate.estimated_ms:.0f}ms")
print(f"Confidence: {estimate.confidence:.2f}")
print(f"Model: {estimate.model_type}")

# After running a task: record the actual time
predictor.record("resize_image", payload_size=2048, actual_ms=312)

# The predictor auto-retrains after enough records
# You can also manually trigger retrain:
result = predictor.retrain()
print(f"MAE: {result.mae:.1f}ms, Promoted: {result.promoted}")
```

### With Custom Configuration

```python
from chronoq_ranker import PredictorConfig, TaskPredictor

config = PredictorConfig(
    cold_start_threshold=30,   # Promote to ML after 30 records (default: 50)
    retrain_every_n=50,        # Retrain every 50 new records (default: 100)
    storage_uri="sqlite:///custom.db",
)
predictor = TaskPredictor(config=config)
```

### In-Memory Mode (Testing)

```python
predictor = TaskPredictor(storage="memory://")
```

### Integration with Celery

```python
from celery import Celery
from chronoq_ranker import TaskPredictor

app = Celery("tasks")
predictor = TaskPredictor(storage="sqlite:///celery_telemetry.db")

@app.task
def process_image(image_path: str):
    import time
    payload_size = os.path.getsize(image_path)

    # Predict (useful for monitoring, ETAs, scheduling decisions)
    estimate = predictor.predict("process_image", payload_size)

    start = time.monotonic()
    # ... actual work ...
    actual_ms = (time.monotonic() - start) * 1000

    # Record for future predictions
    predictor.record("process_image", payload_size, actual_ms)
```

### Integration with Kafka Workers

```python
from chronoq_ranker import TaskPredictor

predictor = TaskPredictor(storage="sqlite:///kafka_telemetry.db")

for message in consumer:
    task_type = message.value["type"]
    payload_size = len(message.value["data"])

    estimate = predictor.predict(task_type, payload_size)

    # If predicted duration exceeds poll interval, pause partition
    if estimate.estimated_ms > MAX_POLL_INTERVAL_MS:
        consumer.pause([partition])

    actual_ms = execute_task(message)
    predictor.record(task_type, payload_size, actual_ms)

    if consumer.paused([partition]):
        consumer.resume([partition])
```

---

## Running the Full Server

### Option 1: Local Development

```bash
# Start Redis
docker-compose up -d redis

# Start the server with auto-reload
uv run uvicorn chronoq_demo_server.main:app --reload --port 8000
```

### Option 2: Docker Compose

```bash
docker-compose up
```

This starts both Redis and the Chronoq server.

### Submit a Task

```bash
curl -X POST http://localhost:8000/tasks \
  -H "Content-Type: application/json" \
  -d '{"task_type": "resize_image", "payload_size": 2048}'
```

Response:
```json
{
  "task_id": "a1b2c3d4-...",
  "predicted_ms": 402.0,
  "confidence": 0.1,
  "model_type": "heuristic"
}
```

### Check Task Status

```bash
curl http://localhost:8000/tasks/{task_id}
```

### View Queue (SJF Order)

```bash
curl http://localhost:8000/tasks
```

### Monitor Metrics

```bash
curl http://localhost:8000/metrics
```

### Run the Demo

The demo script submits 200 tasks and monitors the queue draining in real time:

```bash
uv run python demo.py
```

You'll see:
1. Tasks submitting
2. Queue depth decreasing as workers process jobs
3. Model promoting from heuristic to gradient_boosting (after ~50 tasks)
4. Final prediction accuracy comparison

---

## Configuration Reference

All server configuration is via environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection URL |
| `CHRONOQ_WORKER_COUNT` | `4` | Number of async worker coroutines |
| `CHRONOQ_QUEUE_KEY` | `chronoq:tasks` | Redis key for the sorted set queue |
| `CHRONOQ_TASK_PREFIX` | `chronoq:task:` | Prefix for task hash keys in Redis |
| `CHRONOQ_PREDICTOR_STORAGE` | `sqlite:///chronoq_telemetry.db` | Predictor storage URI |
| `CHRONOQ_COLD_START` | `50` | Records before promoting to GradientBoosting |
| `CHRONOQ_RETRAIN_EVERY` | `100` | Auto-retrain interval (records since last train) |

See `.env.example` for a template.

---

## Database Migrations

For production deployments with schema evolution needs, Chronoq includes Alembic migrations:

```bash
# Install Alembic (optional dependency)
pip install alembic sqlalchemy

# Apply migrations
alembic -c migrations/alembic.ini upgrade head

# Check current version
alembic -c migrations/alembic.ini current
```

Note: The `SqliteStore` auto-creates the table on first use via `CREATE TABLE IF NOT EXISTS`. Migrations are only needed when upgrading existing databases to new schema versions.

---

## Troubleshooting

### "No module named chronoq_ranker"
Run `uv sync` to install workspace packages.

### Redis connection refused
Ensure Redis is running: `docker-compose up -d redis`

### Predictor always returns heuristic
You need at least `cold_start_threshold` (default 50) recorded task executions before the model promotes to GradientBoosting.

### High MAE after promotion
The GradientBoosting model needs diverse data. Ensure you're recording multiple task types with varying payload sizes. You can lower `retrain_every_n` for more frequent retraining.
