# chronoq-server

Self-optimizing task queue with SJF scheduling, powered by `chronoq-predictor`.

## Quick Start

```bash
docker-compose up -d redis
uv run uvicorn chronoq_demo_server.main:app --reload
```

## API

### Submit a task
```bash
curl -X POST http://localhost:8000/tasks \
  -H "Content-Type: application/json" \
  -d '{"task_type": "resize_image", "payload_size": 2048}'
```

### Check task status
```bash
curl http://localhost:8000/tasks/{task_id}
```

### View queue (SJF order)
```bash
curl http://localhost:8000/tasks
```

### System metrics
```bash
curl http://localhost:8000/metrics
```

### Trigger retrain
```bash
curl -X POST http://localhost:8000/metrics/retrain
```

## Architecture

```
Client → POST /tasks → Predictor.predict() → Redis ZADD (score=predicted_ms)
                                                    ↓
                                        Workers ZPOPMIN (shortest first)
                                                    ↓
                                        Execute → Predictor.record()
                                                    ↓
                                        Auto-retrain after N records
```

Workers run as async coroutines, polling the Redis sorted set. The lowest-score task (shortest predicted duration) is always dequeued first.
