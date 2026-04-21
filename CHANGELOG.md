# Changelog

All notable changes to Chronoq. Format loosely based on [Keep a Changelog](https://keepachangelog.com/); versioning per-package once PyPI releases begin (Chunk 4).

## [Unreleased] — v2 in progress

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
