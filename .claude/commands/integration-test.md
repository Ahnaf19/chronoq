---
description: End-to-end smoke check for the Celery integration. Confirms chronoq-celery works after any change to integrations/celery/ or the ranker public API.
---

Invoke the `senior-backend-dev` subagent with this task, then hand off to `qa-validator` to confirm the gate result:

> Run `/integration-test`: end-to-end Celery integration smoke check.
>
> Run the following steps in order. Stop immediately on any non-zero exit and report the failure with full output.
>
> **Step 1 — Celery unit/integration tests**
> ```bash
> uv run pytest tests/celery/ -v
> ```
> Expected: 32+ tests pass. If the count drops below 32, flag it — do not treat it as a pass.
>
> **Step 2 — Toggle demo**
> ```bash
> uv run python integrations/celery/examples/toggle_demo.py
> ```
> Expected: exit 0. The demo prints a summary line; extract `mean_jct_active` and
> `mean_jct_fifo`. Advisory gate: active should be ≥20% lower than fifo. If the
> improvement is <20%, report it as a warning (not a hard failure) and note the
> actual delta.
>
> **Step 3 — Example smoke tests**
> ```bash
> uv run pytest tests/celery/test_examples.py -v
> ```
> Expected: all tests pass.
>
> **Report format:** one table — step, status (PASS/FAIL/WARN), key output.
> End with verdict: INTEGRATION-CLEAN or BLOCKED — <reason>.
>
> **Not in scope:** the Docker A/B stack at `examples/celery-docker/` requires a
> Docker daemon and is verified separately before each release. Do not attempt to
> run it here.
