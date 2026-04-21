---
status: current
last-synced-to-plan: 2026-04-21
---

# Chronoq v2 docs

**Status:** under construction. v2 is a library-first rewrite of Chronoq — see the [root README](../../README.md) for the elevator pitch.

## Contents

| File | Status | Scope |
|---|---|---|
| [`architecture.md`](architecture.md) | current | System design, v1→v2 component map, key interfaces, algorithms |
| [`tech-stack.md`](tech-stack.md) | current | Dependencies, versions, rationale, paid-tier upgrade path |
| `BENCHMARKS.md` | Chunk 2 | Reproduction steps, trace sources, 5 baselines, metrics |
| `INTEGRATIONS.md` | Chunk 3 | Celery plugin quickstart, Hatchet sidecar design, vLLM deferred |

## Chunk status

| Chunk | Status | What shipped | Exit criteria |
|---|---|---|---|
| **0 — Scaffold + team + docs** | ⏳ W3 in progress | W1: renames + workspace stubs. W2: 5 subagents + 4 slash commands + hooks. W3: docs restructure. | 73 tests green, `/boundary-check` clean, `docs/v2/` present |
| 1 — `chronoq-ranker` | pending | — | Spearman ρ ≥ 0.80, pairwise acc ≥ 0.78 on 50k synthetic |
| 2 — `chronoq-bench` | pending | — | ≥10% mean / ≥15% p99 JCT vs FCFS on BurstGPT |
| 3 — `chronoq-celery` | pending | — | ≥15% mean JCT improvement on 200-task demo |
| 4 — Polish + promo | pending | — | README 90s-test, 1 blog post, PyPI releases |

## Reading order for contributors

1. [`architecture.md`](architecture.md) — understand the shape of the library and how v1 pieces map into v2.
2. [`tech-stack.md`](tech-stack.md) — understand the dependency set and versioning decisions.
3. (Chunk 2+) `BENCHMARKS.md` — run `make bench` and read the results.
4. (Chunk 3+) `INTEGRATIONS.md` — plug Chronoq into your own Celery app.

For the elevator pitch, installation, and quickstart, see the [root README](../../README.md).
