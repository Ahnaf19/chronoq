# chronoq-server

FastAPI task queue with Redis sorted set SJF scheduling. Depends on `chronoq-predictor` (workspace source).

## Package Structure

```
chronoq_demo_server/
├── __init__.py
├── main.py              # FastAPI app — lifespan (startup/shutdown), router mounting
├── config.py            # ServerConfig dataclass — env var overrides
├── task_registry.py     # TASK_REGISTRY dict + simulate_task() async function
├── core/
│   ├── queue.py         # TaskQueue — Redis sorted set (ZADD/ZPOPMIN/ZCARD)
│   ├── scheduler.py     # Scheduler — bridges predictor ↔ queue
│   └── worker.py        # WorkerPool — N async worker coroutines
└── api/
    ├── tasks.py         # POST/GET /tasks endpoints
    └── metrics.py       # GET/POST /metrics endpoints, PredictionTracker
```

## Data Flow

```
POST /tasks → api/tasks.py → scheduler.score_and_enqueue()
    → predictor.predict() → queue.enqueue(score=predicted_ms) → Redis ZADD

WorkerPool._worker_loop():
    → queue.dequeue() → Redis ZPOPMIN (lowest score)
    → simulate_task() → measure actual_ms
    → queue.update_status("completed")
    → scheduler.report_completion() → predictor.record()
    → prediction_tracker.record() (ring buffer for /metrics/predictions)
```

## App State (set in lifespan)

All shared objects are stored on `app.state` in `main.py`:
- `app.state.queue` — TaskQueue instance
- `app.state.scheduler` — Scheduler instance
- `app.state.worker_pool` — WorkerPool instance
- `app.state.prediction_tracker` — PredictionTracker instance (deque ring buffer, maxlen=200)

API route handlers access these via `request.app.state`.

## Configuration

All via env vars (see `config.py`):

| Variable | Default | Description |
|----------|---------|-------------|
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection |
| `CHRONOQ_WORKER_COUNT` | `4` | Async worker count |
| `CHRONOQ_QUEUE_KEY` | `chronoq:tasks` | Redis sorted set key |
| `CHRONOQ_TASK_PREFIX` | `chronoq:task:` | Redis hash key prefix |
| `CHRONOQ_PREDICTOR_STORAGE` | `sqlite:///chronoq_telemetry.db` | Predictor storage URI |
| `CHRONOQ_COLD_START` | `50` | Records before ML promotion |
| `CHRONOQ_RETRAIN_EVERY` | `100` | Auto-retrain interval |

## Key Patterns

- **Lifespan context manager**: `main.py` uses `@asynccontextmanager` for startup (init Redis, predictor, queue, workers) and shutdown (stop workers, close Redis).
- **Async workers with sync predictor**: Workers are async coroutines. `predictor.record()` is sync but fast (SQLite write). `predictor.retrain()` uses `asyncio.to_thread()` via `scheduler.trigger_retrain()`.
- **PredictionTracker**: `dataclass` with `deque(maxlen=200)` ring buffer. Workers write predicted_ms vs actual_ms. The `/metrics/predictions` endpoint reads from it.
- **Redis pipeline**: `queue.enqueue()` uses `pipeline()` to batch HSET + ZADD in a single round-trip.
- **fakeredis in tests**: All server tests use `fakeredis.aioredis.FakeRedis()` — no real Redis needed.

## Testing

```bash
uv run pytest tests/server/ -v              # All 24 server tests
uv run pytest tests/server/test_queue.py    # Queue SJF ordering tests
uv run pytest tests/server/test_integration.py  # Submit-and-drain tests
```

- API tests use `httpx.AsyncClient` with `app=create_test_app()` pattern
- Integration tests mock `simulate_task` to return instantly (no actual sleep)
- Worker tests use `poll_interval=0.01` for speed

## When Modifying

- Adding an API endpoint → add to `api/tasks.py` or `api/metrics.py`, add test, update docs/api-reference.md and Postman collection
- Changing queue behavior → update `core/queue.py`, test in `test_queue.py`
- Changing worker behavior → update `core/worker.py`, test in `test_worker.py`
- Adding env vars → update `config.py`, `docs/configuration.md`, `.env.example`
- Changing app startup → update `main.py` lifespan function
