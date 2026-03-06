# Chronoq Diagrams

Comprehensive Mermaid diagrams covering architecture, data flows, and system behavior.

---

## 1. System Architecture

High-level view of all components and their relationships.

```mermaid
graph TB
    subgraph Client
        API_CLIENT[HTTP Client / demo.py]
    end

    subgraph "chronoq-server (FastAPI)"
        subgraph "API Layer"
            TASKS_API["/tasks endpoints"]
            METRICS_API["/metrics endpoints"]
        end

        subgraph "Core Layer"
            SCHEDULER[Scheduler]
            QUEUE[TaskQueue<br/>Redis Sorted Set]
            WORKER_POOL[WorkerPool<br/>N async workers]
            TASK_REG[TaskRegistry<br/>simulate_task]
        end

        TRACKER[PredictionTracker<br/>deque ring buffer]
    end

    subgraph "chronoq-predictor (standalone library)"
        PREDICTOR[TaskPredictor<br/>orchestrator]
        subgraph "Models"
            HEURISTIC[HeuristicEstimator<br/>per-type mean/std]
            GRADIENT[GradientEstimator<br/>sklearn GBR]
        end
        subgraph "Storage"
            STORE[(TelemetryStore<br/>SQLite / Memory)]
        end
        FEATURES[Feature Extraction]
    end

    REDIS[(Redis)]

    API_CLIENT -->|POST /tasks| TASKS_API
    API_CLIENT -->|GET /metrics| METRICS_API
    TASKS_API --> SCHEDULER
    METRICS_API --> SCHEDULER
    METRICS_API --> QUEUE
    METRICS_API --> WORKER_POOL
    METRICS_API --> TRACKER
    SCHEDULER -->|predict| PREDICTOR
    SCHEDULER -->|enqueue| QUEUE
    SCHEDULER -->|record| PREDICTOR
    QUEUE <-->|ZADD/ZPOPMIN| REDIS
    WORKER_POOL -->|dequeue| QUEUE
    WORKER_POOL -->|execute| TASK_REG
    WORKER_POOL -->|report_completion| SCHEDULER
    WORKER_POOL -->|record| TRACKER
    PREDICTOR --> FEATURES
    PREDICTOR --> HEURISTIC
    PREDICTOR --> GRADIENT
    PREDICTOR --> STORE
    GRADIENT -.->|fallback| HEURISTIC
```

---

## 2. SJF Scheduling Flow

Complete lifecycle of a task from submission through execution to feedback.

```mermaid
sequenceDiagram
    participant C as Client
    participant API as FastAPI /tasks
    participant S as Scheduler
    participant P as TaskPredictor
    participant Q as TaskQueue (Redis)
    participant W as Worker
    participant T as PredictionTracker

    C->>API: POST /tasks {task_type, payload_size}
    API->>S: score_and_enqueue(task_id, task_type, payload_size)
    S->>P: predict(task_type, payload_size)
    P-->>S: PredictionResult(estimated_ms, confidence)
    S->>Q: enqueue(task_id, predicted_ms as score)
    Note over Q: ZADD chronoq:tasks {task_id: predicted_ms}<br/>HSET chronoq:task:{id} {details}
    S-->>API: PredictionResult
    API-->>C: {task_id, predicted_ms, confidence, model_type}

    loop Worker poll loop
        W->>Q: dequeue()
        Note over Q: ZPOPMIN → lowest score first (SJF)
        Q-->>W: task_data (shortest predicted job)
    end

    W->>Q: update_status("running")
    W->>W: simulate_task(task_type, payload_size)
    Note over W: actual_ms = base + payload*factor + noise
    W->>Q: update_status("completed", actual_ms)
    W->>S: report_completion(task_type, payload_size, actual_ms)
    S->>P: record(task_type, payload_size, actual_ms)
    Note over P: Save to TelemetryStore<br/>Check auto-retrain trigger
    W->>T: record(predicted_ms, actual_ms)
    Note over T: Append to deque(maxlen=200)
```

---

## 3. Model Promotion Lifecycle

How the predictor auto-promotes from heuristic to gradient boosting.

```mermaid
stateDiagram-v2
    [*] --> ColdStart: TaskPredictor initialized

    ColdStart: Cold Start (Heuristic)
    ColdStart: per-type mean/std
    ColdStart: confidence = 1/(1 + std/mean)
    ColdStart: unseen types → global mean

    WarmML: Warm ML (GradientBoosting)
    WarmML: sklearn GBR (100 trees, depth 4)
    WarmML: features: type, payload, hour, depth
    WarmML: heuristic fallback for unseen types

    ColdStart --> ColdStart: retrain (records < cold_start_threshold)
    ColdStart --> WarmML: retrain (records >= cold_start_threshold)\n**promoted = True**
    WarmML --> WarmML: retrain (records keep growing)\npromoted = False

    note left of ColdStart
        Default cold_start_threshold = 50
        Default retrain_every_n = 100
    end note

    note right of WarmML
        80/20 train/test split
        Confidence = 1 - MAE/mean_pred
        Clamped to [0.1, 1.0]
    end note
```

