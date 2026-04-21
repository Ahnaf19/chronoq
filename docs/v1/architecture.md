# Architecture

## Separation of Concerns

Chronoq is split into two independent layers that communicate through a minimal interface.

### Layer 1: chronoq-predictor (Library)

A standalone, pip-installable Python library with **zero coupling** to any queue, broker, or web framework. It depends only on:

- `pydantic` (schemas)
- `scikit-learn` (ML models)
- `loguru` (logging)

**Responsibilities:**
- Predict task execution time from task type, payload size, and metadata
- Store telemetry records (actual execution times)
- Auto-retrain models when enough data accumulates
- Auto-promote from heuristic to GradientBoosting after cold-start threshold

**Key design decisions:**
- **Strategy pattern for models**: `BaseEstimator` ABC with `HeuristicEstimator` and `GradientEstimator` implementations. New model types can be added by subclassing.
- **Pluggable storage**: `TelemetryStore` ABC with `MemoryStore` (testing) and `SqliteStore` (production). Add PostgreSQL, DynamoDB, etc. by implementing the interface.
- **Thread safety**: A `threading.Lock` protects only the estimator reference read/write. Model fitting happens outside the lock to avoid blocking predictions during retrain.
- **Warm-start**: On init, if storage already has data, the predictor fits a model immediately rather than starting cold.

### Layer 2: chronoq-server (Application)

A FastAPI application that imports `chronoq-predictor` and builds a complete SJF task queue on top. It adds:

- `redis` (sorted set queue)
- `fastapi` + `uvicorn` (HTTP API)

**Responsibilities:**
- Accept task submissions via REST API
- Score tasks using the predictor and enqueue to Redis sorted set
- Run async worker pool that pops shortest-predicted tasks first
- Feed execution telemetry back to the predictor (closed feedback loop)
- Expose metrics, prediction accuracy, and retrain controls

**Key design decisions:**
- **Redis sorted set for SJF**: `ZADD` with `score = predicted_ms` and `ZPOPMIN` to always dequeue the shortest job. This is O(log N) per operation and naturally maintains priority order.
- **Scheduler as bridge**: The `Scheduler` class is the single point of contact between the predictor and the queue. It prevents the queue and worker from depending directly on predictor internals.
- **Async workers with sync predictor**: Workers are async coroutines, but `predictor.record()` is sync. This works because record is fast (SQLite write + counter check). Retraining uses `asyncio.to_thread()` to avoid blocking the event loop.
- **PredictionTracker**: A ring buffer (deque) that records predicted-vs-actual pairs so the `/metrics/predictions` endpoint can serve accuracy history without hitting storage.

## Data Flow

```
1. Client  --POST /tasks-->  FastAPI Router
2. Router  --score_and_enqueue-->  Scheduler
3. Scheduler  --predict()-->  TaskPredictor  -->  Estimator (heuristic or gradient)
4. Scheduler  --enqueue(score=predicted_ms)-->  TaskQueue  -->  Redis ZADD
5. Worker  --dequeue()-->  TaskQueue  -->  Redis ZPOPMIN (lowest score first)
6. Worker  --simulate_task()-->  Execute task
7. Worker  --report_completion()-->  Scheduler  --record()-->  TaskPredictor  -->  Storage
8. TaskPredictor  --auto-retrain if threshold met-->  Fit new estimator  -->  Swap reference
```

## Component Diagram

```
+-------------------+     +-------------------+
|   FastAPI API     |     |   WorkerPool      |
|  /tasks /metrics  |     |  N async workers  |
+--------+----------+     +--------+----------+
         |                         |
         v                         v
+-------------------+     +-------------------+
|    Scheduler      |<--->|    TaskQueue       |
| predict + record  |     | Redis sorted set   |
+--------+----------+     +-------------------+
         |
         v
+-------------------+
|  TaskPredictor    |
|  auto-promote     |
|  auto-retrain     |
+--------+----------+
         |
    +----+----+
    |         |
    v         v
+--------+ +----------+
|Heuristic| |Gradient  |
|Estimator| |Estimator |
+--------+ +----------+
         |
         v
+-------------------+
| TelemetryStore    |
| SQLite / Memory   |
+-------------------+
```

## Model Promotion Lifecycle

```
Records: 0                    50                      150+
         |--- Heuristic ----->|--- GradientBoosting ------->
         |                    |                       |
         | predict: per-type  | predict: sklearn GBR  |
         | mean + std         | with label-encoded    |
         | confidence: low    | task_type features    |
         |                    | confidence: high      |
         |                    |                       |
         |     cold_start_threshold      retrain triggers every N records
```

## Thread Safety Model

```
Thread 1 (predict):    lock -> read _estimator ref -> unlock -> predict (no lock)
Thread 2 (predict):    lock -> read _estimator ref -> unlock -> predict (no lock)
Thread 3 (record):     save to storage (storage has own lock) -> check count
Thread 4 (retrain):    fit new estimator (no lock) -> lock -> swap ref -> unlock
```

The lock protects only the pointer swap, not the computation. This means:
- Multiple threads can predict concurrently (they each hold a reference)
- Retraining does not block predictions
- The only contention point is the brief swap under lock
