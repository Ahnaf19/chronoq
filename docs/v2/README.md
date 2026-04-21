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
| [`BENCHMARKS.md`](BENCHMARKS.md) | current | Reproduction steps, trace sources, 5 baselines, metrics, results |
| [`INTEGRATIONS.md`](INTEGRATIONS.md) | current | Celery plugin quickstart, Hatchet sidecar design, vLLM deferred |

## Chunk status

| Chunk | Status | What shipped | Key numbers |
|---|---|---|---|
| **0 — Scaffold + team + docs** | ✅ complete | Renames, workspace stubs, 5 subagents, 4 slash commands, hooks, docs restructure | 73 tests, `/boundary-check` clean |
| **1 — `chronoq-ranker`** | ✅ complete | LambdaRank estimator, OracleRanker, DriftDetector, 15-feature extractor, incremental warm-start | Spearman ρ=0.87, pairwise acc=0.89, retrain 110ms on 10k |
| **2 — `chronoq-bench`** | ✅ complete | SimPy DES, 5 baselines, 3 experiments, `make bench`, bench-smoke CI | **+32% mean JCT, +17.5% p99 vs FCFS @ load=0.7** — 185 tests |
| **3 — `chronoq-celery`** | ✅ complete | `LearnedScheduler` (shadow/active/fifo), `TypeStatsTracker`, `attach_signals`, 32 tests | **+55% mean JCT vs FIFO** on 200-task Pareto demo |
| 4 — Polish + promo | pending | — | README hero plot, PyPI releases, blog post |

## Reading order for contributors

1. [`architecture.md`](architecture.md) — understand the shape of the library and how v1 pieces map into v2.
2. [`tech-stack.md`](tech-stack.md) — understand the dependency set and versioning decisions.
3. (Chunk 2+) `BENCHMARKS.md` — run `make bench` and read the results.
4. (Chunk 3+) `INTEGRATIONS.md` — plug Chronoq into your own Celery app.

For the elevator pitch, installation, and quickstart, see the [root README](../../README.md).
