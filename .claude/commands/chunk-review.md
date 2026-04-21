---
description: Verify current chunk's exit criteria against the plan. Reports ready-to-merge or blocked with specifics.
argument-hint: <chunk number 0-4>
---

Invoke the `project-manager` subagent with this task:

> Run the `/chunk-review N` workflow for Chunk $ARGUMENTS.
>
> 1. Read plan file `/Users/ahnaftanjid/.claude/plans/ok-i-want-golden-knuth.md` §4 Chunk $ARGUMENTS exit criteria.
> 2. For each criterion, check git log, file presence, test results, bench artifacts (if Chunk 2+), integration tests (if Chunk 3+).
> 3. Produce the exit-criteria verification table per your agent spec.
> 4. End with a single-word verdict: READY-TO-MERGE or BLOCKED, and a bullet list of any blocking issues.
>
> If $ARGUMENTS is missing or not 0-4, ask the user which chunk to review.
