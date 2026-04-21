# docs — navigation

Versioned documentation for Chronoq. v1 is archived (reference only); v2 is current.

## Layout

```
docs/
├── CLAUDE.md           # this file — navigation + freshness rules
├── v1/                 # archived v1 docs (demoted FastAPI+Redis queue era)
└── v2/                 # current v2 docs (library-first: ranker + bench + celery)
    ├── README.md       # v2 landing page + chunk status
    ├── architecture.md # system design, v1→v2 component map, key interfaces
    ├── tech-stack.md   # dependencies, versions, rationale, paid-tier path
    ├── BENCHMARKS.md   # (Chunk 2+) reproduction steps, trace sources, baselines
    ├── INTEGRATIONS.md # (Chunk 3+) Celery quickstart, Hatchet sidecar design
    └── internal/       # ⚠️ gitignored — BRD, PRD, milestones, risks, claude-team
                        #    Project owner's planning docs. Not shipped to OSS consumers.
```

## Where to find what (OSS / contributor audience)

| Question | File |
|---|---|
| How does Chronoq work? | [`v2/architecture.md`](v2/architecture.md) |
| What dependencies, versions, why? | [`v2/tech-stack.md`](v2/tech-stack.md) |
| How do I reproduce the benchmark? | `v2/BENCHMARKS.md` (Chunk 2+) |
| How do I integrate with Celery? | `v2/INTEGRATIONS.md` (Chunk 3+) |
| What was v1? | [`v1/`](v1/) — mentally translate `chronoq_predictor` → `chronoq_ranker` |

## Freshness convention

Every file under `v2/` starts with a frontmatter block:

```yaml
---
status: <draft|current|frozen>
last-synced-to-plan: <YYYY-MM-DD>
source: <upstream plan section>
---
```

Rule for Claude / contributors: **`docs-writer` agent runs `/sync-docs` after every chunk merge** to refresh `last-synced-to-plan` and verify file-path references.

## Internal docs (project owner only)

`v2/internal/` is **gitignored** — it holds the BRD, PRD, milestones, risks register, and Claude-team design docs. These contain portfolio framing, target-hiring-manager language, commit SHAs, and scope-creep rules that aren't useful to OSS consumers. They exist locally for:
- The project owner's planning
- Subagents (`product-manager`, `project-manager`, `library-architect`) that read them as source of truth

The canonical source for internal docs is the plan file at `~/.claude/plans/ok-i-want-golden-knuth.md`. `v2/internal/*.md` are extracts; keep in sync via `/claude-audit` or `/sync-docs`.
