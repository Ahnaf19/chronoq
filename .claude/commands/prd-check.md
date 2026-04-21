---
description: Verify current WIP against PRD functional requirements. Flags scope creep and un-implemented must-haves.
---

Invoke the `product-manager` subagent with this task:

> Read `/Users/ahnaftanjid/.claude/plans/ok-i-want-golden-knuth.md` §2 (PRD) and compare against the current state of the monorepo.
>
> 1. For each Must-have feature in §2.4: is it implemented, partially implemented, or pending? Cite file:line for evidence.
> 2. Check the current branch's uncommitted/recent work: does any of it implement a feature NOT in the PRD (scope creep)? If yes, flag it.
> 3. Check non-functional requirements (§2.5): any that are currently violated (e.g., pandas in ranker runtime deps, wheel size)?
>
> Report format:
>
> ```
> ## PRD check
> ### Must-haves
> | Feature | Status | Evidence |
> ### Scope creep
> <list or "None detected.">
> ### NFR violations
> <list or "None detected.">
> **Verdict:** <aligned-with-PRD / drift-detected>
> ```
