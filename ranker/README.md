# chronoq-ranker

Standalone learning-to-rank scheduling library for Python job queues. Ships today with a per-type heuristic that auto-promotes to sklearn GradientBoosting; LightGBM LambdaRank with pairwise training lands in Chunk 1 W3.

## Install

```bash
pip install chronoq-ranker   # (published in Chunk 4)
```

## Quick Start — single-job prediction (v1 compatible)

```python
from chronoq_ranker import TaskRanker

ranker = TaskRanker(storage="sqlite:///telemetry.db")

# Predict execution time
estimate = ranker.predict("resize_image", payload_size=2048)
print(f"{estimate.estimated_ms:.0f}ms (confidence: {estimate.confidence:.2f})")

# Record actual execution
ranker.record("resize_image", payload_size=2048, actual_ms=312)

# Retrain (also auto-triggered every retrain_every_n records)
metrics = ranker.retrain()
print(f"MAE: {metrics.mae:.1f}ms, promoted: {metrics.promoted}")
```

## Quick Start — batch ranking (v2)

```python
from chronoq_ranker import TaskRanker, TaskCandidate

ranker = TaskRanker(storage="sqlite:///telemetry.db")

candidates = [
    TaskCandidate(task_id="a", task_type="pdf_extract", features={"payload_size": 2_000_000}),
    TaskCandidate(task_id="b", task_type="thumbnail",   features={"payload_size":    50_000}),
    TaskCandidate(task_id="c", task_type="pdf_extract", features={"payload_size":   500_000}),
]
# Returns ScoredTask list sorted ascending; rank 0 = run next.
for scored in ranker.predict_scores(candidates):
    print(f"rank={scored.rank} {scored.task_id} score={scored.score:.1f}")
```

## Configuration

```python
from chronoq_ranker import RankerConfig, TaskRanker

config = RankerConfig(
    cold_start_threshold=50,              # Records before promoting to GradientBoosting
    retrain_every_n=100,                  # Auto-retrain interval
    drift_threshold_mae_ms=500,           # MAE threshold for drift detection
    incremental_rounds=10,                # LambdaRank warm-start rounds (W3+)
    min_groups=20,                        # Minimum query-groups per fit
    full_refit_every_n_incrementals=20,   # Force full refit cadence
    psi_threshold=0.2,                    # Per-feature drift warn threshold (W3+)
    storage_uri="sqlite:///telemetry.db",
)
ranker = TaskRanker(config=config)
```

## Feature schema (v2, user-declarable)

```python
from chronoq_ranker import DefaultExtractor, FeatureSchema, FeatureExtractor

# Ships by default — 15 features (task_type, payload_size, hour_of_day, day_of_week,
# queue_depth, queue_depth_same_type, recent_mean_ms_this_type, recent_p95_ms_this_type,
# recent_count_this_type, time_since_last_retrain_s, worker_count_busy, worker_count_idle,
# prompt_length, user_tier, retry_count).
ranker = TaskRanker(feature_extractor=DefaultExtractor())

# Or roll your own schema for a domain-specific workload:
class MyExtractor(FeatureExtractor):
    schema = FeatureSchema(version="my-v1", numeric=["payload_size"], categorical=["task_type"])
    def extract(self, candidate, context=None):
        return {"task_type": candidate.task_type, "payload_size": float(candidate.features["payload_size"])}
    def extract_from_record(self, record):
        return {"task_type": record.task_type, "payload_size": float(record.payload_size)}

ranker = TaskRanker(feature_extractor=MyExtractor())
```

## Storage Backends

- `"memory://"` — In-memory (testing/ephemeral)
- `"sqlite:///path/to/db"` — SQLite (persistent; auto-migrates v1 schemas)

## Integration Patterns

Works with any task system — Celery, Kafka, FastAPI background tasks, custom workers:

```python
# Before task dispatch (batch)
scored = ranker.predict_scores(candidates)
next_task = scored[0].task_id

# After task execution
ranker.record(task_type, payload_size, actual_ms=elapsed)
```

## v1 compatibility

`TaskPredictor` and `PredictorConfig` are retained as deprecated aliases for one release cycle. Imports from `chronoq_ranker.predictor` still resolve via a shim module that emits a `DeprecationWarning`. Migrate at your leisure; the aliases land on the next major version's removal list.

## Boundary guarantee

`chronoq-ranker` has **zero** imports from `chronoq-demo-server`, Redis, FastAPI, Celery, or vLLM. Runtime deps: `lightgbm` (W3+), `numpy`, `pydantic`, `loguru`. Verify any time with `/boundary-check`.
