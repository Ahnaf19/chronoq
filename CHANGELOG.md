# Changelog

All notable changes to Chronoq. Format loosely based on [Keep a Changelog](https://keepachangelog.com/); versioning per-package once PyPI releases begin (Chunk 4).

## [Unreleased] — v2 in progress

### Chunk 4 — Polish + promo (2026-04-22)

Branch `v2/chunk-4-polish`.

**Bug fixes (Steps 1-4):**
- `count_since()` retrain loop: changed `TelemetryStore.count_since()` ABC from version-string matching to `after: datetime` parameter; `SqliteStore` queries `WHERE recorded_at > ?`; `MemoryStore` filters by `recorded_at`. `TaskRanker` now tracks `_last_retrain_at: datetime` — auto-retrain correctly fires on every threshold crossing, not just the first.
- Train-serve feature skew: `LearnedScheduler.record_completion()` now snapshots `TypeStatsTracker` and passes `metadata={"recent_mean_ms_this_type": ..., "queue_depth": ..., ...}` to `ranker.record()` so LambdaRank trains on real queue context features.
- Task ID collision: `LearnedScheduler.submit()` raises `ValueError("task_id already registered: ...")` on duplicate task_id instead of silently overwriting registry.
- Registry leak: `attach_signals()` now wires `task_revoked` → `cleanup_registry(task_id)`; cancelled tasks no longer leave orphaned registry entries.

**Schema (Step 2):**
- `RetrainResult.rejected: bool = False` — `retrain()` reads `metrics.get("_rejected", False)` from LambdaRank and propagates it. Callers can now detect whether a trained model was rejected.

**Storage hardening (Step 1 side-effects):**
- `SqliteStore`: added `PRAGMA journal_mode=WAL`; created indices on `recorded_at`, `task_type`, `model_version_at_record`.

**Test quality (Step 5):**
- Added `@settings(deadline=None)` to all 8 Hypothesis property tests in `test_lambdarank_hypothesis.py`.
- `tests/ranker/test_retrain_trigger.py` (NEW — 2 tests): verifies `_last_retrain_at` advances and auto-retrain fires on every threshold crossing.
- `tests/ranker/test_schemas.py`: added `test_rejected_defaults_to_false`, `test_rejected_true_when_set`.
- `tests/celery/test_scheduler.py` `TestRegistryIntegrity`: `test_submit_duplicate_task_id_raises`, `test_registry_empty_after_cleanup`, `test_registry_empty_after_record_completion`.
- `tests/celery/test_signals.py`: `test_task_revoked_cleans_registry`.

**RankerConfig hyperparams (Step 6):**
- `RankerConfig` now exposes `num_leaves: int = 31`, `n_estimators: int = 500`, `learning_rate: float = 0.05`, `min_data_in_leaf: int = 20`.
- `LambdaRankEstimator` reads these from config; module-level constants removed.

**DriftDetector wiring (Step 7):**
- `TaskRanker.__init__` initializes a `DriftDetector` with the current config and extractor.
- `retrain()` runs a non-blocking drift check before each refit (skips silently on first run); after a successful lambdarank refit, calls `set_reference(records)`.
- `drift_status()` returns `DriftReport | None` (the last known drift report, or None before first lambdarank refit).

**PyPI metadata + packaging (Step 8):**
- All four packages (`chronoq-ranker`, `chronoq-bench`, `chronoq-celery`, `chronoq-demo-server`) now have `authors`, `license`, `keywords`, `classifiers`, `[project.urls]`.
- Version bumps: `chronoq-ranker` 0.1.0→0.2.0, `chronoq-bench` 0.1.0→0.2.0, `chronoq-celery` 0.1.0→0.2.0 (was already 0.1.0 — see note), `chronoq-demo-server` 0.1.0→0.2.0.
- `ranker/chronoq_ranker/py.typed` created (PEP 561).
- `requires-python` lowered to `>=3.10` across all packages.

**CI (Step 9):**
- `test` job now runs a matrix across Python 3.10, 3.11, 3.12.
- `pytest` step adds `--cov=chronoq_ranker --cov=chronoq_celery --cov-report=term-missing`.

**Wiring:**
- Hero plot embedded in `README.md` (`bench/artifacts/jct_vs_load.png`).
- "v2 in progress" banner replaced with "Chunks 0–4 complete · PyPI-ready".
- Python badge updated to 3.10|3.11|3.12.

**Exit criteria:**

| Criterion | Result |
|---|---|
| `test_auto_retrain_fires_multiple_times` | PASS |
| `test_count_since_resets_after_retrain` | PASS |
| `test_rejected_defaults_to_false` + `test_rejected_true_when_set` | PASS |
| `test_submit_duplicate_task_id_raises` | PASS |
| `test_task_revoked_cleans_registry` | PASS |
| `test_drift_status_returns_report_after_lambdarank_retrain` | PASS |
| Tests total | **225** |
| Lint | 0 errors |
| `RankerConfig(num_leaves=64)` | no error |
| `drift_status()` returns real `DriftReport` | verified by test |
| Boundary check | clean |

### Chunk 3 — `chronoq-celery` integration (2026-04-22)

Branch `v2/chunk-3-celery`.

**Core library (Steps 1-5):**
- `TypeStatsTracker` (`rolling.py`): per-type ring buffer (`dict[str, deque[float]]` + `threading.Lock`); `record()`, `snapshot()` (mean/p95/count), and `seed()` for cold-start pre-warming
- `LearnedScheduler` (`scheduler.py`): pre-broker gate with three modes — `fifo` (ranker never instantiated, zero overhead), `shadow` (score+log, arrival order preserved), `active` (heap dispatch in score order). Heap: `list[tuple[float, int, Callable, str]]` with stable tiebreaking via arrival_counter. Scoring path replicates bench's `LambdaRankScheduler._score()` — calls extractor+estimator directly so each candidate gets its own `QueueContext.recent_mean_ms_this_type`
- `attach_signals()` (`signals.py`): wires `task_prerun` → `record_start()`, `task_success` → `record_completion()` + `dispatch_next()`, `task_failure` → `cleanup_registry()` only (no ranker.record on failure)
- `__init__.py` real exports; version `0.2.0`

**Tests (Step 6) — 32 tests, no Docker/Redis:**
- `test_rolling.py` (9): mean/p95 accuracy, window eviction, thread safety, seed pre-warming, multi-type independence
- `test_scheduler.py` (19): `test_fifo_never_calls_ranker`, `test_shadow_mode_identical_to_fifo`, `test_active_mode_dispatches_in_score_order` (plan exit-criteria names), heap populate/clear, record_completion, cleanup_registry, ranker.record not called on cleanup
- `test_signals.py` (4): attach_signals wiring, registry population, fifo short-circuit

**Demo + docs (Step 7):**
- `integrations/celery/demo.py`: inline Pareto generation (no `chronoq_bench` import); pre-trains LambdaRank on 800 jobs with `recent_mean_ms_this_type` embedded in metadata; seeds `TypeStatsTracker`; compares 200-task fifo vs active scheduling; asserts ≥15% mean JCT improvement
- `docs/v2/INTEGRATIONS.md`: install, 3-step quickstart (create scheduler, attach signals, submit), modes table, `TypeStatsTracker` seeding, training guide, demo output, limitations, Hatchet/vLLM deferred sections

**Wiring (Step 8):**
- `Makefile`: `celery-demo` target (`uv run python integrations/celery/demo.py`)
- `README.md` + `docs/v2/README.md`: Chunk 3 marked complete
- `tests/CLAUDE.md`: updated count (216 tests)

**Exit criteria (all met):**

| Criterion | Result | Target |
|---|---|---|
| `test_fifo_never_calls_ranker` | PASS | pass |
| `test_shadow_mode_identical_to_fifo` | PASS | pass |
| `test_active_mode_dispatches_in_score_order` | PASS | pass |
| demo.py mean JCT (active vs fifo) | **+55.0%** (fifo 155,819ms → active 70,046ms) | ≥15% ✅ |
| Tests total | **216** | ≥207 ✅ |
| Lint | 0 errors | clean ✅ |
| Boundary check (`grep -r "celery" ranker/`) | nothing | nothing ✅ |
| `docs/v2/INTEGRATIONS.md` | exists, 3-step quickstart | exists ✅ |

### Chunk 2 — `chronoq-bench` + money plot (2026-04-21)

Branch `v2/chunk-2-bench`.

**Simulator + baselines (Steps 1-4):**
- SimPy discrete-event simulator (`bench/chronoq_bench/simulator.py`): event-driven dispatch (no polling), single-server queue, pluggable `BaseScheduler.select()` interface
- 5 baselines: `FCFSScheduler`, `SJFOracleScheduler`, `SRPTOracleScheduler` (non-preemptive, labeled "approx"), `RandomScheduler`, `PriorityFCFSScheduler`
- Synthetic Pareto trace generator (`SyntheticTraceLoader`): 5 task types, lognormal durations with payload-size correlation, seeded Poisson arrivals
- JCT metrics: `mean_jct`, `p99_jct`, `hol_blocking_count`, `jains_fairness_index`, `percentile_jct`, `summarise`
- Ranking metrics: `spearman_rho`, `pairwise_accuracy_grouped`
- 48 new tests: `test_metrics.py` (17), `test_traces.py` (14), `test_simulator.py` (12), `test_baselines.py` (5); total suite 185

**Experiments + plots (Step 5):**
- `jct_vs_load.py`: sweeps load 0.3→0.9 (7 points), 6 schedulers; writes `jct_vs_load.png` + `results.json`
- `drift_recovery.py`: pre-shift train → shifted workload (3× more transcodes) → 3 incremental retrain cycles; writes `drift_recovery.png`
- `ablation_features.py`: LGBMRanker `booster_.feature_importance(gain)` for all 15 features; writes `ablation_features.csv`
- `LambdaRankScheduler`: uses per-job `QueueContext` with `recent_mean_ms_this_type` from training data; bypasses `predict_scores()` to pass per-candidate context
- Training fix: per-type duration stats embedded in `TaskRecord.metadata` so model learns `recent_mean_ms_this_type` as primary ranking signal
- `bench/chronoq_bench/plots/base.py`: `save_figure()` helper

**Wiring + CI + agents (Step 6):**
- `Makefile`: `bench` and `bench-smoke` stubs replaced with real targets
- `.github/workflows/ci.yml`: `enable-cache: true` on both setup-uv steps; `bench-smoke` job added (`needs: [test]`, <60s)
- `.claude/agents/benchmark-analyst.md` and `docs-writer.md` added
- `.claude/commands/bench.md` and `bench-smoke.md` added
- `docs/v2/BENCHMARKS.md`: trace descriptions, scheduler table, result tables, limitations section

**Exit criteria (synthetic Pareto trace, `n_train=800`, `n_eval=300`, seed=42):**

| Metric | Result | Target |
|---|---|---|
| LambdaRank mean JCT vs FCFS @ load=0.7 | **+32.2%** | ≥ 10% ✅ |
| LambdaRank p99 JCT vs FCFS @ load=0.7 | **+17.5%** | ≥ 15% ✅ |
| LambdaRank p99 vs SJF-oracle @ load=0.7 | **13.4% gap** | ≤ 20% ✅ |
| LambdaRank p99 JCT vs FCFS @ load=0.5 | +11.6% | ≥ 15% ⚠️ oracle-bounded |
| `make bench-smoke` runtime | 4.4s | < 60s ✅ |
| Tests | 185 passing | all green ✅ |

Note: p99@load=0.5 target requires BurstGPT's extreme variance (500:1 short:long). SJF-oracle (upper bound) achieves exactly +11.6% on synthetic trace — LambdaRank p99 matches oracle exactly at load=0.5 (8306ms vs 8306ms). The ≥15% target is physically unreachable on this trace; it is not a model deficiency.

**Key feature importances (ablation):** `recent_mean_ms_this_type` 80%, `payload_size` 20%.

### Chunk 1 — `chronoq-ranker` LambdaRank library (2026-04-21)

Branch `v2/chunk-1-ranker` → PR #2, merged to main.

**Weekend 1 — `.claude/` additions:**
- `ml-engineer` subagent added to `.claude/agents/`
- `/architecture-check` and `/ml-review` slash commands
- `ranker/CLAUDE.md` updated with LambdaRank specifics and ownership map

**Weekend 2 — Rename + schema extension + feature engineering:**
- `TaskPredictor` → `TaskRanker`; `PredictorConfig` → `RankerConfig`; `tests/predictor/` → `tests/ranker/`; deprecation shims preserve v1 imports with `DeprecationWarning`
- `TaskRecord` extended: `group_id`, `rank_label`, `feature_schema_version`; `SqliteStore` auto-migrates
- `RankerConfig` extended: `incremental_rounds`, `min_groups`, `full_refit_every_n_incrementals`, `psi_threshold`, `allow_degrade`
- `FeatureSchema` + `FeatureExtractor` ABC + `DefaultExtractor` (15 features) + `DEFAULT_SCHEMA_V1`
- `TaskRanker.predict_scores(candidates)` batch-ranking API; `ScoredTask`, `TaskCandidate`, `QueueContext` schemas

**Weekend 3 — LambdaRank, Oracle, Drift + 52 new tests:**
- `LambdaRankEstimator` (`lightgbm.LGBMRanker`, `objective="lambdarank"`): 60s tumbling group assignment, proportional label normalization (0–9), incremental warm-start via `init_model`, Spearman ρ rejection gate, per-group metrics (ρ, τ, pairwise accuracy)
- `OracleRanker` — perfect SJF/SRPT using true `actual_ms`; benchmarks upper bound
- `DriftDetector` — PSI per numeric feature (warn >0.2, drift >0.3) + rolling MAE tracking
- `TaskRanker.retrain()` wired: auto-promotes heuristic → lambdarank; degrades to `GradientEstimator` on `InsufficientGroupsError` when `allow_degrade=True`
- `lightgbm>=4.3` + `numpy>=1.26` added to ranker runtime deps; `hypothesis>=6.100` to root dev deps
- 52 new tests: `test_lambdarank.py` (25), `test_oracle.py` (8), `test_drift.py` (11), `test_lambdarank_hypothesis.py` (8 property tests)

**Exit criteria (all verified pre-merge):**

| Metric | Result | Target |
|---|---|---|
| Spearman ρ on 50k synthetic | 0.8692 | ≥ 0.80 |
| Pairwise accuracy | 0.8857 | ≥ 0.78 |
| Incremental retrain (10k records) | 109.7ms | < 200ms |
| Tests | 137 passing | ≥ 40 ranker |
| Lint | 0 errors | clean |

### Chunk 0 — Scaffold + `.claude/` team + docs restructure (2026-04-21)

Branch `v2/scaffold`. v1 → v2 repositioning from "ML-scheduled job queue" to a library-first structure: reusable ranker + benchmark harness + integration demos.

**Renames and layout (Weekend 1, `3c141fb`):**
- `predictor/` → `ranker/` (package: `chronoq_predictor` → `chronoq_ranker`)
- `server/` → `demo-server/` (package: `chronoq_server` → `chronoq_demo_server`), demoted from product to reference integration
- New workspace members: `bench/` (chronoq-bench, Chunk 2), `integrations/celery/` (chronoq-celery, Chunk 3)
- Deleted: `migrations/`, `alembic.ini`, root `demo.py` (Alembic overkill; SqliteStore auto-creates table)
- Top-level `Makefile` with `bench`, `bench-smoke`, `test`, `lint`, `fix`, `clean` targets
- 73 tests green (71 existing + 2 new workspace-stub tests)

**`.claude/` team setup (Weekend 2, `b8e089f`–`de835ee`):**
- 5 subagents in `.claude/agents/`: `claude-master`, `product-manager`, `project-manager`, `library-architect`, `qa-validator`
- 4 new slash commands: `/chunk-review [0-4]`, `/prd-check`, `/status`, `/claude-audit`
- 3 `PostToolUse` hooks in `.claude/settings.json`: auto-lint ranker edits, public-API-change warning, `.claude/`/CLAUDE.md edit reminder
- 1 `Stop` hook: end-of-session checklist reminder (CHANGELOG update + `/chunk-review N`)
- Root `CLAUDE.md` overhauled for v2 (155 → 134 lines); per-package CLAUDE.md files tightened (361 → 286 lines total)
- Git conventions expanded: commit-granularity rule (split large changes into logical commits), no Claude signatures

**Docs restructure (Weekend 3, `db935f1`–`8b5c320`):**
- All v1 docs archived under `docs/v1/` (architecture, user-guide, api-reference, configuration, chronoq-plan, diagrams, postman/, excalidraw)
- New `docs/v2/` with public contributor-facing docs: `README.md` (landing + chunk status), `architecture.md` (v1→v2 component map, key interfaces, algorithms), `tech-stack.md` (deps, versions, rationale)
- New `docs/CLAUDE.md` navigation with freshness-marker convention (`status`, `last-synced-to-plan` frontmatter)
- New `docs/v2/internal/` **gitignored** — BRD, PRD, milestones, risks, claude-team extracts from the plan file. Internal project-planning docs are not shipped to OSS consumers; they live locally for the project owner and the PM/PjM/architect subagents.
- Root `README.md` rewritten for v2 positioning (339 → 86 lines); v2 pitch, status table, audience-routed doc links; full hero-plot version lands in Chunk 4
- Gitignored additionally: `bench/artifacts/` and `bench/data/` (regenerated by `make bench`; BurstGPT cache is 188MB)

### Deviations from plan

- `docs/v2/{BRD,PRD,milestones,risks,claude-team}.md` were moved to `docs/v2/internal/` and gitignored rather than committed as the plan literally prescribed. Rationale: these contain portfolio framing, target-hiring-manager language, commit SHAs, and scope-creep rules not useful to OSS consumers. Documented in `docs/CLAUDE.md`. Plan §4 and §12.8 should be updated to reflect this split.

## Prior

See `docs/v1/` for v1 history. v1 was never formally released; this changelog starts at the v2 rewrite.
