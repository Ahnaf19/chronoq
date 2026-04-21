---
description: Print current chunk, weekend, progress, latest test/bench numbers, next exit criterion. Short and scannable.
---

Invoke the `project-manager` subagent with this task:

> Produce a short status report (<20 lines) covering:
>
> 1. Current chunk and weekend (from memory `project_chunk_progress.md`).
> 2. Current git branch and last commit SHA + subject.
> 3. Last test result count (run `uv run pytest --co -q 2>&1 | tail -3` to get count or read from last CI run).
> 4. Last bench numbers if any (`bench/artifacts/results.json` when present, Chunk 2+).
> 5. The ONE next exit criterion to hit.
> 6. Any blocking issues.
>
> Format as a compact status table or short bullet list. Do NOT include a long narrative. Target: a reader at-a-glance understanding in 10 seconds.
