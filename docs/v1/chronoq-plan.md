# Chronoq — Self-Optimizing Task Queue with ML-Based SJF Scheduling

## Idea

Every task queue (Celery, Bull, ARQ, custom Kafka workers) processes jobs in FIFO order by default. But FIFO is suboptimal for average wait time — if a 10-second job is stuck behind a 10-minute job, everything waits. Operating systems solved this decades ago with **Shortest Job First (SJF)** scheduling, which is provably optimal for minimizing average wait time. The problem? SJF requires knowing how long a job will take *before* it runs.

Chronoq solves this by **learning execution time from historical telemetry** and using those predictions to reorder the queue in real time.

## Goal

Build two deliverables:

1. **`chronoq-predictor`** — A standalone, pip-installable Python library that any project can drop in to predict task execution time. Three methods: `predict()`, `record()`, `retrain()`. Zero coupling to any specific queue, broker, or framework.
2. **`chronoq`** — A complete self-optimizing task queue that imports `chronoq-predictor` and builds SJF scheduling, async workers, and a metrics API on top. Serves as both a usable system and a reference implementation for the library.

## What This Demonstrates

- **Systems design**: task queues, Redis sorted sets, async worker pools, priority scheduling
- **ML in production patterns**: cold-start → warm model promotion, auto-retrain, prediction drift detection, feature engineering from system telemetry
- **Software architecture**: strategy pattern for models, pluggable storage backends, clean separation between library and application
- **Theoretical grounding**: SJF scheduling from OS theory, applied to real distributed workloads
- **API design**: FastAPI, Pydantic contracts, metrics/observability endpoints

## How It Works (End to End)

1. Client submits a task via REST (`POST /tasks` with `task_type`, `payload_size`, optional `metadata`)
2. Chronoq calls `predictor.predict()` → gets estimated duration in ms
3. Task is inserted into a Redis sorted set with `score = estimated_ms` (lowest score = shortest job = popped first)
4. Async workers pop from the sorted set (always the shortest predicted job), execute, and record actual duration back to the predictor
5. After enough telemetry accumulates, the predictor auto-promotes from a simple heuristic (per-type moving average) to a GradientBoosting regressor — predictions get sharper over time
6. The metrics API exposes predicted vs actual accuracy, model version, worker utilization, and throughput

## Project Structure

```
chronoq/                          # monorepo
├── chronoq_ranker/            # standalone library (Layer 1)
│   ├── ...
│   └── README.md
├── chronoq_demo_server/               # full queue system (Layer 2)
│   ├── ...
│   └── README.md
├── demo.py                       # end-to-end demo script
├── docker-compose.yml
└── README.md                     # top-level overview
```

---

## Part 1: `chronoq-predictor` (Standalone Library)

### Public API (3 methods)

```python
from chronoq_ranker import TaskPredictor

predictor = TaskPredictor(storage="sqlite:///telemetry.db")

# 1. Predict execution time before running a task
estimate = predictor.predict(task_type="resize_image", payload_size=2048)
# => PredictionResult(estimated_ms=340, confidence=0.82, model_version="v3")

# 2. Record actual execution after task completes
predictor.record(
    task_type="resize_image",
    payload_size=2048,
    actual_ms=312,
    metadata={"worker": "w-03", "queue_depth": 14}
)

# 3. Retrain the model (manual or auto-triggered)
metrics = predictor.retrain()
# => RetrainResult(mae=45.2, samples_used=1200, model_version="v4")
```

### Directory Structure

```
chronoq_ranker/
├── __init__.py          # exports TaskPredictor
├── predictor.py         # main class — predict / record / retrain
├── features.py          # feature engineering (extract + transform)
├── models/
│   ├── base.py          # abstract BaseEstimator interface
│   ├── heuristic.py     # cold-start: moving average per task_type
│   └── gradient.py      # warm: GradientBoostingRegressor
├── storage/
│   ├── base.py          # abstract TelemetryStore
│   ├── sqlite.py        # SQLite implementation
│   └── memory.py        # in-memory (for testing / ephemeral use)
├── schemas.py           # PredictionResult, RetrainResult, TaskRecord (Pydantic)
└── config.py            # thresholds, retrain triggers, feature config
```

