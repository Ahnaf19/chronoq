---
description: Verify public API hasn't drifted from library-architect's approved design. Classifies each change as additive, breaking, or internal. Required before any edit to ranker/chronoq_ranker/{ranker,predictor,schemas,config,features,__init__}.py.
---

Invoke the `library-architect` subagent with this task:

> Run the `/architecture-check` workflow per your agent spec.
>
> 1. Read the current public API surface: `ranker/chronoq_ranker/__init__.py` (`__all__` list), `ranker.py` (or `predictor.py` pre-Chunk-1 rename), `schemas.py`, `config.py`, `features.py`, `models/base.py`, `storage/base.py`.
> 2. Compare against the last-approved snapshot. Sources of truth, in order of precedence:
>    - `docs/v2/architecture.md` (committed, current after Chunk 0)
>    - Plan file `/Users/ahnaftanjid/.claude/plans/ok-i-want-golden-knuth.md` §3.3 (low-level interfaces)
> 3. Inspect any uncommitted changes (`git diff ranker/`) and any changes on this branch (`git log main..HEAD -- ranker/`).
> 4. For each delta, classify as `additive` (safe), `breaking` (needs user approval + version bump), or `internal` (allowed).
> 5. Enforce design rules per your agent spec:
>    - No pandas in ranker runtime deps
>    - No server/framework imports in ranker (cross-check with `/boundary-check`)
>    - Every `TaskRecord` carries `feature_schema_version`
>    - `predict_scores` takes a list, returns relative scores
>    - Pairwise label construction within `group_id` windows
>    - Incremental fit via `init_model`; full refit every N incrementals
>    - Thread-safe estimator swap; fit outside the lock
>
> Output per your agent spec's format:
>
> ```
> ## API drift report
> **Additive (safe):** <list>
> **Breaking (needs approval):** <list>
> **Internal (allowed):** <list>
> **Design rule violations:** <list or "none">
> **Verdict:** APPROVED / NEEDS-USER-APPROVAL-FOR-BREAKING-CHANGES
> ```
>
> If breaking changes are present, propose additive alternatives where possible before declaring final verdict.
