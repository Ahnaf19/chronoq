# Contributing to Chronoq

Contributions are welcome. This document covers the development setup, code standards, and PR process.

## Development Setup

```bash
# Clone and install
git clone git@github.com:Ahnaf19/chronoq.git
cd chronoq
uv sync

# Verify everything works
uv run pytest -v
uv run ruff check .
```

**Requirements:** Python 3.11+, [uv](https://docs.astral.sh/uv/), Redis (for server integration tests with real Redis, or fakeredis handles unit tests automatically).

## Project Structure

This is a uv workspace monorepo with four packages:

- `ranker/` — standalone learning-to-rank scheduling library (no Redis/FastAPI dependency)
- `bench/` — benchmark harness (SimPy simulator + traces + baselines; Chunk 2+)
- `integrations/celery/` — Celery plugin (Chunk 3+)
- `demo-server/` — reference FastAPI+Redis integration (v1 demoted)

Tests live under `tests/{ranker,server,bench,celery}/` mirroring the packages.

## Code Standards

- **Formatter/Linter:** Ruff with `line-length=100`, `target-version="py311"`, double quotes
- **Type hints:** Required on all public functions. Use `X | None` union style (not `Optional[X]`)
- **Docstrings:** Google-style on public classes and methods
- **Imports:** Use `from __future__ import annotations` where needed for forward refs. Keep type-only imports in `TYPE_CHECKING` blocks.

```bash
# Lint and format
uv run ruff check .
uv run ruff format .
```

## Running Tests

```bash
# Full suite
uv run pytest -v

# Ranker tests only
uv run pytest tests/ranker/ -v

# Server tests only (uses fakeredis, no real Redis needed)
uv run pytest tests/server/ -v

# With coverage
uv run pytest --cov=chronoq_ranker --cov=chronoq_demo_server
```

## Making Changes

1. **Fork** the repository and create a branch from `main`.
2. **Write tests** for new functionality. Maintain or improve coverage.
3. **Run the full check suite** before pushing:
   ```bash
   uv run ruff check . && uv run ruff format --check . && uv run pytest -v
   ```
4. **Open a pull request** against `main` with a clear description of what changed and why.

### Commit Messages

Use conventional-style prefixes:

- `feat:` — new feature
- `fix:` — bug fix
- `docs:` — documentation only
- `test:` — test additions or fixes
- `chore:` — tooling, CI, dependencies

### Important Boundaries

- `chronoq-ranker` must **never** import from `chronoq-demo-server`, Redis, FastAPI, Celery, or vLLM. It is a standalone library. Verify with `/boundary-check`.
- Server tests should use `fakeredis` — do not require a running Redis instance for unit tests.
- Any edit to `ranker/chronoq_ranker/{ranker,schemas,config,features,__init__}.py` or `models/base.py` / `storage/base.py` → run `/architecture-check` first (library-architect).
- Any edit under `ranker/chronoq_ranker/{models,features,drift}.py` → run `/ml-review` (ml-engineer).

## Reporting Issues

- **Bugs:** Open an issue with steps to reproduce, expected behavior, and actual behavior.
- **Feature requests:** Open an issue describing the use case and proposed approach.
