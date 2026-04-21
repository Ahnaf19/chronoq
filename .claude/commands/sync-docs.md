---
description: Synchronize docs/v2/ and README with current code and bench results. Delegates to docs-writer.
---

Invoke the `docs-writer` subagent with this task:

> Run the `/sync-docs` checklist per your agent spec.
>
> 1. Read `bench/artifacts/results.json` (if present). Extract mean_jct and p99_jct for
>    LambdaRank and FCFS at load=0.7. Compare against the results tables in
>    `docs/v2/BENCHMARKS.md`. Report: in-sync or list specific outdated numbers.
>
> 2. Read `README.md` status table. Verify it marks Chunks 0, 1, 2 complete and includes
>    the `make bench` quickstart. Flag any stale test counts or pending→complete mismatches.
>
> 3. Read `docs/v2/README.md` chunk status table. Verify Chunks 1 and 2 are marked complete
>    with exit-criteria numbers.
>
> 4. Read `docs/v2/architecture.md`. Verify the package layout section matches the actual
>    monorepo structure: `ranker/`, `bench/`, `integrations/celery/`, `demo-server/`,
>    `tests/`, `docs/`. Flag any references to old paths (`predictor/`, `server/`).
>
> 5. Check that every `docs/v2/` file that should have a frontmatter block (`status`,
>    `last-synced-to-plan`) has one.
>
> 6. Run `uv run pytest --co -q 2>&1 | tail -3` to get current test count.
>    Flag any per-package CLAUDE.md that references a stale count.
>
> Report: in-sync or a specific list of outdated sections with proposed text.
> Do NOT edit files unilaterally — propose diffs and wait for user approval.