### Module Specifications

#### `schemas.py`
Pydantic models:
- `TaskRecord`: task_type (str), payload_size (int), actual_ms (float), metadata (dict, optional), recorded_at (datetime, auto)
- `PredictionResult`: estimated_ms (float), confidence (float, 0-1), model_version (str), model_type (str: "heuristic" | "gradient_boosting")
- `RetrainResult`: mae (float), mape (float), samples_used (int), model_version (str), promoted (bool — true if model type changed)

#### `config.py`
Dataclass `PredictorConfig`:
- `cold_start_threshold`: int = 50 — minimum records before auto-promoting from heuristic to ML model
- `retrain_every_n`: int = 100 — auto-retrain after N new records since last training
- `drift_threshold_mae_ms`: float = 500.0 — if rolling MAE exceeds this, force retrain
- `feature_columns`: list = ["task_type", "payload_size", "hour_of_day", "queue_depth"]
- `storage_uri`: str = "sqlite:///chronoq_telemetry.db"

#### `storage/base.py`
Abstract class `TelemetryStore`:
- `save(record: TaskRecord) -> None`
- `get_all() -> list[TaskRecord]`
- `get_by_type(task_type: str) -> list[TaskRecord]`
- `count() -> int`
- `count_since(model_version: str) -> int` — records added since last retrain

#### `storage/sqlite.py`
SQLite implementation of `TelemetryStore`.

Table schema:
```sql
CREATE TABLE IF NOT EXISTS telemetry (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_type TEXT NOT NULL,
    payload_size INTEGER,
    actual_ms REAL NOT NULL,
    metadata_json TEXT,
    hour_of_day INTEGER,
    queue_depth INTEGER,
    recorded_at TEXT NOT NULL,
    model_version_at_prediction TEXT
);
```

#### `storage/memory.py`
In-memory list-based implementation. Useful for testing or ephemeral workflows.

#### `models/base.py`
Abstract class `BaseEstimator`:
- `fit(records: list[TaskRecord]) -> dict` — returns training metrics
- `predict(features: dict) -> tuple[float, float]` — returns (estimated_ms, confidence)
- `version() -> str`
- `model_type() -> str`

#### `models/heuristic.py`
Class `HeuristicEstimator(BaseEstimator)`:
- Maintains a running mean + std per `task_type`
- `predict()`: returns mean for that type, confidence = 1 / (1 + normalized_std)
- `fit()`: recalculates means from all records
- If task_type unseen: return global mean, confidence = 0.3

#### `models/gradient.py`
Class `GradientEstimator(BaseEstimator)`:
- Uses `sklearn.ensemble.GradientBoostingRegressor`
- Features: task_type (label encoded), payload_size, hour_of_day, queue_depth
- `fit()`: train on all records, compute MAE + MAPE on 20% holdout, increment version
- `predict()`: return prediction + confidence derived from model's staged_predict variance
- Fallback: if prediction fails (unseen category etc.), delegate to HeuristicEstimator

#### `features.py`
Function `extract_features(task_type, payload_size, metadata=None) -> dict`:
- Encodes task_type via a label map (built during fit, stored on the estimator)
- Extracts hour_of_day from current time
- Extracts queue_depth from metadata if present, else 0
- Returns flat dict ready for model input

#### `predictor.py`
Class `TaskPredictor`:
- Constructor: takes `PredictorConfig` or `storage` URI string (convenience)
- Initializes storage + starts with `HeuristicEstimator`
- **`predict(task_type, payload_size, metadata=None) -> PredictionResult`**:
  - Extract features
  - Get estimate from current model
  - Return PredictionResult
- **`record(task_type, payload_size, actual_ms, metadata=None) -> None`**:
  - Save to storage
  - Check if auto-retrain trigger hit (count_since or drift)
  - If triggered → call retrain()
- **`retrain() -> RetrainResult`**:
  - Pull all records from storage
  - If count < cold_start_threshold → fit heuristic only
  - Else → fit GradientEstimator (auto-promotion)
  - Return RetrainResult with metrics and whether promotion happened

