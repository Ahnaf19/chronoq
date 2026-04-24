---
status: current
last-synced-to-plan: 2026-04-24
---

# Chronoq v2 docs

**Status:** v0.2.0 pre-release. 4 real-trace validation complete. See [root README](../../README.md) for the elevator pitch and latest evidence plots.

## Contents

| File | Status | Scope |
|---|---|---|
| [`architecture.md`](architecture.md) | current | System design, v1→v2 component map, key interfaces, algorithms |
| [`tech-stack.md`](tech-stack.md) | current | Dependencies, versions, rationale, paid-tier upgrade path |
| [`BENCHMARKS.md`](BENCHMARKS.md) | current | Reproduction steps, trace sources, 5 baselines, metrics, results |
| [`INTEGRATIONS.md`](INTEGRATIONS.md) | current | Celery plugin quickstart, Hatchet sidecar design, vLLM deferred |

## Release milestones

| Version | Status | Highlight |
|---|---|---|
| v0.1.0 | retired | FastAPI+Redis queue (demoted to `demo-server/` reference) |
| v0.2.0 | shipping | First PyPI. 4 real traces, multi-seed, multi-worker, Celery demos |
| v0.2.1 | next patch | +3 real traces (Philly, Helios, Mooncake) |
| v0.3.0 | next minor | SRPT+aging scheduler, more traces, possible Hatchet/Temporal integration |

## Reading order for contributors

1. [`architecture.md`](architecture.md) — understand the shape of the library and how v1 pieces map into v2.
2. [`tech-stack.md`](tech-stack.md) — understand the dependency set and versioning decisions.
3. `BENCHMARKS.md` — run `make bench` and read the results.
4. `INTEGRATIONS.md` — plug Chronoq into your own Celery app.

For the elevator pitch, installation, and quickstart, see the [root README](../../README.md).
