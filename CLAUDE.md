# Chronoq (v2 in progress)

Learning-to-rank scheduling library for Python job queues. Replaces FIFO/static-priority ordering with online-learning LambdaRank trained on job-duration telemetry.

**Phase:** Chunk 3 shipped (`chronoq-celery` — `LearnedScheduler` with shadow/active/fifo modes, +55% mean JCT vs FIFO on 200-task Pareto demo, 32 tests). Chunks 0–3 complete; Chunk 4 next (Polish + promo: PyPI releases, blog post, hero README). Full plan: `/Users/ahnaftanjid/.claude/plans/ok-i-want-golden-knuth.md`. v2 docs: `docs/v2/`.

## Monorepo Layout

```
chronoq/
├── ranker/                    # chronoq-ranker — ML library (v1 regressor, becomes LTR in Chunk 1)
├── bench/                     # chronoq-bench — simulator + traces + baselines (Chunk 2)
├── integrations/celery/       # chronoq-celery — Celery plugin (Chunk 3)
├── demo-server/               # reference FastAPI+Redis integration (v1 demoted)
├── tests/                     # tests/{ranker,bench,celery,demo_server}/
├── docs/                      # Chunk 0 W3: split into docs/v1/ and docs/v2/
└── .claude/                   # agents, commands, settings — see §Claude Team
```

**Workspace members** (root `pyproject.toml`): `ranker`, `bench`, `integrations/celery`, `demo-server`. Managed by `uv`.

## Critical Boundaries

- **`chronoq-ranker` MUST NEVER import from `chronoq-demo-server`, Redis, FastAPI, Celery, or vLLM.** It is a standalone library.
- Verify: `grep -r "chronoq_demo_server\|fastapi\|celery" ranker/` returns nothing.
- Run `/boundary-check` at any time.

## Tech Stack

- Python 3.11, `uv` workspace
- **Ranker** (Chunk 1+): Pydantic v2, LightGBM `LGBMRanker` (lambdarank objective), loguru, sqlite3 stdlib. No pandas in runtime.
- **Bench** (Chunk 2+): SimPy, matplotlib, pyarrow, huggingface_hub, pandas.
- **Celery integration** (Chunk 3+): Celery 5.4+, redis-py.
- **Demo-server** (kept for reference): FastAPI, uvicorn, redis-py async.
- **Testing**: pytest + pytest-asyncio (auto mode), fakeredis[lua], hypothesis (Chunk 1+).
- **Lint**: ruff — line-length 100, target-version py311, double quotes.
- **CI**: GitHub Actions — lint + test on push/PR.

## Conventions

- Type hints on all public functions. `X | None`, never `Optional[X]`.
- Google-style docstrings on public classes/methods.
- `from __future__ import annotations` + `TYPE_CHECKING` blocks for forward refs.
- `datetime.now(UTC)` with `from datetime import UTC, datetime`.
- Thread safety: `threading.Lock` in `ranker/ranker.py` protects only the estimator reference swap. Fitting happens outside the lock.
- Storage: `SqliteStore` has its own `threading.Lock` + `check_same_thread=False`.
- Async workers: `asyncio.to_thread()` for blocking ranker calls.

## Git Conventions

**Signature and format:**
- **Never add Claude signatures.** No "Co-Authored-By: Claude", no "🤖 Generated with Claude Code", no attribution footers. User is sole author.
- Conventional prefixes: `feat:`, `fix:`, `test:`, `docs:`, `chore:`, `refactor:`, `style:`, `ci:`, `perf:`, `build:`.
- Subject imperative, <72 chars. Body wraps at 100. HEREDOC for multi-line.

**Granularity — split large changes into logical commits:**
- One commit = one coherent intent readable from the subject alone.
- Good boundaries: per-package, rename vs behavior change, schema vs impl, tests vs prod, config vs code.
- When in doubt, more commits. Squash at merge if desired; cannot un-merge.

**Safety:**
- Don't amend published commits.
- No `--no-verify`, `--force`, `--amend` on pushed commits without explicit ask.
- Prefer `git add <path>` over `git add -A` when tree has mixed concerns.

## Commands

```bash
uv sync                        # Install workspace
uv run pytest -v               # All tests
uv run ruff check .            # Lint
uv run ruff check . --fix      # Lint + auto-fix
uv run ruff format .           # Format
make bench                     # (Chunk 2+) full benchmark harness
make test / make lint / make fix
```