---

## 4. Auto-Retrain Trigger Flow

Decision flow for when and how retraining happens.

```mermaid
flowchart TD
    A[predictor.record called] --> B[Save TaskRecord to TelemetryStore<br/>stamp with current model_version]
    B --> C{count_since current_version<br/>>= retrain_every_n?}
    C -->|No| D[Return]
    C -->|Yes| E[Trigger retrain]
    E --> F[Fetch all records from store]
    F --> G{total records >= cold_start_threshold?}
    G -->|No| H[Create new HeuristicEstimator]
    G -->|Yes| I[Create new GradientEstimator]
    H --> J[Fit estimator<br/>OUTSIDE lock]
    I --> J
    J --> K[Acquire lock]
    K --> L[Swap _estimator reference]
    L --> M[Release lock]
    M --> N[Return RetrainResult<br/>mae, mape, samples, promoted]

    style E fill:#f9f,stroke:#333
    style L fill:#ff9,stroke:#333
```

---

## 5. Data Flow Diagram — Level 0 (Context)

High-level external interactions with the system.

```mermaid
flowchart LR
    USER([External Client])
    SYSTEM[[Chronoq System]]
    REDIS_EXT[(Redis)]
    SQLITE_EXT[(SQLite)]

    USER -->|task submissions| SYSTEM
    SYSTEM -->|predictions, status,<br/>metrics| USER
    SYSTEM <-->|queue operations<br/>ZADD, ZPOPMIN, HSET| REDIS_EXT
    SYSTEM <-->|telemetry read/write| SQLITE_EXT
```

---

## 6. Data Flow Diagram — Level 1

Internal data flows between major processes.

```mermaid
flowchart TB
    USER([Client])

    subgraph "Chronoq System"
        P1[1.0<br/>Submit Task]
        P2[2.0<br/>Predict Duration]
        P3[3.0<br/>Queue Management]
        P4[4.0<br/>Execute Task]
        P5[5.0<br/>Record Telemetry]
        P6[6.0<br/>Retrain Model]
        P7[7.0<br/>Report Metrics]
    end

    REDIS[(Redis<br/>Sorted Set + Hashes)]
    SQLITE[(SQLite<br/>Telemetry Store)]
    MODEL[[ML Model<br/>Heuristic / GBR]]

    USER -->|task_type, payload_size| P1
    P1 -->|task params| P2
    P2 <-->|features / prediction| MODEL
    P2 -->|task_id, predicted_ms| P3
    P3 <-->|ZADD / ZPOPMIN| REDIS
    P3 -->|task_data (SJF order)| P4
    P4 -->|actual_ms| P5
    P5 -->|TaskRecord| SQLITE
    P5 -->|count check| P6
    P6 <-->|read records / update model| SQLITE
    P6 -->|new estimator| MODEL
    P1 -->|prediction result| USER
    USER -->|GET /metrics| P7
    P7 -->|queue_depth| REDIS
    P7 -->|model info| MODEL
    P7 -->|worker stats, predictions| USER
```

---

## 7. Worker Pool Execution

How the async worker pool processes tasks concurrently.

```mermaid
flowchart TD
    START[WorkerPool.start] --> SPAWN["Spawn N worker coroutines<br/>(default N=4)"]

    SPAWN --> W0[Worker 0]
    SPAWN --> W1[Worker 1]
    SPAWN --> W2[Worker 2]
    SPAWN --> W3[Worker 3]

    subgraph "Worker Loop (each worker)"
        POLL[ZPOPMIN from Redis] --> CHECK{Task returned?}
        CHECK -->|None| SLEEP["Sleep(poll_interval)<br/>Track idle_ms"]
        SLEEP --> POLL
        CHECK -->|task_data| BUSY[Set status = busy]
        BUSY --> EXEC["simulate_task(type, size)<br/>Measure actual_ms"]
        EXEC --> UPDATE[Update Redis hash:<br/>status=completed]
        UPDATE --> REPORT[scheduler.report_completion<br/>→ predictor.record]
        REPORT --> TRACK[prediction_tracker.record<br/>predicted vs actual]
        TRACK --> STATS[Increment tasks_completed<br/>Track busy_ms]
        STATS --> IDLE[Set status = idle]
        IDLE --> POLL
    end

    STOP[WorkerPool.stop] --> CANCEL[Cancel all worker tasks]
    CANCEL --> GATHER[asyncio.gather with return_exceptions]
```

---

## 8. Thread Safety Model

How the predictor handles concurrent predict/record/retrain operations.