---

## Part 2: `chronoq` (Full Task Queue System)

### Directory Structure

```
chronoq/
├── main.py              # FastAPI app entry point
├── api/
│   ├── tasks.py         # task submission + status endpoints
│   └── metrics.py       # metrics + dashboard endpoints
├── core/
│   ├── queue.py         # Redis sorted set queue manager
│   ├── worker.py        # async worker pool
│   └── scheduler.py     # bridges predictor → Redis scoring
├── task_registry.py     # simulated task definitions
├── config.py            # app config (Redis URL, worker count, etc.)
├── docker-compose.yml   # Redis + app
└── demo.py              # script to flood queue and show SJF in action
```

### Component Specifications

#### `config.py`
- `REDIS_URL`: str = "redis://localhost:6379/0"
- `WORKER_COUNT`: int = 4
- `QUEUE_KEY`: str = "chronoq:tasks"
- `PREDICTOR_STORAGE`: str = "sqlite:///chronoq_telemetry.db"

#### `task_registry.py`
Simulated tasks that sleep for variable durations to mimic real work. Each task type has a characteristic time profile so the ML model has learnable patterns.

```python
TASK_REGISTRY = {
    "resize_image": {
        "base_ms": 300,    # avg execution time
        "variance": 80,    # std deviation
        "payload_factor": 0.05  # ms added per byte of payload_size
    },
    "send_email": {
        "base_ms": 150,
        "variance": 30,
        "payload_factor": 0.01
    },
    "generate_report": {
        "base_ms": 2000,
        "variance": 500,
        "payload_factor": 0.1
    },
    "compress_file": {
        "base_ms": 800,
        "variance": 200,
        "payload_factor": 0.08
    },
    "run_inference": {
        "base_ms": 1500,
        "variance": 400,
        "payload_factor": 0.12
    }
}
```

Simulated execution: `actual_ms = base_ms + (payload_size * payload_factor) + random.gauss(0, variance)` then `await asyncio.sleep(actual_ms / 1000)`.

#### `core/queue.py`
Class `TaskQueue`:
- Uses Redis sorted set (`ZADD`) where score = predicted_ms from predictor
- `enqueue(task_id, task_type, payload_size, metadata) -> None`:
  - Call predictor.predict() to get estimated_ms
  - Store task details in Redis hash `chronoq:task:{task_id}`
  - ZADD to sorted set with score = estimated_ms (SJF: lowest score popped first)
- `dequeue() -> task_dict | None`:
  - ZPOPMIN from sorted set (gets lowest score = shortest predicted job)
  - Fetch task details from hash
- `length() -> int`
- `peek(n=10) -> list` — show top N tasks in queue order

Task hash stores: `{task_id, task_type, payload_size, metadata, predicted_ms, status, submitted_at}`

Status transitions: `pending → running → completed | failed`

#### `core/scheduler.py`
Class `Scheduler`:
- Holds an instance of `TaskPredictor` from `chronoq-predictor`
- `score_task(task_type, payload_size, metadata) -> PredictionResult` — thin wrapper
- `report_completion(task_type, payload_size, actual_ms, metadata) -> None` — calls predictor.record()
- `get_predictor_metrics() -> dict` — exposes model version, type, sample count

#### `core/worker.py`
Class `WorkerPool`:
- Spawns N async worker coroutines
- Each worker loops:
  1. `task = queue.dequeue()` (if None, sleep 100ms and retry)
  2. Update status to `running`, record `started_at`
  3. Execute simulated task from registry
  4. Record `completed_at`, compute `actual_ms`
  5. Call `scheduler.report_completion(...)` to feed telemetry back to predictor
  6. Update status to `completed`
- Track per-worker: tasks_completed, total_busy_ms, total_idle_ms

