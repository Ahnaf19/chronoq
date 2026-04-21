---
description: Audit .claude/ directory and all CLAUDE.md files for coherence, staleness, missing agents/commands. Propose diffs.
---

Invoke the `claude-master` subagent with this task:

> Run the full audit workflow per your agent spec:
>
> 1. Agent coverage: every agent referenced in root `CLAUDE.md` §Claude Team exists under `.claude/agents/`; every agent file is referenced somewhere.
> 2. Command coverage: every slash command in root `CLAUDE.md` §Slash Commands exists under `.claude/commands/` (or is marked `Chunk N+` for future).
> 3. CLAUDE.md staleness: check every `CLAUDE.md` in the repo (root, `ranker/`, `demo-server/`, `tests/`, `bench/` if present, `integrations/celery/` if present, `docs/` if present). Flag old names (`chronoq_predictor`, `chronoq_server`, `predictor/`, `server/`), stale file paths, bad line numbers.
> 4. Hook sanity: validate `.claude/settings.json` and `.claude/settings.local.json` — hooks reference real commands, permissions are used.
> 5. Redundancy: flag any content repeated across CLAUDE.md files with >5 identical lines.
> 6. Size: root `CLAUDE.md` target <150 lines, per-package <100 lines. Report current line counts.
>
> Output per your agent spec's format. Do NOT edit anything; propose diffs and wait for user approval.
