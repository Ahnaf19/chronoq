# Chronoq

**Learning-to-rank scheduling for Python job queues.** Replaces FIFO with an online-learning [LambdaRank](https://en.wikipedia.org/wiki/Learning_to_rank) ranker that predicts job duration from telemetry and reorders pending work shortest-job-first. Plug it into Celery, a reference FastAPI+Redis server, or benchmark against public traces — all in one monorepo.

![CI](https://github.com/Ahnaf19/chronoq/actions/workflows/ci.yml/badge.svg)
![Python](https://img.shields.io/badge/python-3.11%2B-blue?style=flat-square)
![License](https://img.shields.io/badge/license-MIT-green?style=flat-square)
![Status](https://img.shields.io/badge/status-v2%20in%20progress-yellow?style=flat-square)

> ⚠️ **v2 in progress.** Repo is mid-rewrite from a FastAPI+Redis queue (v1) to a library-first structure. Current state: Chunk 0 scaffold complete. Ranker LambdaRank land in Chunk 1. First benchmark numbers land in Chunk 2. See [`docs/v2/`](docs/v2/) for design, [`docs/v1/`](docs/v1/) for the prior FastAPI+Redis architecture (still runs in `demo-server/`).

---

## Why Chronoq

Every Python task queue (Celery, RQ, Dramatiq, arq, Hatchet, Temporal) schedules in FIFO or static-priority order. On workloads where durations vary 2–4 orders of magnitude — ML training, LLM inference, media transcoding, document AI, data pipelines — this causes head-of-line blocking: short tasks wait behind long ones.

Learned scheduling has been proven repeatedly in research (Resource Central SOSP'17 = 5% packing improvement; Decima SIGCOMM'19 = 21–50% lower JCT; vLLM-LTR NeurIPS'24 = 2.8× lower chatbot latency) but has not propagated to the Python task-queue layer. **Chronoq closes that gap** — with a LambdaRank ranker you can plug into your existing queue.

---

## Layout

```
chronoq/
├── ranker/                   # chronoq-ranker — ML library (CPU LightGBM LambdaRank)
├── bench/                    # chronoq-bench — SimPy simulator + 5 baselines + public traces
├── integrations/celery/      # chronoq-celery — Celery plugin (shadow/active/fifo modes)
├── demo-server/              # reference FastAPI+Redis integration (v1, demoted)
└── docs/                     # docs/v1/ (archived), docs/v2/ (current)
```

---

## Status

| Chunk | Status | Deliverable |
|---|---|---|
| 0 — Scaffold + team + docs | ⏳ in progress | workspace, `.claude/` team, docs restructure |
| 1 — `chronoq-ranker` | pending | LightGBM LambdaRank library, Spearman ρ ≥ 0.80 target |
| 2 — `chronoq-bench` | pending | `make bench` with 5 baselines + p99-vs-load plot |
| 3 — `chronoq-celery` | pending | Drop-in Celery plugin, 15%+ JCT improvement demo |
| 4 — Polish + promo | pending | PyPI releases, blog post, Show HN |

Full milestone detail: [`docs/v2/README.md`](docs/v2/README.md).

---

## Quick Start

*(v1 demo-server; v2 install surface lands Chunk 3.)*

```bash
git clone https://github.com/Ahnaf19/chronoq.git
cd chronoq
uv sync
uv run pytest -v                # 73 tests
```

Run the v1 reference server:

```bash
docker compose up                # Redis + FastAPI
# POST a task:
curl -X POST http://localhost:8000/tasks -H 'content-type: application/json' \
  -d '{"task_type":"resize","payload_size":1024}'
```

See [`docs/v1/user-guide.md`](docs/v1/user-guide.md) for the full v1 walkthrough.

---

## Documentation

| Audience | Start here |
|---|---|
| **Trying Chronoq** | [`docs/v2/README.md`](docs/v2/README.md) — landing + chunk status |
| **Contributing** | [`docs/v2/architecture.md`](docs/v2/architecture.md) — system design |
| **Stack details** | [`docs/v2/tech-stack.md`](docs/v2/tech-stack.md) — dependencies, versions, rationale |
| **Historical (v1)** | [`docs/v1/`](docs/v1/) — FastAPI+Redis architecture (still in `demo-server/`) |

---

## License

MIT — see [LICENSE](LICENSE).
