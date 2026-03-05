# Chronoq

A self-optimizing task queue with ML-based Shortest Job First (SJF) scheduling.

## Overview

Every task queue processes jobs in FIFO order by default, but FIFO is suboptimal for average wait time. Chronoq applies SJF scheduling — provably optimal for minimizing average wait time — by **learning task execution time from historical telemetry**.

### Two-Layer Design

1. **`chronoq-predictor`** — Standalone, pip-installable library. Three methods: `predict()`, `record()`, `retrain()`. Drop it into any project (Celery, Kafka, custom workers) to predict task duration. Zero coupling to any queue or broker.

2. **`chronoq-server`** — Complete task queue using Redis sorted sets for SJF scheduling, async workers, and a FastAPI metrics API. Imports `chronoq-predictor` and serves as a reference implementation.

## Quick Start

```bash
# Install dependencies
uv sync

# Run tests
uv run pytest -v

# Start Redis + server
docker-compose up -d redis
uv run uvicorn chronoq_server.main:app --reload

# Run demo (in another terminal)
uv run python demo.py
```

## How It Works

1. Client submits a task via `POST /tasks` with `task_type`, `payload_size`, optional `metadata`
2. Predictor estimates duration → task enters Redis sorted set with `score = estimated_ms`
3. Workers pop the lowest-score task (shortest job first), execute it, record actual duration
4. After 50 records, predictor auto-promotes from heuristic (per-type mean) to GradientBoosting
5. Model retrains every 100 new records — predictions sharpen over time

## Predictor Standalone Usage

```python
from chronoq_predictor import TaskPredictor

predictor = TaskPredictor(storage="sqlite:///telemetry.db")

# Predict before running
estimate = predictor.predict("resize_image", payload_size=2048)
# => PredictionResult(estimated_ms=340, confidence=0.82, model_type="gradient_boosting")

# Record after completion
predictor.record("resize_image", payload_size=2048, actual_ms=312)

# Manual retrain
metrics = predictor.retrain()
# => RetrainResult(mae=45.2, samples_used=1200, promoted=False)
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/tasks` | Submit a task |
| POST | `/tasks/batch` | Submit multiple tasks |
| GET | `/tasks/{id}` | Get task status |
| GET | `/tasks` | Queue snapshot (SJF order) |
| GET | `/metrics` | System metrics |
| POST | `/metrics/retrain` | Trigger retrain |
| GET | `/metrics/predictions` | Prediction accuracy history |

## Project Structure

```
chronoq/
├── chronoq_predictor/          # ML predictor library
│   └── chronoq_predictor/
│       ├── predictor.py        # Main orchestrator
│       ├── models/             # Heuristic + GradientBoosting
│       ├── storage/            # Memory + SQLite backends
│       ├── schemas.py          # Pydantic models
│       └── features.py         # Feature extraction
├── chronoq_server/             # Task queue server
│   └── chronoq_server/
│       ├── main.py             # FastAPI app
│       ├── core/               # Queue, scheduler, workers
│       ├── api/                # REST endpoints
│       └── task_registry.py    # Simulated task definitions
├── tests/                      # Full test suite
├── demo.py                     # End-to-end demo
└── docker-compose.yml          # Redis + app
```

## Development

```bash
uv sync                         # Install dependencies
uv run pytest -v                # Run all tests
uv run ruff check .             # Lint
uv run ruff format .            # Format
```
