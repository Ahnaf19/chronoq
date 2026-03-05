# API Reference

Base URL: `http://localhost:8000`

---

## Tasks

### POST /tasks

Submit a single task for SJF-scheduled execution.

**Request Body:**
```json
{
  "task_type": "resize_image",
  "payload_size": 2048,
  "metadata": {"source": "upload-service"}
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `task_type` | string | yes | Task category (must match a registered type) |
| `payload_size` | integer | yes | Size indicator for the task payload |
| `metadata` | object | no | Arbitrary key-value pairs passed to the predictor |

**Response (200):**
```json
{
  "task_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "predicted_ms": 402.4,
  "confidence": 0.82,
  "model_type": "gradient_boosting"
}
```

---

### POST /tasks/batch

Submit multiple tasks in one request.

**Request Body:**
```json
{
  "tasks": [
    {"task_type": "resize_image", "payload_size": 2048},
    {"task_type": "send_email", "payload_size": 512},
    {"task_type": "generate_report", "payload_size": 10000}
  ]
}
```

**Response (200):**
```json
[
  {"task_id": "...", "predicted_ms": 402.4, "confidence": 0.82, "model_type": "gradient_boosting"},
  {"task_id": "...", "predicted_ms": 155.1, "confidence": 0.85, "model_type": "gradient_boosting"},
  {"task_id": "...", "predicted_ms": 3000.0, "confidence": 0.78, "model_type": "gradient_boosting"}
]
```

---

### GET /tasks/{task_id}

Get task status and details.

**Response (200):**
```json
{
  "task_id": "a1b2c3d4-...",
  "task_type": "resize_image",
  "payload_size": "2048",
  "predicted_ms": "402.4",
  "metadata": "{\"source\": \"upload-service\"}",
  "status": "completed",
  "submitted_at": "2026-03-06T10:30:00+00:00",
  "actual_ms": "312.0",
  "worker_id": "2"
}
```

**Status values:** `pending` | `running` | `completed`

**Response (404):**
```json
{"detail": "Task not found"}
```

---

### GET /tasks

Queue snapshot: pending tasks in SJF order (shortest predicted first).

**Response (200):**
```json
[
  {
    "task_id": "...",
    "task_type": "send_email",
    "payload_size": "100",
    "predicted_ms": "155.1",
    "status": "pending",
    "queue_score": 155.1
  },
  {
    "task_id": "...",
    "task_type": "resize_image",
    "payload_size": "2048",
    "predicted_ms": "402.4",
    "status": "pending",
    "queue_score": 402.4
  }
]
```

Returns up to 50 tasks.

---

## Metrics

### GET /metrics

System-wide metrics.

**Response (200):**
```json
{
  "queue_depth": 23,
  "prediction": {
    "model_version": "gradient-v3",
    "model_type": "gradient_boosting",
    "total_records": 1200
  },
  "workers": [
    {"id": "w-0", "status": "busy", "utilization_percent": 78.3, "tasks_completed": 142},
    {"id": "w-1", "status": "idle", "utilization_percent": 65.1, "tasks_completed": 118},
    {"id": "w-2", "status": "busy", "utilization_percent": 72.0, "tasks_completed": 130},
    {"id": "w-3", "status": "idle", "utilization_percent": 60.5, "tasks_completed": 105}
  ]
}
```

---

### POST /metrics/retrain

Manually trigger predictor model retrain.

**Response (200):**
```json
{
  "mae": 42.3,
  "mape": 8.1,
  "samples_used": 1200,
  "model_version": "gradient-v4",
  "promoted": false
}
```

| Field | Type | Description |
|-------|------|-------------|
| `mae` | float | Mean Absolute Error in ms |
| `mape` | float | Mean Absolute Percentage Error |
| `samples_used` | integer | Total records used for training |
| `model_version` | string | New model version after retrain |
| `promoted` | boolean | True if model type changed (heuristic -> gradient) |

---

### GET /metrics/predictions

Recent prediction-vs-actual accuracy history (last 50 entries).

**Response (200):**
```json
[
  {
    "task_type": "resize_image",
    "predicted_ms": 340.0,
    "actual_ms": 312.0,
    "error_ms": 28.0
  },
  {
    "task_type": "send_email",
    "predicted_ms": 155.0,
    "actual_ms": 148.0,
    "error_ms": 7.0
  }
]
```

---

## Registered Task Types

The demo server includes 5 simulated task types with characteristic time profiles:

| Task Type | Base (ms) | Variance (ms) | Payload Factor |
|-----------|-----------|----------------|----------------|
| `resize_image` | 300 | 80 | 0.05 ms/byte |
| `send_email` | 150 | 30 | 0.01 ms/byte |
| `generate_report` | 2000 | 500 | 0.10 ms/byte |
| `compress_file` | 800 | 200 | 0.08 ms/byte |
| `run_inference` | 1500 | 400 | 0.12 ms/byte |

Actual execution time: `base_ms + (payload_size * payload_factor) + gaussian_noise(0, variance)`