```mermaid
sequenceDiagram
    participant W1 as Worker 1 (predict)
    participant W2 as Worker 2 (record)
    participant L as threading.Lock
    participant E as _estimator ref
    participant S as TelemetryStore

    par Concurrent operations
        W1->>L: acquire()
        L-->>W1: granted
        W1->>E: read _estimator ref
        W1->>L: release()
        Note over W1: predict() runs WITHOUT lock held

        W2->>S: store.save(record)
        Note over S: SQLite has its own lock
        W2->>S: store.count_since(version)
        Note over W2: Check if retrain needed
    end

    Note over W2: count >= retrain_every_n → retrain triggered

    W2->>W2: Create new estimator
    W2->>W2: new_estimator.fit(records)
    Note over W2: Fitting happens WITHOUT lock<br/>Can take 100s of ms

    W2->>L: acquire()
    L-->>W2: granted
    W2->>E: swap _estimator = new_estimator
    W2->>L: release()
    Note over L: Lock held only for pointer swap<br/>(nanoseconds)
```

---

## 9. Feature Extraction Pipeline

How raw task parameters become ML features.

```mermaid
flowchart LR
    subgraph "Input"
        TT[task_type<br/>e.g. resize_image]
        PS[payload_size<br/>e.g. 2048]
        META[metadata<br/>e.g. queue_depth: 5]
    end

    subgraph "extract_features()"
        F1[task_type → string]
        F2[payload_size → int]
        F3[hour_of_day → UTC hour]
        F4[queue_depth → from metadata]
    end

    subgraph "Heuristic Model"
        H1["Lookup _stats[task_type]"]
        H2[Return mean, confidence]
    end

    subgraph "Gradient Model"
        G1[LabelEncoder.transform<br/>task_type → int]
        G2["Feature vector:<br/>[encoded_type, payload, hour, depth]"]
        G3[GBR.predict → estimated_ms]
        G4["Confidence:<br/>max(0.1, min(1.0, 1 - MAE/mean))"]
    end

    TT --> F1
    PS --> F2
    META --> F4

    F1 --> H1
    F1 --> G1
    F2 --> G2
    F3 --> G2
    F4 --> G2
    G1 --> G2
    G2 --> G3
    G3 --> G4

    H1 --> H2
```

---

## 10. Redis Data Model

How task data is structured in Redis.

```mermaid
graph LR
    subgraph "Sorted Set: chronoq:tasks"
        direction TB
        Z1["member: task-uuid-1<br/>score: 152.3 (predicted_ms)"]
        Z2["member: task-uuid-2<br/>score: 305.7"]
        Z3["member: task-uuid-3<br/>score: 1847.2"]
    end

    subgraph "Hash: chronoq:task:uuid-1"
        H1["task_id: uuid-1"]
        H2["task_type: send_email"]
        H3["payload_size: 500"]
        H4["predicted_ms: 152.3"]
        H5["status: completed"]
        H6["actual_ms: 148.7"]
        H7["submitted_at: ISO timestamp"]
    end

    Z1 ---|HGETALL| H1

    ENQUEUE[enqueue] -->|"Pipeline:<br/>HSET + ZADD"| Z1
    DEQUEUE[dequeue] -->|ZPOPMIN| Z1
    DEQUEUE -->|HGETALL| H1
    PEEK[peek] -->|"ZRANGE WITHSCORES"| Z1
```

---

## 11. API Request Map

All available HTTP endpoints and their internal routing.

```mermaid
flowchart LR
    subgraph "Task Endpoints"
        POST_T["POST /tasks"]
        POST_B["POST /tasks/batch"]
        GET_T["GET /tasks/{id}"]
        GET_Q["GET /tasks"]
    end

    subgraph "Metrics Endpoints"
        GET_M["GET /metrics"]
        POST_R["POST /metrics/retrain"]
        GET_P["GET /metrics/predictions"]
    end

    subgraph "app.state"
        SCH[scheduler]
        Q[queue]
        WP[worker_pool]
        PT[prediction_tracker]
    end

    POST_T -->|score_and_enqueue| SCH
    POST_B -->|score_and_enqueue x N| SCH
    GET_T -->|get_task| Q
    GET_Q -->|peek| Q

    GET_M -->|length| Q
    GET_M -->|get_predictor_info| SCH
    GET_M -->|get_stats| WP
    POST_R -->|trigger_retrain| SCH
    GET_P -->|recent| PT
```

---

## 12. Application Lifespan

Startup and shutdown sequence managed by FastAPI's lifespan context manager.

```mermaid
sequenceDiagram
    participant U as Uvicorn
    participant L as lifespan()
    participant R as Redis
    participant P as TaskPredictor
    participant Q as TaskQueue
    participant S as Scheduler
    participant W as WorkerPool

    Note over U,W: STARTUP
    U->>L: Enter lifespan context
    L->>R: aioredis.from_url(REDIS_URL)
    L->>P: TaskPredictor(config)
    Note over P: Warm-start from existing SQLite data
    L->>Q: TaskQueue(redis, key, prefix)
    L->>S: Scheduler(predictor, queue)
    L->>W: WorkerPool(queue, scheduler, count=4)
    L->>W: start()
    Note over W: Spawn 4 async worker coroutines
    L-->>U: yield (app is running)

    Note over U,W: SHUTDOWN
    U->>L: Exit lifespan context
    L->>W: stop()
    Note over W: Cancel workers, await gather
    L->>R: aclose()
    Note over L: Server shut down
```
