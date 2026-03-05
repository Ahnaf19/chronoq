# Chronoq

**A task queue that learns how long your jobs take — and reorders them to minimize wait time.**

Every task queue processes jobs in FIFO order. But FIFO is a poor strategy when a 10-second job is stuck behind a 10-minute job — everything downstream waits. Operating systems solved this decades ago with **Shortest Job First (SJF)** scheduling, which is provably optimal for minimizing average wait time. The catch? SJF requires knowing how long a job will take *before* it runs.

Chronoq bridges that gap by learning execution time from historical telemetry and using those predictions to continuously reorder the queue.

## The Self-Improving Loop

```
                    submit task
                        |
                        v
              +-------------------+
              |    Predictor      |   "This will take ~340ms"
              | (predict duration)|
              +-------------------+
                        |
                        v
              +-------------------+
              |   Redis Sorted    |   score = predicted_ms
              |   Set (SJF Queue) |   lowest score dequeued first
              +-------------------+
                        |
                        v
              +-------------------+
              |   Async Workers   |   execute task, measure actual time
              +-------------------+
                        |
                        v
              +-------------------+
              |  Record Telemetry |   "Actually took 312ms"
              +-------------------+
                        |
                        +-------> feeds back into predictor
                                  predictions get sharper over time
```

The predictor starts with a simple heuristic (per-type mean). After collecting 50 records, it **auto-promotes** to a GradientBoosting regressor — no manual intervention. It retrains every 100 new records, continuously improving accuracy.

## Two Independent Layers

Chronoq is a monorepo with a deliberate separation of concerns:

### Layer 1: `chronoq-predictor` — The ML Library

A standalone, pip-installable library with three methods. Zero dependency on Redis, FastAPI, or any queue system. Drop it into Celery, Kafka consumers, FastAPI background tasks, or any custom worker.

```python
from chronoq_predictor import TaskPredictor

predictor = TaskPredictor(storage="sqlite:///telemetry.db")

# Before running a task: predict how long it will take
estimate = predictor.predict("resize_image", payload_size=2048)
# => PredictionResult(estimated_ms=340, confidence=0.82, model_type="gradient_boosting")

# After running it: record what actually happened
predictor.record("resize_image", payload_size=2048, actual_ms=312)

# The model retrains automatically, or you can trigger it manually
result = predictor.retrain()
# => RetrainResult(mae=45.2, samples_used=1200, promoted=False)
```

**What it learns from:** task type, payload size, hour of day, queue depth. The heuristic model tracks per-type mean and standard deviation. The GradientBoosting model learns non-linear relationships between these features and actual execution time.

**Thread-safe by design.** The predictor uses a lock only to swap the model reference — fitting happens outside the lock, so concurrent predict/record calls from multiple threads never block each other.

### Layer 2: `chronoq-server` — The Queue System

A complete SJF task queue built on Redis sorted sets, with async workers and a FastAPI observability API. Imports `chronoq-predictor` and serves as both a usable system and a reference implementation.

```bash
# Start Redis and the server
docker compose up -d redis
uv run uvicorn chronoq_server.main:app --reload

# Submit a task
curl -X POST http://localhost:8000/tasks \
  -H "Content-Type: application/json" \
  -d '{"task_type": "resize_image", "payload_size": 2048}'

# Watch the system metrics
curl http://localhost:8000/metrics
```

**Redis sorted sets as a priority queue.** Tasks are inserted with `ZADD` where the score is the predicted duration in milliseconds. Workers pop with `ZPOPMIN` — always getting the shortest predicted job first.

**Async worker pool.** Four concurrent workers (configurable) drain the queue, execute tasks, and feed actual timing data back to the predictor. Per-worker stats track utilization, task count, and busy/idle time.

**Observable.** The `/metrics` endpoint exposes queue depth, model type/version, worker utilization, and telemetry count. The `/metrics/predictions` endpoint returns recent predicted-vs-actual pairs so you can see the model improving in real time.

## Demo: Model Promotion in Action

The demo submits 200 tasks in waves, giving the predictor time to learn between batches:

```bash
uv run python demo.py
```

```
=======================================================
  Wave 1 (cold start): submitting 60 tasks...
=======================================================

--- 14s elapsed ---
  Queue depth:     38
  Model type:      heuristic          <-- simple per-type mean
  Model version:   heuristic-v0
  Total records:   22

=======================================================
  Wave 2 (heuristic learning): submitting 60 tasks...
=======================================================

--- 30s elapsed ---
  Queue depth:     12
  Model type:      gradient_boosting  <-- auto-promoted after 50 records
  Model version:   gradient-v1
  Total records:   108

=======================================================
  Wave 4 (gradient boosting): submitting 40 tasks...
=======================================================

--- 56s elapsed ---
  Queue depth:     0
  Model type:      gradient_boosting
  Model version:   gradient-v1
  Total records:   200

=================================================================
  Prediction Accuracy Summary (200 total samples)
=================================================================
  Early predictions MAE (heuristic):               682 ms
  Late predictions MAE  (gradient boosting):        241 ms
  Improvement:                                     64.7%
```

