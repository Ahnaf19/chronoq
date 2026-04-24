# Chronoq

> Learning-to-rank scheduling for Python task queues. Replace FIFO with an
> online LambdaRank. 2-line Celery drop-in.

![CI](https://github.com/Ahnaf19/chronoq/actions/workflows/ci.yml/badge.svg)
![Python](https://img.shields.io/badge/python-3.10%20|%203.11%20|%203.12-blue?style=flat-square)
![License](https://img.shields.io/badge/license-MIT-green?style=flat-square)

![hero](docs/assets/jct_vs_load.png)

**+32% mean JCT · +17.5% p99** vs FCFS on synthetic Pareto · **within 5.1%** of
SJF-oracle on real BurstGPT traces · byte-identical reproducibility across
macOS + Windows.

---

## Install & try (30 seconds)

```bash
pip install chronoq-celery
```

```python
from chronoq_celery import LearnedScheduler, attach_signals
from celery import Celery

app = Celery("myapp", broker="redis://localhost:6379/0")
scheduler = LearnedScheduler(mode="active")  # or "shadow" / "fifo"
attach_signals(app, scheduler)
```

Already running production Celery? Flip `mode="shadow"` — the ranker scores tasks
without changing any dispatch behavior, so you can measure the potential win
first, then flip to `"active"`.

---

## Why this exists

Python task queues — Celery, RQ, Dramatiq, Hatchet, Temporal — all ship FIFO or
static priority. On heavy-tail workloads (LLM inference, media transcoding, ML
training), a 20ms `resize` waits behind a 1.8s `transcode` with no good reason.

Ten-plus years of systems research says learning-to-rank beats FIFO here:
- Microsoft **Resource Central** (SOSP'17): +5% VM packing from lifetime prediction
- MIT **Decima** (SIGCOMM'19): −21 to −50% JCT on Spark via RL-learned scheduling
- UCSD **vLLM-LTR** (NeurIPS'24): 2.8× lower LLM chatbot latency from ranker-based scheduling

None of this has shipped to the Python task-queue layer. Chronoq closes that gap.

---

## Evidence — validated on 4 real workload traces

| Trace | Source | Headline |
|---|---|---|
| Synthetic Pareto (seeded) | Generated | **+32% mean / +17.5% p99** vs FCFS at ρ=0.7 |
| BurstGPT (LLM inference) | HuggingFace `lzzmm/BurstGPT` | **Within 5.1% of SJF-oracle** at p99 |
| Google Borg 2011 (cluster batch) | GCS `gs://clusterdata-2011-2` | **+14–22% mean JCT** at ρ ≥ 0.8 |
| Azure Functions 2019 (serverless) | `Azure/AzurePublicDataset` | **+10% mean JCT** (p99 structurally bound on this workload) |

![Feature importance](docs/assets/ablation_features.png)
![Drift recovery](docs/assets/drift_recovery.png)

All results reproducible with one command (`make bench`). Byte-identical
`results.json` across macOS and Windows (SHA-256 verified). Full methodology +
per-trace tables in [`docs/v2/BENCHMARKS.md`](docs/v2/BENCHMARKS.md).

---

## What's in the box

- **`chronoq-ranker`** — LightGBM LambdaRank over 15 features, online incremental
  retraining, drift detection. Standalone ML library; zero deps on Celery / Redis /
  FastAPI.
- **`chronoq-celery`** — pre-broker gate with `fifo` / `shadow` / `active` modes.
  Shadow mode logs scores without changing behavior — measure before switching.
- **`chronoq-bench`** — SimPy simulator, 5 baselines (incl. SJF oracle + SRPT
  approximation), 4 real-trace loaders, reproducible `make bench`.

---

## Usage — standalone ranker

```python
from chronoq_ranker import TaskRanker, TaskCandidate

ranker = TaskRanker(storage="sqlite:///jobs.db")
ranker.record(task_type="resize", payload_size=2048, actual_ms=312.4)
ranker.record(task_type="transcode", payload_size=8000, actual_ms=1780.1)
# ... more telemetry over time triggers retraining ...

scored = ranker.predict_scores([
    TaskCandidate(task_id="j1", task_type="transcode", payload_size=8000),
    TaskCandidate(task_id="j2", task_type="resize",    payload_size=500),
])
# scored[0] is the job LambdaRank predicts finishes fastest
```

---

## Honest limitations

- **p99 starvation at saturation** (ρ ≥ 0.8): SJF-family tradeoff — short-first
  bias indefinitely delays long jobs at the tail. Pair with aging in production.
  An aging-aware scheduler is planned for v0.3.0.
- **Workload-dependent wins**: on traces where SJF-oracle can't improve p99
  (narrow duration variance, single task type), the ranker also can't. The bench
  harness is a diagnostic tool for this — see the Azure Functions result.
- **Pre-1.0 API**: breaking changes allowed in minor-version bumps under the
  project's semver policy; deprecation shims land one minor ahead.

---

## Deeper reading

- [`docs/v2/architecture.md`](docs/v2/architecture.md) — system design, component map
- [`docs/v2/BENCHMARKS.md`](docs/v2/BENCHMARKS.md) — full methodology, all numbers, honest framing
- [`docs/v2/INTEGRATIONS.md`](docs/v2/INTEGRATIONS.md) — Celery quickstart, shadow→active rollout guide
- [`integrations/celery/examples/`](integrations/celery/examples/) — runnable eager-mode + Docker demos

---

## Status & roadmap

- **v0.2.0** (shipping): 4 real-trace validation · multi-seed error bands · multi-worker simulator · Celery integration with eager + Docker demos · byte-identical cross-platform reproducibility
- **v0.2.1** (next patch): 3 more traces — Philly DL-training · Helios multi-tenant GPU · Mooncake cross-provider LLM (Kimi FAST'25)
- **v0.3.0** (next minor): SRPT+aging scheduler (bounded p99 starvation) · more cluster / microservice / HPC traces · possible Hatchet or Temporal integration

See [`CHANGELOG.md`](CHANGELOG.md) for full release history.

---

## License

MIT. Contributions welcome — issues for bug reports, PRs with tests for changes.
