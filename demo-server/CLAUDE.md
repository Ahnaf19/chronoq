# chronoq-demo-server (reference integration, demoted from v1)

**Status:** demoted. In v1 this was "the product." In v2 it's a **reference integration** showing one way to embed `chronoq-ranker` inside a FastAPI + Redis sorted-set queue. The real v2 product is the library + Celery plugin. Do not invest new features here unless they're demonstrating ranker usage.

## Layout

```
chronoq_demo_server/
├── main.py             # FastAPI lifespan + router mounting
├── config.py           # ServerConfig — env var overrides
├── task_registry.py    # simulate_task() — random sleep stub (real trace replay is in chronoq-bench)
├── core/
│   ├── queue.py        # TaskQueue — Redis sorted set (ZADD/ZPOPMIN)
│   ├── scheduler.py    # Scheduler — bridges ranker ↔ queue
│   └── worker.py       # WorkerPool — N async worker coroutines
└── api/
    ├── tasks.py        # POST/GET /tasks
    └── metrics.py      # GET/POST /metrics + PredictionTracker ring buffer
```

## Data flow (for reference)

```
POST /tasks → scheduler.score_and_enqueue() → ranker.predict() → Redis ZADD(score=predicted_ms)
Worker loop: ZPOPMIN → simulate_task() → scheduler.report_completion() → ranker.record()
```

## Config (env vars)

| Var | Default | Purpose |
|---|---|---|
| `REDIS_URL` | `redis://localhost:6379/0` | Redis |
| `CHRONOQ_WORKER_COUNT` | `4` | Async workers |
| `CHRONOQ_QUEUE_KEY` | `chronoq:tasks` | Redis sorted set key |
| `CHRONOQ_TASK_PREFIX` | `chronoq:task:` | Redis hash prefix |
| `CHRONOQ_PREDICTOR_STORAGE` | `sqlite:///chronoq_telemetry.db` | Ranker storage URI |
| `CHRONOQ_COLD_START` | `50` | Records before ML promotion |
| `CHRONOQ_RETRAIN_EVERY` | `100` | Auto-retrain interval |

## Patterns

- **Lifespan context**: init Redis, ranker, queue, workers on startup; reverse on shutdown. All shared objs on `app.state`.
- **Sync ranker from async workers**: `ranker.record()` is sync+fast (SQLite). `ranker.retrain()` uses `asyncio.to_thread()` via `scheduler.trigger_retrain()`.
- **Redis pipeline**: `queue.enqueue()` batches HSET + ZADD.
- **fakeredis in tests**: `FakeRedis(decode_responses=True)` — no real Redis needed.

## Testing

```bash
uv run pytest tests/server/ -v
```

Integration tests mock `simulate_task` to `asyncio.sleep(0.01)` for speed.

## When modifying

- Treat as frozen unless the change demonstrates ranker integration.
- Real ranker integration work belongs in `integrations/celery/`.
- Bench / simulator work belongs in `bench/`.