#### `api/tasks.py`
FastAPI router:
- `POST /tasks` — body: `{task_type, payload_size, metadata?}` → generates UUID, enqueues, returns `{task_id, predicted_ms, position_in_queue}`
- `POST /tasks/batch` — body: `{tasks: [{task_type, payload_size}...]}` → bulk submit, returns list of predictions
- `GET /tasks/{task_id}` — returns full task status including predicted_ms, actual_ms (if done), wait_time, position
- `GET /queue` — current queue snapshot: ordered list of pending tasks with predicted durations

#### `api/metrics.py`
FastAPI router:
- `GET /metrics` — returns:
  ```json
  {
    "queue_depth": 23,
    "throughput_tasks_per_min": 12.4,
    "avg_wait_ms": 450,
    "prediction": {
      "model_type": "gradient_boosting",
      "model_version": "v4",
      "mae_ms": 42.3,
      "mape_percent": 8.1,
      "samples_used": 1200
    },
    "workers": [
      {"id": "w-0", "status": "busy", "utilization_percent": 78.3, "tasks_completed": 142},
      {"id": "w-1", "status": "idle", "utilization_percent": 65.1, "tasks_completed": 118}
    ]
  }
  ```
- `POST /retrain` — manually trigger predictor retrain, returns RetrainResult
- `GET /metrics/predictions` — returns last N predictions with actual vs predicted for plotting

#### `main.py`
- FastAPI app with lifespan handler
- On startup: init Redis, init TaskPredictor, init Scheduler, init TaskQueue, start WorkerPool as background tasks
- Mount both routers

#### `demo.py`
CLI script:
1. Submit 200 tasks of mixed types with varying payload sizes in rapid succession
2. Poll `/metrics` every 2 seconds, print a live table showing:
   - Queue depth draining
   - Model promotion from heuristic → gradient boosting (after 50 tasks)
   - MAE improving over time
   - Worker utilization
3. At the end, fetch `/metrics/predictions` and print a comparison table: predicted vs actual, sorted by error

#### `docker-compose.yml`
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

---

## Build Order (5 hours)

| Block | Time | Deliverable |
|-------|------|-------------|
| 1 | 0:00–0:30 | `chronoq-predictor`: scaffold, schemas.py, config.py, storage base + sqlite + memory |
| 2 | 0:30–1:30 | `chronoq-predictor`: heuristic model, gradient model, features.py |
| 3 | 1:30–2:15 | `chronoq-predictor`: predictor.py (predict/record/retrain with auto-promotion) + unit tests |
| 4 | 2:15–3:15 | `chronoq`: FastAPI scaffold, task_registry, queue.py (Redis sorted set), scheduler.py |
| 5 | 3:15–4:15 | `chronoq`: worker.py (async pool + telemetry loop), wire up in main.py lifespan |
| 6 | 4:15–4:45 | `chronoq`: metrics API, prediction tracking endpoint |
| 7 | 4:45–5:00 | demo.py, docker-compose.yml, README for both packages |

---

## Real-World Integration Example: Maveric rApp Training Worker

The `chronoq-predictor` module is designed to integrate with any job system. Below is a concrete integration example using a Kafka-based ML training worker (rApp worker from the Maveric RADP platform) that trains RL models for telecom network optimization.

### Why This Pipeline Is a Perfect Fit

Each training job has:
- **Predictable structure**: fetch artifacts → preprocess → train → upload
- **Observable features at submission time**: rapp_type, dataset_rows, topology_rows, total_timesteps, n_steps, batch_size, device
- **Highly variable execution time**: preprocessing scales with dataset_rows × topology_rows (BDT predictions), training scales with total_timesteps and step complexity
- **A real pain point**: Kafka heartbeat expires during long-running training (~14 min), causing rebalance loops. Knowing predicted duration upfront lets you set `max_poll_interval_ms` dynamically or use pause/resume patterns.

### Feature Extraction from Kafka Message + Early Logs

```python
# At job receive time (from Kafka message payload):
features = {
    "task_type": "mro_rl_training",       # from rapp_id
    "dataset_rows": 198000,                # from data_utils log or payload metadata
    "topology_rows": 15,                   # from data_utils log or payload metadata
    "total_timesteps": 1024,               # from training config in message
    "n_steps": 512,                        # from training config
    "batch_size": 128,                     # from training config
    "device": "cpu",                       # from environment / config
    "payload_size": 198000 * 4 + 15 * 21,  # approximate: rows × columns
}
```