## Slash Commands

| Command | Purpose |
|---|---|
| `/validate` | Lint + format + all tests |
| `/test [scope]` | Scoped test run |
| `/fix` | Auto-fix lint/format; verify tests |
| `/boundary-check` | Verify ranker has zero server/framework imports |
| `/sync-docs` | Doc/code sync check |
| `/coverage` | Coverage report |
| `/chunk-review [0-4]` | (v2) Verify current chunk's exit criteria |
| `/prd-check` | (v2) WIP vs PRD functional requirements |
| `/status` | (v2) Current chunk, progress, latest bench |
| `/claude-audit` | (v2) Audit `.claude/` + all CLAUDE.md for staleness |
| `/architecture-check` | (Chunk 1+) Public API drift check |
| `/ml-review` | (Chunk 1+) Ranker code review by ml-engineer |
| `/bench`, `/bench-smoke` | (Chunk 2+) Run benchmarks |
| `/integration-test` | (Chunk 3+) Integration smoke test |
| `/release [pkg]` | (Chunk 4) Release notes + QA gate + `uv publish` |

## Claude Team

Treat Claude as a fractional team. Role subagents live in `.claude/agents/`:

- `claude-master` — meta-agent: audits `.claude/` + CLAUDE.md files; invoked at chunk starts and after any `.claude/` edit.
- `product-manager` — BRD/PRD, feature prioritization, release notes.
- `project-manager` — CHANGELOG, milestone tracking, chunk reviews, PR descriptions.
- `library-architect` — public API, interface contracts, schema versioning.
- `ml-engineer` (Chunk 1+) — ranker, features, LightGBM, drift.
- `senior-backend-dev` (Chunk 3+) — Celery, demo-server, async.
- `benchmark-analyst` (Chunk 2+) — bench interpretation, regression bisection.
- `qa-validator` — runs full validation gate pre-merge.
- `docs-writer` (Chunk 2+) — README + `docs/` sync.

**Rules:**
- Any change to public API in `ranker/chronoq_ranker/{ranker,schemas,config,features}.py` → invoke `library-architect` via `/architecture-check` FIRST.
- End of every chunk → `/chunk-review N` (project-manager).
- Any `.claude/` or `CLAUDE.md` edit → hook reminds to run `/claude-audit` (claude-master).
- New feature proposal → `product-manager` updates PRD before implementation.
- LTR pipeline doubt (features, labels, drift) → invoke `ml-engineer`, don't guess.
- Benchmark regression >5% on any metric in `results.json` → blocks merge until explained.

Full roster + invocation triggers + ownership: plan `/Users/ahnaftanjid/.claude/plans/ok-i-want-golden-knuth.md` §12 (moved to `docs/v2/claude-team.md` in Weekend 3).

## Key Files

- Ranker public API: `ranker/chronoq_ranker/ranker.py` (`TaskRanker`). `predictor.py` is a 22-line deprecated shim re-exporting `TaskRanker as TaskPredictor`.
- Schemas: `ranker/chronoq_ranker/schemas.py` (`TaskRecord`, `TaskCandidate`, `ScoredTask`, `FeatureSchema`, `QueueContext`, `PredictionResult`, `RetrainResult`).
- Config: `ranker/chronoq_ranker/config.py` (`RankerConfig`; `PredictorConfig` is a silent alias).
- Features: `ranker/chronoq_ranker/features.py` (`FeatureExtractor` ABC, `DefaultExtractor`, `DEFAULT_SCHEMA_V1`).
- Models: `ranker/chronoq_ranker/models/{heuristic,gradient}.py` today; adds `lambdarank.py`, `oracle.py` in Chunk 1 W3.
- Storage: `ranker/chronoq_ranker/storage/{sqlite,memory}.py`.
- Shared test fixtures: `tests/conftest.py`.
- Per-package CLAUDE.md exists under `ranker/`, `demo-server/`, `tests/`, `docs/` (and later `bench/`, `integrations/celery/`).

## Subagents

Use the `Agent` tool for open-ended codebase exploration (`subagent_type=Explore`) or role-based work (`subagent_type=<role from Claude Team>`). Don't use subagents for single-file reads or single-command runs.