The early heuristic predictions are off by ~680ms on average (it only knows the global mean). After promotion to GradientBoosting, error drops to ~240ms — a **65% improvement** in prediction accuracy, which directly translates to better SJF ordering.

## API Reference

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/tasks` | Submit a task — returns prediction and task ID |
| `POST` | `/tasks/batch` | Submit multiple tasks at once |
| `GET` | `/tasks/{id}` | Get task status (pending / running / completed) |
| `GET` | `/tasks` | Queue snapshot in SJF order |
| `GET` | `/metrics` | Queue depth, model info, worker stats |
| `POST` | `/metrics/retrain` | Manually trigger model retrain |
| `GET` | `/metrics/predictions` | Recent predicted-vs-actual accuracy history |

Full request/response examples: [`docs/api-reference.md`](docs/api-reference.md)

## Project Structure

```
chronoq/
├── chronoq_predictor/              # Layer 1: standalone ML library
│   └── chronoq_predictor/
│       ├── predictor.py            # TaskPredictor — predict / record / retrain
│       ├── models/
│       │   ├── heuristic.py        # Cold-start: per-type mean + std
│       │   └── gradient.py         # Warm: GradientBoostingRegressor
│       ├── storage/
│       │   ├── sqlite.py           # Persistent telemetry storage
│       │   └── memory.py           # In-memory (testing)
│       ├── schemas.py              # Pydantic models
│       ├── features.py             # Feature extraction
│       └── config.py               # Tunable thresholds
├── chronoq_server/                 # Layer 2: queue system
│   └── chronoq_server/
│       ├── main.py                 # FastAPI app with lifespan
│       ├── core/
│       │   ├── queue.py            # Redis sorted set SJF queue
│       │   ├── scheduler.py        # Bridges predictor to queue
│       │   └── worker.py           # Async worker pool
│       ├── api/
│       │   ├── tasks.py            # Task submission endpoints
│       │   └── metrics.py          # Observability endpoints
│       └── task_registry.py        # Simulated task definitions
├── tests/                          # 71 tests (47 predictor + 24 server)
├── migrations/                     # Alembic schema migrations
├── docs/                           # Architecture, user guide, API reference
│   └── postman/                    # Postman collection + environment
├── demo.py                         # End-to-end demo with wave-based submission
├── docker-compose.yml              # Redis + app
└── Dockerfile
```

## Getting Started

### Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (package manager)
- Redis (via Docker or local install)

### Setup

```bash
git clone <repo-url> && cd chronoq
uv sync

# Run the test suite
uv run pytest -v

# Start Redis
docker compose up -d redis

# Start the server
uv run uvicorn chronoq_server.main:app --reload

# Run the demo (separate terminal)
uv run python demo.py
```

### Using the predictor standalone (no Redis needed)

```bash
uv pip install ./chronoq_predictor
```

```python
from chronoq_predictor import TaskPredictor

predictor = TaskPredictor(storage="sqlite:///my_telemetry.db")

# Works with any task system — just predict before and record after
estimate = predictor.predict("my_task", payload_size=1024)
# ... run your task ...
predictor.record("my_task", payload_size=1024, actual_ms=actual)
```

## Design Decisions

**Why SJF?** It's provably optimal for minimizing average wait time in non-preemptive scheduling. The trade-off is that long tasks wait longer (starvation risk) — acceptable for most async workloads where total throughput matters more than strict fairness.

**Why auto-promotion?** Cold-start is real. A fresh system has no data, so starting with a heuristic (per-type mean) gives reasonable predictions immediately. Once enough data accumulates, the system promotes itself to a GradientBoosting model that captures non-linear relationships between features and execution time.

**Why two packages?** The predictor is useful independently. If you already have a task queue (Celery, Kafka, etc.), you don't need another one — you just need duration predictions. Keeping it separate means zero unnecessary dependencies and clean integration with any system.

**Why Redis sorted sets?** They give O(log N) insert and O(log N) pop-min — exactly what SJF needs. The score is the predicted duration, and `ZPOPMIN` always returns the shortest predicted job.

## Documentation

| Document | Description |
|----------|-------------|
| [`docs/architecture.md`](docs/architecture.md) | System design, data flow, thread safety model |
| [`docs/user-guide.md`](docs/user-guide.md) | Setup, standalone usage, integration patterns |
| [`docs/api-reference.md`](docs/api-reference.md) | Full REST API with request/response examples |
| [`docs/configuration.md`](docs/configuration.md) | Environment variables, predictor config, Redis layout |
| [`docs/postman/`](docs/postman/) | Postman collection + environment for API testing |

## Tech Stack

Python 3.11 | FastAPI | Redis | scikit-learn | Pydantic v2 | SQLite | pytest | uv workspace monorepo