### Integration Point in rApp Worker

```python
# In rapp_worker.py — after receiving training job, before dispatching

from chronoq_ranker import TaskPredictor

predictor = TaskPredictor(storage="sqlite:///maveric_telemetry.db")

# Before training starts
estimate = predictor.predict(
    task_type=f"{rapp_id}_{training_type}",  # e.g. "mro_rl"
    payload_size=dataset_rows * num_columns,
    metadata={
        "dataset_rows": dataset_rows,
        "topology_rows": topology_rows,
        "total_timesteps": total_timesteps,
        "n_steps": n_steps,
        "batch_size": batch_size,
        "device": device,
    }
)
logger.info(f"Predicted training duration: {estimate.estimated_ms}ms "
            f"(confidence: {estimate.confidence:.2f}, model: {estimate.model_type})")

# USE PREDICTION: dynamically adjust Kafka consumer config
# If predicted duration > max_poll_interval_ms, pause the partition
if estimate.estimated_ms > MAX_POLL_INTERVAL_MS:
    consumer.pause([assigned_partition])
    # resume after training completes

# ... run training ...

# After training completes
predictor.record(
    task_type=f"{rapp_id}_{training_type}",
    payload_size=dataset_rows * num_columns,
    actual_ms=actual_duration_ms,
    metadata={
        "dataset_rows": dataset_rows,
        "topology_rows": topology_rows,
        "total_timesteps": total_timesteps,
        "preprocessing_ms": preprocessing_duration_ms,
        "training_ms": training_duration_ms,
        "upload_ms": upload_duration_ms,
    }
)
```

### What This Solves in Maveric Specifically

1. **Kafka rebalance loop prevention**: your logs show the exact bug — training takes ~14 min, heartbeat expires at ~3.5 min, offset commit fails, same job re-consumed 3+ times. With predicted duration, you can `consumer.pause()` the partition before dispatching long jobs.
2. **Training job ETA**: the platform API can expose estimated completion time to the frontend.
3. **Resource planning**: if predicted duration × queue depth exceeds SLA, trigger alerts or scale workers.
4. **Phase-level prediction (future)**: with enough telemetry, predict preprocessing vs training time separately — useful since preprocessing scales with dataset size while PPO training scales with timesteps.

### README Talking Point

> Integrated `chronoq-predictor` with a Kafka-based ML training pipeline (Maveric RADP) to predict RL training job duration from dataset dimensions, hyperparameters, and hardware config. Used predictions to dynamically manage Kafka consumer partition pausing, eliminating a rebalance loop caused by long-running training jobs exceeding `max_poll_interval_ms`.

This turns a side project into something that solved a real production bug — which is exactly the kind of story that stands out in interviews.

---

## Future Scope

- **Priority classes**: allow `urgent` / `critical` tasks that bypass SJF ordering — adds real-world scheduling nuance (preemptive vs non-preemptive)
- **Worker autoscaling**: dynamically spawn/kill workers based on predicted queue drain time
- **Prediction drift alerting**: if rolling MAE exceeds threshold, auto-trigger retrain and emit a structured warning log / webhook
- **Task DAGs**: support dependent tasks (B waits for A) — enters DAG scheduling territory (topological sort + SJF within each level)
- **Persistent queue recovery**: Redis AOF or PostgreSQL fallback so in-flight tasks survive crashes; add dead-letter queue for repeated failures
- **PostgreSQL storage backend**: implement `TelemetryStore` for PostgreSQL for production-grade persistence
- **Pluggable model registry**: let users bring their own sklearn/PyTorch estimator that conforms to `BaseEstimator` interface
- **Multi-feature expansion**: incorporate CPU load, memory usage, time-of-day seasonality as additional features for prediction
- **WebSocket live feed**: stream queue state and worker activity to a frontend in real-time
- **Benchmark suite**: compare SJF (predicted) vs FIFO vs random scheduling and produce a report showing average wait time reduction
